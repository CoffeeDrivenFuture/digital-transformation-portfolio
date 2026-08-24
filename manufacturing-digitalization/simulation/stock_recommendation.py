# -*- coding: utf-8 -*-
"""
stock_recommendation.py
------------------------
Implements US-202: a recommended minimum stock level per material, derived
from a completed run's actual consumption -- not the structural default in
prod_config.py, which is a starting guess, not a measured value.

Kept separate from db_layer.py (schema/CRUD only) and out of
dashboard/app.py (UI only) because this encodes real domain logic: how
consumption rate, changeover time, and batch size combine into a
safety-stock number.
"""

import os
import sys

import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))       # .../case-a/simulation
PROJECT_ROOT = os.path.dirname(BASE_DIR)                     # .../case-a
sys.path.insert(0, PROJECT_ROOT)

from config.prod_config import PRODUCT_PARAMS  # noqa: E402


def compute_min_stock_levels(conn, run_id: int, safety_factor: float = 1.2) -> dict:
    """
    For a completed run, computes a recommended minimum stock level per
    material from actual consumption during that run:
      consumption_rate = total consumed / sim_duration            (units/min)
      recovery_time = changeover_time + (batch_size / consumption_rate)
      base_min_stock = consumption_rate * recovery_time
      min_stock_level = base_min_stock * safety_factor
      safety_stock = min_stock_level - base_min_stock

    recovery_time is the worst-case window the line could still be
    consuming material at its observed rate while a fresh batch is
    changed over to and produced; min_stock_level sizes the buffer to
    survive that window, with safety_factor as headroom above the bare
    minimum.

    Total consumption per material is reconstructed exactly (not
    estimated) from production_events: each row is one unit processed at
    one machine, and PRODUCT_PARAMS says exactly how much of which
    material that (product, machine) combination consumes -- the same
    mapping production_process() itself uses in production_sim_db.py.
    This is more reliable than reading net drops out of
    material_stock_log, where a consumption dip and a replenishment `put`
    can land in the same 1-minute snapshot and cancel out.

    Returns {material_id: {"base_min_stock": ..., "min_stock_level": ...,
                            "safety_stock": ...}}.
    """
    # Read batch_size/changeover_time from this run's own snapshot, not the
    # materials master table -- that table gets overwritten by every run,
    # so reading it directly would return whichever run was simulated most
    # recently instead of what this run_id actually used.
    materials = pd.read_sql(
        "SELECT material_id, min_level, batch_size, unit_time, changeover_time "
        "FROM run_material_params WHERE run_id = ?",
        conn, params=(run_id,),
    )
    if materials.empty:
        # Runs from before run_material_params existed have no snapshot --
        # fall back to the master table (same imprecision these runs
        # already had, not a regression).
        materials = pd.read_sql("SELECT * FROM materials", conn)
    sim_duration = conn.execute(
        "SELECT sim_duration FROM simulation_runs WHERE run_id = ?", (run_id,)
    ).fetchone()[0]

    events = pd.read_sql(
        "SELECT product_id, machine_id, COUNT(*) as n FROM production_events "
        "WHERE run_id = ? GROUP BY product_id, machine_id",
        conn, params=(run_id,),
    )

    total_consumed = {mat_id: 0.0 for mat_id in materials["material_id"]}
    for _, row in events.iterrows():
        machine_materials = (
            PRODUCT_PARAMS.get(row["product_id"], {})
            .get("materials", {})
            .get(row["machine_id"], {})
        )
        for mat_id, qty_per_unit in machine_materials.items():
            total_consumed[mat_id] = total_consumed.get(mat_id, 0.0) + qty_per_unit * row["n"]

    results = {}
    for _, mat in materials.iterrows():
        mat_id = mat["material_id"]
        rate = (total_consumed.get(mat_id, 0.0) / sim_duration) if sim_duration else 0.0
        if rate <= 0:
            # Never consumed during this run -- no basis for a recommendation.
            results[mat_id] = {"base_min_stock": 0.0, "min_stock_level": 0.0, "safety_stock": 0.0}
            continue
        recovery_time = mat["changeover_time"] + (mat["batch_size"] / rate)
        base_min_stock = rate * recovery_time
        min_stock_level = base_min_stock * safety_factor
        results[mat_id] = {
            "base_min_stock": base_min_stock,
            "min_stock_level": min_stock_level,
            "safety_stock": min_stock_level - base_min_stock,
        }
    return results


def save_stock_recommendations(conn, run_id: int, recommendations: dict) -> None:
    """Writes (INSERT OR REPLACE) computed recommendations into material_recommendations."""
    rows = [
        (run_id, mat_id, r["min_stock_level"], r["safety_stock"])
        for mat_id, r in recommendations.items()
    ]
    conn.executemany(
        """INSERT OR REPLACE INTO material_recommendations
           (run_id, material_id, min_stock_level, safety_stock)
           VALUES (?, ?, ?, ?)""",
        rows,
    )
    conn.commit()
