# -*- coding: utf-8 -*-
"""
db_layer.py
-----------
The database layer for the US-401 implementation.

This module is responsible for everything related to the SQLite database:
- creating the schema (based on chapter III of case_a_confluence_jira_sql.md),
- starting and finishing a new simulation "run",
- bulk-writing the data collected during the simulation (production_events,
  machine_status_log, material_stock_log).

The goal is that the simulation code (production_sim_db.py) should NOT
contain SQL directly in the main logic — it should just call these
functions. This way the two responsibilities (what happens in the factory /
what goes into the database) stay separate.
"""

import os
import sqlite3
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# 1. SCHEMA
# ---------------------------------------------------------------------------
# This comes almost verbatim from chapter III of case_a_confluence_jira_sql.md.
# One thing I added compared to the spec: a `status` column
# ('RUNNING' | 'COMPLETED' | 'FAILED') on the simulation_runs table, exactly
# as prescribed by the US-401 Jira acceptance criteria:
#   "simulation_runs includes a status flag ... so downstream consumers
#    only process finalized runs."
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS machines (
    machine_id      TEXT PRIMARY KEY,
    name            TEXT,
    mtbf_target     REAL,
    mttr_target     REAL,
    cycle_time_base REAL
);

CREATE TABLE IF NOT EXISTS products (
    product_id      TEXT PRIMARY KEY,
    name            TEXT
);

CREATE TABLE IF NOT EXISTS product_routes (
    product_id      TEXT REFERENCES products(product_id),
    sequence_order  INTEGER,
    machine_id      TEXT REFERENCES machines(machine_id),
    PRIMARY KEY (product_id, sequence_order)
);

CREATE TABLE IF NOT EXISTS materials (
    material_id       TEXT PRIMARY KEY,
    name              TEXT,
    min_level         INTEGER,
    batch_size        INTEGER,
    unit_time         REAL,
    changeover_time   REAL
);

CREATE TABLE IF NOT EXISTS simulation_runs (
    run_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at      TEXT,
    finished_at     TEXT,
    sim_duration    INTEGER,
    random_seed     INTEGER,
    status          TEXT NOT NULL DEFAULT 'RUNNING',  -- RUNNING | COMPLETED | FAILED
    notes           TEXT
);

CREATE TABLE IF NOT EXISTS production_events (
    event_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          INTEGER REFERENCES simulation_runs(run_id),
    sim_time        REAL,
    machine_id      TEXT REFERENCES machines(machine_id),
    product_id      TEXT REFERENCES products(product_id),
    is_good         INTEGER  -- 0/1
);

CREATE TABLE IF NOT EXISTS machine_status_log (
    log_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          INTEGER REFERENCES simulation_runs(run_id),
    sim_time        REAL,
    machine_id      TEXT REFERENCES machines(machine_id),
    status          TEXT   -- 'working' | 'blocked' | 'repair'
);

CREATE TABLE IF NOT EXISTS material_stock_log (
    log_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          INTEGER REFERENCES simulation_runs(run_id),
    sim_time        REAL,
    material_id     TEXT REFERENCES materials(material_id),
    stock_level     REAL
);

-- Per-run snapshots of the machine/material parameters actually used for
-- that run. machines/materials above stay as the single structural master
-- table (product_routes has a real FK into machines, which must stay
-- run-independent) -- but since machine_overrides/material_overrides let
-- each run use different parameter values, something needs to remember
-- what a given past run_id actually used, instead of only ever exposing
-- whatever run_simulation() last wrote into machines/materials. Without
-- this, a query that means "the value used in run_id=X" would silently
-- return the most-recently-run simulation's value instead.
CREATE TABLE IF NOT EXISTS run_machine_params (
    run_id          INTEGER REFERENCES simulation_runs(run_id),
    machine_id      TEXT REFERENCES machines(machine_id),
    mtbf_target     REAL,
    mttr_target     REAL,
    cycle_time_base REAL,
    PRIMARY KEY (run_id, machine_id)
);

CREATE TABLE IF NOT EXISTS run_material_params (
    run_id            INTEGER REFERENCES simulation_runs(run_id),
    material_id       TEXT REFERENCES materials(material_id),
    min_level         REAL,
    batch_size        REAL,
    unit_time         REAL,
    changeover_time   REAL,
    PRIMARY KEY (run_id, material_id)
);

CREATE TABLE IF NOT EXISTS material_recommendations (
    run_id            INTEGER REFERENCES simulation_runs(run_id),
    material_id       TEXT REFERENCES materials(material_id),
    min_stock_level   REAL,
    safety_stock      REAL,
    PRIMARY KEY (run_id, material_id)
);

CREATE TABLE IF NOT EXISTS kpi_daily (
    run_id          INTEGER REFERENCES simulation_runs(run_id),
    sim_day         INTEGER,
    machine_id      TEXT REFERENCES machines(machine_id),
    availability    REAL,
    performance     REAL,
    quality         REAL,
    oee             REAL,
    mtbf            REAL,
    mttr            REAL,
    PRIMARY KEY (run_id, sim_day, machine_id)
);

CREATE TABLE IF NOT EXISTS operators (
    operator_id     TEXT PRIMARY KEY,
    name            TEXT
);

CREATE TABLE IF NOT EXISTS skill_matrix (
    operator_id     TEXT REFERENCES operators(operator_id),
    station_id      TEXT,
    skill_level     INTEGER,
    routine_level   INTEGER,
    PRIMARY KEY (operator_id, station_id)
);

