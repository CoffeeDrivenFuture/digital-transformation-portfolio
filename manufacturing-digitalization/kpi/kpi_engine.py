# -*- coding: utf-8 -*-
"""
kpi_engine.py
--------------
US-101 + US-103 megvalósítása:

  US-101: "OEE broken down into Availability, Performance and Quality
           per machine" -- értékek a SQLite adatbázisból, nem hardkódolva.
  US-103: "MTBF and MTTR calculated from the simulation event log" --
           MTBF = átlagos idő két meghibásodás-kezdet között gépenként,
           MTTR = átlagos javítási időtartam gépenként. Mindkettő a
           kpi_daily táblába kerül.

FONTOS SZABÁLY: csak COMPLETED státuszú run_id-kra számolunk. Ez a
Confluence "Hibakezelés" pontjának közvetlen következménye -- egy FAILED
futás részleges adata torzítaná a KPI-ket.

Módszertan (dokumentálva, mert ez egy értelmezési kérdés, nem egyértelmű
képlet):

  - A machine_status_log-ban 3 állapotot naplózunk: working / blocked / repair.
    Ezekből "szegmenseket" építünk (mettől-meddig volt az adott állapotban
    a gép), majd ezeket napi (1440 perces) blokkokra vágjuk szét, hogy a
    kpi_daily tábla sim_day granularitását ki tudjuk szolgálni.

  - Availability = working_idő / (working+blocked+repair összesen), naponta.
    (Ez a klasszikus "Run Time / Planned Production Time" arány egy
    egyszerűsített verziója -- a "blocked" időt letöltött, de nem hasznos
    időnek tekintjük, tehát az Availability-t rontja, ahogy egy valós
    üzemben a anyaghiány miatti állás is rontaná.)

  - Performance = (elméleti ciklusidő × legyártott darabszám) / working_idő,
    naponta, gépenként. Az elméleti ciklusidőt a config/prod_config.py
    MACHINE_PARAMS-ból vesszük (vagy a simulation_runs-hoz tartozó
    machines törzstáblából, ha az felül lett írva egy adott futásnál).

  - Quality = jó darab / összes darab (production_events.is_good), naponta.

  - OEE = Availability × Performance × Quality.

  - MTBF: a 'repair' állapotú szegmensek KEZDŐ időpontjai közötti
    különbségek átlaga, gépenként. Egy adott napra azok a különbségek
    számítanak, amelyeknél a KÉSŐBBI meghibásodás abba a napba esik.

  - MTTR: minden 'repair' szegmens (kezdet -> következő 'working' kezdete)
    időtartamának átlaga, gépenként, aznapra, amelyikbe a szegmens eleje esik.

  Mivel ez szintetikus, oktatási célú adaton fut, a fenti egyszerűsítések
  (pl. napi vágásnál a szegmensek nem "arányosítva" oszlanak meg MTBF/MTTR
  szempontból, csak Availability/Performance szempontból) dokumentált,
  tudatos döntések -- egy éles rendszerben ezt pontosítani kellene.
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
DAY_LENGTH = 24 * 60  # perc


# ---------------------------------------------------------------------------
# SEGÉDFÜGGVÉNYEK
# ---------------------------------------------------------------------------
def _build_segments(status_df: pd.DataFrame, machine_id: str, sim_end_time: float) -> list:
    """
    A machine_status_log sorokból (időpont + állapot) (start, end, status)
    szegmenseket épít egy adott gépre. Az utolsó szegmens a run végéig tart.
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
    {day: {status: duration}} -- egy szegmens, ha átnyúlik napváltáson,
    arányosan szétvágódik a napok között.
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
    segments: az adott gép ÖSSZES (start, end, status) szegmense (nem napra vágva).
    Visszaadja: ({day: mtbf}, {day: mttr})
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
        day = int(starts[i] // DAY_LENGTH)  # a KÉSŐBBI meghibásodás napjához rendeljük
        mtbf_by_day[day].append(gap)

    mtbf_avg = {day: sum(vals) / len(vals) for day, vals in mtbf_by_day.items()}
    mttr_avg = {day: sum(vals) / len(vals) for day, vals in mttr_by_day.items()}
    return mtbf_avg, mttr_avg


# ---------------------------------------------------------------------------
# FŐ SZÁMÍTÁS
# ---------------------------------------------------------------------------
def compute_kpis_for_run(conn, run_id: int) -> pd.DataFrame:
    """
    Kiszámolja az OEE-komponenseket + MTBF/MTTR-t minden gépre, minden napra,
    egy adott run_id-hoz. Visszaad egy DataFrame-et (nem ír adatbázisba --
    azt a write_kpis_to_db() csinálja, hogy a számítás és az írás külön
    tesztelhető legyen).
    """
    run_row = conn.execute(
        "SELECT status, sim_duration FROM simulation_runs WHERE run_id = ?", (run_id,)
    ).fetchone()
    if run_row is None:
        raise ValueError(f"run_id={run_id} nem található a simulation_runs táblában.")
    status, sim_duration = run_row
    if status != "COMPLETED":
        raise ValueError(
            f"run_id={run_id} státusza '{status}', nem 'COMPLETED' -- "
            "a KPI-motor szándékosan csak lezárt futásokat dolgoz fel."
        )

    events_df = pd.read_sql(
        "SELECT sim_time, machine_id, product_id, is_good FROM production_events WHERE run_id = ?",
        conn, params=(run_id,),
    )
    status_df = pd.read_sql(
        "SELECT sim_time, machine_id, status FROM machine_status_log WHERE run_id = ?",
        conn, params=(run_id,),
    )
    # a gép törzsadatból vesszük a cycle_time-ot -- ez tükrözi az adott
    # futáshoz ténylegesen használt (esetlegesen felülírt) paramétert,
    # nem a config default-ját
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
    """A kiszámolt KPI-sorokat beírja (INSERT OR REPLACE) a kpi_daily táblába."""
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
    """Kényelmi wrapper: megnyitja a DB-t, számol, ír, visszaadja az eredményt."""
    conn = get_connection(db_path)
    try:
        kpi_df = compute_kpis_for_run(conn, run_id)
        write_kpis_to_db(conn, kpi_df)
        print(f"[OK] {len(kpi_df)} kpi_daily sor beírva run_id={run_id}-hez.")
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
        print("Nincs COMPLETED státuszú futás az adatbázisban -- futtasd előbb a szimulációt.")
    else:
        df = run_kpi_engine(latest_completed)
        print(df.to_string(index=False))
