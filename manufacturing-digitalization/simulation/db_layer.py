# -*- coding: utf-8 -*-
"""
db_layer.py
-----------
US-401 megvalósításának adatbázis-rétege.

Ez a modul felel mindenért, ami az SQLite adatbázissal kapcsolatos:
- a séma létrehozása (a case_a_confluence_jira_sql.md III. fejezete alapján),
- egy új szimulációs "run" indítása és lezárása,
- a szimuláció közben gyűjtött adatok (production_events, machine_status_log,
  material_stock_log) tömeges beírása.

A cél, hogy a szimulációs kód (production_sim_db.py) NE tartalmazzon SQL-t
közvetlenül a fő logikában — csak meghívja ezeket a függvényeket. Így a két
felelősség (mi történik a gyárban / mi kerül az adatbázisba) külön marad.
"""

import os
import sqlite3
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# 1. SÉMA
# ---------------------------------------------------------------------------
# Ez majdnem szó szerint a case_a_confluence_jira_sql.md III. fejezetéből jön.
# Egy dolgot hozzáadtam a specifikációhoz képest: a simulation_runs táblába
# egy `status` oszlopot ('RUNNING' | 'COMPLETED' | 'FAILED'), pontosan úgy,
# ahogy azt a US-401 Jira acceptance criteria előírja:
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
    """Megnyit egy kapcsolatot az SQLite fájlhoz, és bekapcsolja az FK-ellenőrzést."""
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """Létrehozza a táblákat, ha még nem léteznek. Ismételten futtatható, nem töröl semmit."""
    conn.executescript(SCHEMA_SQL)
    conn.commit()


def upsert_master_data(conn, machines: dict, products: dict, materials: dict) -> None:
    """
    Feltölti a törzsadat-táblákat (machines, products, product_routes, materials)
    a szimuláció konfigurációjából. INSERT OR REPLACE-t használunk, hogy több
    futtatás között is konzisztens maradjon, ha időközben módosulnak a paraméterek.
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


def start_run(conn: sqlite3.Connection, sim_duration: int, random_seed: int, notes: str = "") -> int:
    """
    Új sort szúr be a simulation_runs táblába 'RUNNING' státusszal, és
    visszaadja az új run_id-t. Ezt az azonosítót kell minden további
    logolt eseményhez csatolni.
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
    Lezár egy futást: beírja a befejezés időpontját és a végső státuszt
    ('COMPLETED' vagy 'FAILED'). A Confluence spec "Hibakezelés" pontja
    szerint: ha a szimuláció hibával megszakad, a részleges adat az
    adatbázisban marad, de a KPI-motor csak COMPLETED futásokat dolgoz fel.
    """
    assert status in ("COMPLETED", "FAILED"), "status csak COMPLETED vagy FAILED lehet"
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
    Ez a "wide" formátumú stock_snapshot-okat alakítja "long" formátumú
    sorokká (egy sor / anyag / időpont), mert a machine_status_log tábla is
    így van normalizálva.
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
