# -*- coding: utf-8 -*-
"""
production_sim_db.py
---------------------
An extended version of production_sim_lean.py (SimPy production simulation),
per US-401 (SQLite writing), now using configuration imported from
config/prod_config.py -- see the explanation there about the separation of
structural vs. runtime parameters.

run_simulation() accepts as arguments the parameters that, per Jira US-402,
will be adjustable on the Streamlit dashboard (order pattern, batch size,
sim_time, seed, per-machine cycle_time/quality overrides). If these are not
provided, the defaults from prod_config.py apply -- so the script still runs
the same on its own, without Streamlit, as before.
"""

import os
import sys
import random
import copy

import simpy
import pandas as pd

# --- accessing config/prod_config.py, independent of folder structure ----
BASE_DIR = os.path.dirname(os.path.abspath(__file__))          # .../manufacturing_simulation/simulation
PROJECT_ROOT = os.path.dirname(BASE_DIR)                        # .../manufacturing_simulation
sys.path.insert(0, PROJECT_ROOT)

from config.prod_config import (                                # noqa: E402
    MACHINE_PARAMS as DEFAULT_MACHINE_PARAMS,
    PRODUCT_PARAMS,
    MATERIAL_PARAMS,
    DEFAULT_RANDOM_SEED,
    DEFAULT_SIM_TIME,
    DEFAULT_BATCH_INTERVAL,
    DEFAULT_BATCHES,
)

from db_layer import (                                           # noqa: E402
    get_connection,
    init_db,
    upsert_master_data,
    insert_run_params,
    start_run,
    finish_run,
    bulk_insert_production_events,
    bulk_insert_machine_status,
    bulk_insert_material_stock,
)

DB_PATH = os.path.join(PROJECT_ROOT, "data", "digital_manufacturing.db")


# ---------------------------------------------------------------------------
# MACHINE CLASS (unchanged)
# ---------------------------------------------------------------------------
class Machine:
    def __init__(self, env, name, params, status_log):
        self.env = env
        self.name = name
        self.params = params
        self.status_log = status_log
        self.working = True
        self.repair_time = 0
        self.blocked_time = 0
        self.good_count = 0
        self.bad_count = 0
        self.total_processed = 0
        self.machine_resource = simpy.Resource(env, capacity=1)
        self._log_status("working")
        self.process = env.process(self.breakdown_process())

    def _log_status(self, status):
        self.status_log.append({"time": self.env.now, "machine": self.name, "status": status})

    def breakdown_process(self):
        while True:
            yield self.env.timeout(random.expovariate(1.0 / self.params["mtbf"]))
            self.working = False
            self._log_status("repair")
            down_time = random.expovariate(1.0 / self.params["mttr"])
            self.repair_time += down_time
            yield self.env.timeout(down_time)
            self.working = True
            self._log_status("working")

    def process_product(self, product_type, production_log):
        with self.machine_resource.request() as req:
            yield req
            while not self.working:
                yield self.env.timeout(1)
            yield self.env.timeout(self.params["cycle_time"])
            good = random.random() < self.params["quality"]
            self.total_processed += 1
            if good:
                self.good_count += 1
            else:
                self.bad_count += 1
            production_log.append({
                "time": self.env.now, "machine": self.name,
                "product": product_type, "good": good,
            })


# ---------------------------------------------------------------------------
# MATERIAL SUPPLY (unchanged)
# ---------------------------------------------------------------------------
def pre_production(env, material_stock, material_stock_log, material_logs, material_params):
    while True:
        snapshot = {"time": env.now}
        for mat, qty in material_stock.items():
            snapshot[mat] = qty.level
        material_stock_log.append(snapshot)

        for mat, props in material_params.items():
            if material_stock[mat].level < props["min_level"]:
                env.process(produce_material(env, material_stock, mat, props, material_logs))

        yield env.timeout(1)


def produce_material(env, material_stock, mat, props, material_logs):
    yield env.timeout(props["changeover_time"])
    yield env.timeout(props["batch_size"] * props["unit_time"])
    material_stock[mat].put(props["batch_size"])
    material_logs.append({"time": env.now, "material": mat, "action": "produced", "amount": props["batch_size"]})


# ---------------------------------------------------------------------------
# PRODUCTION PROCESS (unchanged)
# ---------------------------------------------------------------------------
def production_process(env, product_type, machines, material_stock, production_log, machine_status_log):
    route = PRODUCT_PARAMS[product_type]["route"]
    materials = PRODUCT_PARAMS[product_type]["materials"]

    for machine_name in route:
        machine = machines[machine_name]

        if machine_name in materials:
            for mat, qty in materials[machine_name].items():
                wait_start = env.now
                waited = False
                while material_stock[mat].level < qty:
                    if not waited:
                        machine_status_log.append({"time": env.now, "machine": machine_name, "status": "blocked"})
                        waited = True
                    yield env.timeout(1)
                material_stock[mat].get(qty)

                if waited:
                    machine.blocked_time += env.now - wait_start
                    if machine.working:
                        machine_status_log.append({"time": env.now, "machine": machine_name, "status": "working"})

        yield env.timeout(1)
        yield env.process(machine.process_product(product_type, production_log))