CREATE TABLE IF NOT EXISTS operator_assignments (
    run_id            INTEGER REFERENCES simulation_runs(run_id),
    operator_id       TEXT REFERENCES operators(operator_id),
    station_id        TEXT,
    competency_score  REAL,
    PRIMARY KEY (run_id, operator_id)
);
"""


def get_connection(db_path: str) -> sqlite3.Connection:
    """Opens a connection to the SQLite file, and turns on FK checking."""
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Creates the tables if they don't already exist. Can be run repeatedly, deletes nothing."""
    conn.executescript(SCHEMA_SQL)
    conn.commit()


def upsert_master_data(conn, machines: dict, products: dict, materials: dict) -> None:
    """
    Populates the master data tables (machines, products, product_routes,
    materials) from the simulation configuration. We use INSERT OR REPLACE
    so it stays consistent across multiple runs if the parameters change
    in the meantime.
    """
    cur = conn.cursor()

    for name, params in machines.items():
        cur.execute(
            """INSERT OR REPLACE INTO machines
               (machine_id, name, mtbf_target, mttr_target, cycle_time_base)
               VALUES (?, ?, ?, ?, ?)""",
            (name, name, params["mtbf"], params["mttr"], params["cycle_time"]),
        )

    for product_id, cfg in products.items():
        cur.execute(
            "INSERT OR REPLACE INTO products (product_id, name) VALUES (?, ?)",
            (product_id, f"Product {product_id}"),
        )
        for seq, machine_id in enumerate(cfg["route"]):
            cur.execute(
                """INSERT OR REPLACE INTO product_routes
                   (product_id, sequence_order, machine_id) VALUES (?, ?, ?)""",
                (product_id, seq, machine_id),
            )

    for material_id, props in materials.items():
        cur.execute(
            """INSERT OR REPLACE INTO materials
               (material_id, name, min_level, batch_size, unit_time, changeover_time)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                material_id,
                material_id,
                props["min_level"],
                props["batch_size"],
                props["unit_time"],
                props["changeover_time"],
            ),
        )

    conn.commit()


def insert_run_params(conn, run_id: int, machines: dict, materials: dict) -> None:
    """
    Snapshots the machine/material parameters actually used for this run
    into run_machine_params / run_material_params, so a later query for
    "what did run_id=X actually use" doesn't have to rely on the
    machines/materials master tables, which get overwritten by every run.
    """
    cur = conn.cursor()

    for machine_id, params in machines.items():
        cur.execute(
            """INSERT OR REPLACE INTO run_machine_params
               (run_id, machine_id, mtbf_target, mttr_target, cycle_time_base)
               VALUES (?, ?, ?, ?, ?)""",
            (run_id, machine_id, params["mtbf"], params["mttr"], params["cycle_time"]),
        )

    for material_id, props in materials.items():
        cur.execute(
            """INSERT OR REPLACE INTO run_material_params
               (run_id, material_id, min_level, batch_size, unit_time, changeover_time)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                run_id, material_id,
                props["min_level"], props["batch_size"], props["unit_time"], props["changeover_time"],
            ),
        )

    conn.commit()


def start_run(conn: sqlite3.Connection, sim_duration: int, random_seed: int, notes: str = "") -> int:
    """
    Inserts a new row into the simulation_runs table with 'RUNNING' status,
    and returns the new run_id. This identifier must be attached to every
    further logged event.
    """
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO simulation_runs (started_at, sim_duration, random_seed, status, notes)
           VALUES (?, ?, ?, 'RUNNING', ?)""",
        (datetime.now(timezone.utc).isoformat(), sim_duration, random_seed, notes),
    )
    conn.commit()
    return cur.lastrowid


def finish_run(conn: sqlite3.Connection, run_id: int, status: str) -> None:
    """
    Closes out a run: writes the finish timestamp and the final status
    ('COMPLETED' or 'FAILED'). Per the Confluence spec's "Error handling"
    section: if the simulation aborts with an error, the partial data
    stays in the database, but the KPI engine only processes COMPLETED runs.
    """
    assert status in ("COMPLETED", "FAILED"), "status can only be COMPLETED or FAILED"
    conn.execute(
        "UPDATE simulation_runs SET finished_at = ?, status = ? WHERE run_id = ?",
        (datetime.now(timezone.utc).isoformat(), status, run_id),
    )
    conn.commit()


def bulk_insert_production_events(conn, run_id: int, events: list) -> None:
    """events: [{"time":..., "machine":..., "product":..., "good": bool}, ...]"""
    rows = [
        (run_id, e["time"], e["machine"], e["product"], int(bool(e["good"])))
        for e in events
    ]
    conn.executemany(
        """INSERT INTO production_events (run_id, sim_time, machine_id, product_id, is_good)
           VALUES (?, ?, ?, ?, ?)""",
        rows,
    )
    conn.commit()


def bulk_insert_machine_status(conn, run_id: int, events: list) -> None:
    """events: [{"time":..., "machine":..., "status": "working"|"blocked"|"repair"}, ...]"""
    rows = [(run_id, e["time"], e["machine"], e["status"]) for e in events]
    conn.executemany(
        """INSERT INTO machine_status_log (run_id, sim_time, machine_id, status)
           VALUES (?, ?, ?, ?)""",
        rows,
    )
    conn.commit()


def bulk_insert_material_stock(conn, run_id: int, snapshots: list, material_ids: list) -> None:
    """
    snapshots: [{"time":..., "material1": <level>, "material2": <level>, ...}, ...]
    This converts "wide" format stock_snapshots into "long" format rows
    (one row / material / timestamp), because the machine_status_log table
    is normalized the same way.
    """
    rows = []
    for snap in snapshots:
        for mat in material_ids:
            if mat in snap:
                rows.append((run_id, snap["time"], mat, snap[mat]))
    conn.executemany(
        """INSERT INTO material_stock_log (run_id, sim_time, material_id, stock_level)
           VALUES (?, ?, ?, ?)""",
        rows,
    )
    conn.commit()
