# -*- coding: utf-8 -*-
"""
kpi_engine.py
--------------
Implements US-101 + US-103.

US-101 wants OEE broken into Availability, Performance and Quality per
machine, computed from the SQLite database rather than hardcoded. US-103
wants MTBF and MTTR calculated from the simulation event log: MTBF is the
average time between two failure starts per machine, MTTR is the average
repair duration per machine. Both land in the kpi_daily table.

We only compute for run_ids with COMPLETED status -- per the Confluence
"Error handling" section, a FAILED run's partial data would distort the
KPIs.

A note on methodology, since this isn't a single unambiguous formula.
machine_status_log logs three states per machine: working / blocked /
repair. We turn these into segments (from-to for each state), then cut
them into daily (1440-minute) blocks to match the kpi_daily table's
sim_day granularity.

Availability = working time / (working + blocked + repair), per day. It's
a simplified "Run Time / Planned Production Time" -- blocked time counts
against Availability, the same way a material-shortage stoppage would on
a real line.

Performance = (ideal cycle time x pieces produced) / working time, per day
per machine. The ideal cycle time comes from config/prod_config.py
MACHINE_PARAMS, or from the machines master table tied to the run if it
was overridden.

Quality = good pieces / total pieces (production_events.is_good), per day.
OEE = Availability x Performance x Quality.

MTBF is the average gap between the start timestamps of consecutive
'repair' segments per machine; a gap is counted on whichever day the
later failure falls in. MTTR is the average duration of each 'repair'
segment (start to the next 'working' start), counted on the day the
segment starts.

This runs on synthetic data, so a couple of the choices above are
deliberate simplifications rather than universal truths -- segments that
cross a day boundary get split proportionally for Availability/Performance
but not for MTBF/MTTR. A production system would want this refined.
"""

import os
import sys
from collections import defaultdict

import pandas as pd

BASE_DIR = os.path.dirname(os.path.abspath(__file__))       # .../case-a/kpi
PROJECT_ROOT = os.path.dirname(BASE_DIR)                     # .../case-a
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "simulation"))

from config.prod_config import MACHINE_PARAMS as DEFAULT_MACHINE_PARAMS  # noqa: E402
from db_layer import get_connection                                       # noqa: E402

DB_PATH = os.path.join(PROJECT_ROOT, "data", "digital_manufacturing.db")
DAY_LENGTH = 24 * 60  # minutes


# ---------------------------------------------------------------------------
# HELPER FUNCTIONS
# ---------------------------------------------------------------------------
def _build_segments(status_df: pd.DataFrame, machine_id: str, sim_end_time: float) -> list:
    """
    Builds (start, end, status) segments for a given machine from the
    machine_status_log rows (timestamp + status). The last segment lasts
    until the end of the run.
    """
    df = status_df[status_df["machine_id"] == machine_id].sort_values("sim_time")
    times = df["sim_time"].tolist()
    statuses = df["status"].tolist()

    segments = []
    for i in range(len(times)):
        start = times[i]
        end = times[i + 1] if i + 1 < len(times) else sim_end_time
        if end > start:
            segments.append((start, end, statuses[i]))
    return segments