def order_generator(env, material_stock, machines, production_log, machine_status_log, order_log, batches, batch_interval):
    for batch in batches:
        order_log.append({"time": env.now, "order": batch})
        for product_type, quantity in batch.items():
            for _ in range(quantity):
                env.process(production_process(
                    env, product_type, machines, material_stock, production_log, machine_status_log
                ))
        yield env.timeout(batch_interval)


# ---------------------------------------------------------------------------
# RUN + DATABASE WRITE
# ---------------------------------------------------------------------------
def run_simulation(
    db_path: str = DB_PATH,
    sim_time: int = DEFAULT_SIM_TIME,
    seed: int = DEFAULT_RANDOM_SEED,
    batches: list = None,
    batch_interval: int = DEFAULT_BATCH_INTERVAL,
    machine_overrides: dict = None,
    material_overrides: dict = None,
    notes: str = "",
):
    """
    Executes one complete simulation run and writes all results to the
    SQLite database. Returns the run_id.

    Parameters that Streamlit will later override (per US-402):
      - sim_time, seed, batches (order pattern), batch_interval
      - machine_overrides: e.g. {"Machine0": {"cycle_time": 5.0, "quality": 0.8}}
        -- only the given machines/fields are overridden, the rest get the
        default value from prod_config.py.
      - material_overrides: e.g. {"material1": {"min_level": 65}} -- same
        merge-over-defaults pattern as machine_overrides, used by the
        MFG-9 "apply recommended stock levels" flow to raise a material's
        reorder threshold without touching its batch_size/unit_time/
        changeover_time.

    If none of these parameters are provided, the DEFAULT_* values from
    prod_config.py apply -- meaning the script also runs standalone,
    without Streamlit.
    """
    random.seed(seed)

    batches = batches if batches is not None else DEFAULT_BATCHES

    # Machine and material parameters: base + optional overrides (we don't
    # mutate the original config dicts).
    machine_params = copy.deepcopy(DEFAULT_MACHINE_PARAMS)
    if machine_overrides:
        for machine_name, overrides in machine_overrides.items():
            machine_params.setdefault(machine_name, {}).update(overrides)

    material_params = copy.deepcopy(MATERIAL_PARAMS)
    if material_overrides:
        for material_name, overrides in material_overrides.items():
            material_params.setdefault(material_name, {}).update(overrides)

    conn = get_connection(db_path)
    init_db(conn)
    upsert_master_data(conn, machine_params, PRODUCT_PARAMS, material_params)

    run_id = start_run(conn, sim_duration=sim_time, random_seed=seed, notes=notes)
    insert_run_params(conn, run_id, machine_params, material_params)

    material_logs, order_log = [], []
    production_log, material_stock_log, machine_status_log = [], [], []

    try:
        env = simpy.Environment()
        machines = {name: Machine(env, name, params, machine_status_log) for name, params in machine_params.items()}

        material_stock = {
            "material1": simpy.Container(env, 50, init=50),
            "material2": simpy.Container(env, 70, init=100),
        }

        env.process(pre_production(env, material_stock, material_stock_log, material_logs, material_params))
        env.process(order_generator(
            env, material_stock, machines, production_log, machine_status_log, order_log,
            batches, batch_interval,
        ))

        env.run(until=sim_time)

        bulk_insert_production_events(conn, run_id, production_log)
        bulk_insert_machine_status(conn, run_id, machine_status_log)
        bulk_insert_material_stock(conn, run_id, material_stock_log, list(material_params.keys()))

        finish_run(conn, run_id, status="COMPLETED")

        print(f"[OK] run_id={run_id} closed with COMPLETED status.")
        print(f"     production_events: {len(production_log)} rows")
        print(f"     machine_status_log: {len(machine_status_log)} rows")

        return run_id

    except Exception:
        finish_run(conn, run_id, status="FAILED")
        print(f"[ERROR] run_id={run_id} set to FAILED status.")
        raise
    finally:
        conn.close()


def quick_sanity_check(db_path: str = DB_PATH, run_id: int = None):
    conn = get_connection(db_path)
    if run_id is None:
        run_id = conn.execute("SELECT MAX(run_id) FROM simulation_runs").fetchone()[0]

    print(f"\n--- Check: run_id = {run_id} ---")
    for table in ["simulation_runs", "production_events", "machine_status_log", "material_stock_log"]:
        limit = "" if table == "simulation_runs" else "LIMIT 5"
        df = pd.read_sql(f"SELECT * FROM {table} WHERE run_id = {run_id} {limit}", conn)
        print(f"\n{table} (first few rows):")
        print(df)

    conn.close()


if __name__ == "__main__":
    new_run_id = run_simulation(notes="US-401 test run (imported from config)")
    quick_sanity_check(run_id=new_run_id)
