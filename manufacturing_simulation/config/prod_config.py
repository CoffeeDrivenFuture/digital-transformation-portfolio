# -*- coding: utf-8 -*-
"""
prod_config.py
---------------
Single, central place for the factory's configuration, so the simulation
(production_sim_db.py), the KPI engine (kpi_engine.py), and the Streamlit
dashboard don't each duplicate the same machine parameters, routes, and
materials -- everyone imports from here.

The file has two parts:

  1. STRUCTURAL CONFIGURATION -- the factory's physical layout: what
     machines exist, what route a given product travels through them,
     what raw material they require. This isn't a Streamlit widget; if it
     changed from run to run, it wouldn't be a "what if" simulation, it'd
     be a different factory.

  2. DEFAULT RUNTIME PARAMETERS -- everything Jira US-402 lists as
     Streamlit input (order pattern, batch size, product mix, machine
     cycle time, MTBF/MTTR, quality rate). Only the defaults live here;
     run_simulation() in production_sim_db.py takes the same values as
     arguments and overrides these defaults whenever Streamlit or another
     caller supplies them.

cycle_time and quality in MACHINE_PARAMS also count as runtime parameters
per Jira -- the user can adjust them on the dashboard -- but since they
need to be set per machine rather than as one global default, the
MACHINE_PARAMS dict itself is what Streamlit overrides per machine (see
run_simulation's `machine_overrides` argument).
"""

# ---------------------------------------------------------------------------
# 1. STRUCTURAL CONFIGURATION — the factory's layout, rarely/never changes
# ---------------------------------------------------------------------------

# Which machine has which base MTBF/MTTR/cycle_time/quality.
# The cycle_time and quality values can be overridden per run by Streamlit
# (see run_simulation(machine_overrides=...)), but the LIST of machines
# (Machine0..Machine4) is structural data.
MACHINE_PARAMS = {
    "Machine0": {"mtbf": 800, "mttr": 50, "quality": 0.75, "cycle_time": 4.5},
    "Machine1": {"mtbf": 500, "mttr": 60, "quality": 0.66, "cycle_time": 5.3},
    "Machine2": {"mtbf": 200, "mttr": 200, "quality": 0.8, "cycle_time": 6.1},
    "Machine3": {"mtbf": 1200, "mttr": 100, "quality": 0.9, "cycle_time": 7.2},
    "Machine4": {"mtbf": 500, "mttr": 60, "quality": 0.8, "cycle_time": 5.5},
}

# Which product goes through which machine line, and how much of which raw
# material it requires at which machine. This is the factory's topology,
# so it's structural.
PRODUCT_PARAMS = {
    "A": {
        "route": ["Machine0", "Machine2", "Machine3"],
        "materials": {"Machine0": {"material1": 1}, "Machine2": {"material2": 2}},
    },
    "B": {
        "route": ["Machine1", "Machine3", "Machine4"],
        "materials": {"Machine1": {"material1": 2}, "Machine4": {"material2": 3}},
    },
}

# Raw material replenishment rules (min level, batch size, production/changeover time).
# This is also structural: how long it takes to replenish "material1" is a
# property of the supplier/manufacturing process, not a "what if" question.
MATERIAL_PARAMS = {
    "material1": {"min_level": 40, "batch_size": 15, "unit_time": 4, "changeover_time": 100},
    "material2": {"min_level": 90, "batch_size": 30, "unit_time": 6, "changeover_time": 150},
}


# ---------------------------------------------------------------------------
# 2. DEFAULT RUNTIME PARAMETERS — these will be overridden by Streamlit
# ---------------------------------------------------------------------------

DEFAULT_RANDOM_SEED = 42
DEFAULT_SIM_TIME = 5 * 24 * 60  # 5 days in minutes
DEFAULT_BATCH_INTERVAL = 12 * 60  # 720 minutes
DEFAULT_TOTAL_PIECES_PER_BATCH = 40

# Business/management OEE target -- distinct from the generic industry
# benchmarks (60% typical, 85% world-class) shown in the dashboard. This is
# a reporting/goal-setting value, not a physical simulation input, so it
# lives here as a simple constant rather than something Streamlit overrides
# per-run.
TARGET_OEE = 0.75

# Order pattern: product mix per batch.
# The Jira US-201 "configurable batch size, interval, and product mix"
# requirement lands here -- this is most likely what Streamlit will
# regenerate with a slider triplet (batch size, interval, A/B ratio)
# instead of using this hand-written list.
DEFAULT_BATCHES = [
    {"A": 18, "B": 22}, {"A": 30, "B": 10}, {"A": 12, "B": 28},
    {"A": 27, "B": 13}, {"A": 20, "B": 20}, {"A": 17, "B": 23},
    {"A": 17, "B": 23}, {"A": 22, "B": 18}, {"A": 28, "B": 12},
    {"A": 15, "B": 25},
]


def generate_batches(n_batches: int, total_per_batch: int, a_share: float = 0.5, seed: int = None) -> list:
    """
    Helper function that lets Streamlit (or anyone) generate a new order
    pattern instead of using the hardcoded DEFAULT_BATCHES.

    a_share: the approximate share of the "A" product (between 0-1). The
    exact quantity per batch varies slightly due to randomness, to keep
    the pattern realistic.
    """
    import random as _random

    rng = _random.Random(seed)
    batches = []
    for _ in range(n_batches):
        a_qty = max(0, min(total_per_batch, round(rng.gauss(total_per_batch * a_share, total_per_batch * 0.1))))
        b_qty = total_per_batch - a_qty
        batches.append({"A": a_qty, "B": b_qty})
    return batches