def _split_segments_by_day(segments: list) -> dict:
    """
    {day: {status: duration}} -- if a segment crosses a day boundary, it
    gets proportionally split between the days.
    """
    day_status_duration = defaultdict(lambda: defaultdict(float))
    for start, end, status in segments:
        t = start
        while t < end:
            day = int(t // DAY_LENGTH)
            day_end = (day + 1) * DAY_LENGTH
            seg_end = min(end, day_end)
            day_status_duration[day][status] += seg_end - t
            t = seg_end
    return day_status_duration


def _mtbf_mttr_by_day(segments: list) -> tuple:
    """
    segments: ALL (start, end, status) segments of the given machine (not cut by day).
    Returns: ({day: mtbf}, {day: mttr})
    """
    repair_segments = [(s, e) for s, e, st in segments if st == "repair"]
    repair_segments.sort(key=lambda x: x[0])

    mttr_by_day = defaultdict(list)
    for start, end in repair_segments:
        day = int(start // DAY_LENGTH)
        mttr_by_day[day].append(end - start)

    mtbf_by_day = defaultdict(list)
    starts = [s for s, _ in repair_segments]
    for i in range(1, len(starts)):
        gap = starts[i] - starts[i - 1]
        day = int(starts[i] // DAY_LENGTH)  # assigned to the day of the LATER failure
        mtbf_by_day[day].append(gap)

    mtbf_avg = {day: sum(vals) / len(vals) for day, vals in mtbf_by_day.items()}
    mttr_avg = {day: sum(vals) / len(vals) for day, vals in mttr_by_day.items()}
    return mtbf_avg, mttr_avg


# ---------------------------------------------------------------------------
# MAIN CALCULATION
# ---------------------------------------------------------------------------
def compute_kpis_for_run(conn, run_id: int) -> pd.DataFrame:
    """
    Computes the OEE components + MTBF/MTTR for every machine, every day,
    for a given run_id. Returns a DataFrame (does not write to the
    database -- write_kpis_to_db() does that, so the calculation and the
    writing can be tested separately).
    """
    run_row = conn.execute(
        "SELECT status, sim_duration FROM simulation_runs WHERE run_id = ?", (run_id,)
    ).fetchone()
    if run_row is None:
        raise ValueError(f"run_id={run_id} not found in the simulation_runs table.")
    status, sim_duration = run_row
    if status != "COMPLETED":
        raise ValueError(
            f"run_id={run_id} has status '{status}', not 'COMPLETED' -- "
            "the KPI engine deliberately only processes finalized runs."
        )

    events_df = pd.read_sql(
        "SELECT sim_time, machine_id, product_id, is_good FROM production_events WHERE run_id = ?",
        conn, params=(run_id,),
    )
    status_df = pd.read_sql(
        "SELECT sim_time, machine_id, status FROM machine_status_log WHERE run_id = ?",
        conn, params=(run_id,),
    )
    # Take cycle_time from this run's own snapshot (run_machine_params), not
    # the machines master table -- machines gets overwritten by every run,
    # so reading it directly would silently return whichever run was
    # simulated most recently instead of what run_id actually used.
    machines_df = pd.read_sql(
        "SELECT machine_id, cycle_time_base FROM run_machine_params WHERE run_id = ?",
        conn, params=(run_id,),
    )
    if machines_df.empty:
        # Runs from before run_machine_params existed have no snapshot --
        # fall back to the master table (same imprecision these runs
        # already had, not a regression).
        machines_df = pd.read_sql("SELECT machine_id, cycle_time_base FROM machines", conn)
    cycle_time_by_machine = dict(zip(machines_df["machine_id"], machines_df["cycle_time_base"]))

    machine_ids = sorted(set(status_df["machine_id"]).union(DEFAULT_MACHINE_PARAMS.keys()))

    rows = []
    for machine_id in machine_ids:
        segments = _build_segments(status_df, machine_id, sim_end_time=sim_duration)
        if not segments:
            continue
        day_status_duration = _split_segments_by_day(segments)
        mtbf_by_day, mttr_by_day = _mtbf_mttr_by_day(segments)

        machine_events = events_df[events_df["machine_id"] == machine_id].copy()
        machine_events["sim_day"] = (machine_events["sim_time"] // DAY_LENGTH).astype(int)

        ideal_cycle_time = cycle_time_by_machine.get(machine_id, DEFAULT_MACHINE_PARAMS[machine_id]["cycle_time"])

        for day, status_durations in sorted(day_status_duration.items()):
            working = status_durations.get("working", 0.0)
            blocked = status_durations.get("blocked", 0.0)
            repair = status_durations.get("repair", 0.0)
            total = working + blocked + repair
            if total <= 0:
                continue

            day_events = machine_events[machine_events["sim_day"] == day]
            total_count = len(day_events)
            good_count = int(day_events["is_good"].sum()) if total_count else 0

            availability = working / total
            performance = (ideal_cycle_time * total_count / working) if working > 0 else 0.0
            quality = (good_count / total_count) if total_count > 0 else 0.0
            oee = availability * performance * quality

            rows.append({
                "run_id": run_id,
                "sim_day": day,
                "machine_id": machine_id,
                "availability": round(availability, 4),
                "performance": round(performance, 4),
                "quality": round(quality, 4),
                "oee": round(oee, 4),
                "mtbf": round(mtbf_by_day.get(day, 0.0), 2) if day in mtbf_by_day else None,
                "mttr": round(mttr_by_day.get(day, 0.0), 2) if day in mttr_by_day else None,
            })

    return pd.DataFrame(rows)


def write_kpis_to_db(conn, kpi_df: pd.DataFrame) -> None:
    """Writes the computed KPI rows (INSERT OR REPLACE) into the kpi_daily table."""
    cur = conn.cursor()
    for _, row in kpi_df.iterrows():
        cur.execute(
            """INSERT OR REPLACE INTO kpi_daily
               (run_id, sim_day, machine_id, availability, performance, quality, oee, mtbf, mttr)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                int(row["run_id"]), int(row["sim_day"]), row["machine_id"],
                row["availability"], row["performance"], row["quality"], row["oee"],
                row["mtbf"], row["mttr"],
            ),
        )
    conn.commit()


def run_kpi_engine(run_id: int, db_path: str = DB_PATH) -> pd.DataFrame:
    """Convenience wrapper: opens the DB, computes, writes, returns the result."""
    conn = get_connection(db_path)
    try:
        kpi_df = compute_kpis_for_run(conn, run_id)
        write_kpis_to_db(conn, kpi_df)
        print(f"[OK] {len(kpi_df)} kpi_daily rows written for run_id={run_id}.")
        return kpi_df
    finally:
        conn.close()


if __name__ == "__main__":
    conn = get_connection(DB_PATH)
    latest_completed = conn.execute(
        "SELECT MAX(run_id) FROM simulation_runs WHERE status = 'COMPLETED'"
    ).fetchone()[0]
    conn.close()

    if latest_completed is None:
        print("No run with COMPLETED status in the database -- run the simulation first.")
    else:
        df = run_kpi_engine(latest_completed)
        print(df.to_string(index=False))
