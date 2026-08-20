# -*- coding: utf-8 -*-
"""
app.py -- Case A Streamlit dashboard (US-402)

Acceptance criteria, amit ez a script teljesít:
  [x] A dashboard SQL-lekérdezésekkel olvas az SQLite fájlból.
  [x] "Run new simulation" gomb friss futtatást indít és frissíti a nézetet.
  [x] A futtatási paraméterek (order pattern, batch size, product mix,
      gépenkénti cycle_time, MTBF/MTTR, quality rate) az oldalsávon
      állíthatók, nincsenek hardkódolva.

Emellé bónuszként megjeleníti a már kész KPI-motor (US-101/US-103) és a
machine_status_log (US-203 -- gépállapot idővonal) eredményeit is, mert
ezek nélkül a dashboard üres lenne.

FONTOS, amit itt szándékosan NEM implementáltam (backlogban maradt):
  - US-102 (SQDCP kategória/tier szűrő) -- a jelenlegi séma nem tartalmaz
    SQDCP-kategorizálást a KPI-khez, ez külön story.
  - US-204 (Yamazumi chart) -- külön komponens lesz, nem ide való.
  - US-403 (Power BI) -- másik eszköz, nem ez a fájl dolga.
"""

import os
import sys

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# --- config/simulation/kpi modulok elérése, mappaszerkezettől függetlenül --
BASE_DIR = os.path.dirname(os.path.abspath(__file__))            # .../case-a/dashboard
PROJECT_ROOT = os.path.dirname(BASE_DIR)                          # .../case-a
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "simulation"))
sys.path.insert(0, os.path.join(PROJECT_ROOT, "kpi"))

from config.prod_config import (                                   # noqa: E402
    MACHINE_PARAMS as DEFAULT_MACHINE_PARAMS,
    DEFAULT_SIM_TIME,
    DEFAULT_RANDOM_SEED,
    DEFAULT_BATCH_INTERVAL,
    DEFAULT_TOTAL_PIECES_PER_BATCH,
    generate_batches,
)
from db_layer import get_connection                                # noqa: E402
from production_sim_db import run_simulation, DB_PATH               # noqa: E402
from kpi_engine import run_kpi_engine, _build_segments               # noqa: E402

DAY_LENGTH = 24 * 60

st.set_page_config(page_title="Manufacturing Digitalization", layout="wide")


# ---------------------------------------------------------------------------
# ADATBETÖLTŐ SEGÉDFÜGGVÉNYEK (mindegyik SQL-lekérdezés az SQLite fájlból)
# ---------------------------------------------------------------------------
def get_completed_runs() -> pd.DataFrame:
    conn = get_connection(DB_PATH)
    try:
        return pd.read_sql(
            """SELECT run_id, started_at, sim_duration, random_seed, notes
               FROM simulation_runs WHERE status = 'COMPLETED'
               ORDER BY run_id DESC""",
            conn,
        )
    finally:
        conn.close()


def get_kpi_daily(run_id: int) -> pd.DataFrame:
    conn = get_connection(DB_PATH)
    try:
        return pd.read_sql(
            "SELECT * FROM kpi_daily WHERE run_id = ? ORDER BY machine_id, sim_day",
            conn, params=(run_id,),
        )
    finally:
        conn.close()


def get_machine_status_log(run_id: int) -> pd.DataFrame:
    conn = get_connection(DB_PATH)
    try:
        return pd.read_sql(
            "SELECT sim_time, machine_id, status FROM machine_status_log WHERE run_id = ?",
            conn, params=(run_id,),
        )
    finally:
        conn.close()


def get_run_meta(run_id: int) -> dict:
    conn = get_connection(DB_PATH)
    try:
        row = conn.execute(
            "SELECT started_at, finished_at, sim_duration, random_seed, notes FROM simulation_runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        return {
            "started_at": row[0], "finished_at": row[1],
            "sim_duration": row[2], "random_seed": row[3], "notes": row[4],
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# OLDALSÁV -- futtatási paraméterek + "Run new simulation"
# ---------------------------------------------------------------------------
st.sidebar.header("⚙️ Szimulációs paraméterek")

sim_days = st.sidebar.slider("Szimuláció hossza (nap)", 1, 10, DEFAULT_SIM_TIME // DAY_LENGTH)
seed = st.sidebar.number_input("Random seed", value=DEFAULT_RANDOM_SEED, step=1)

st.sidebar.subheader("Rendelési minta (order pattern)")
n_batches = st.sidebar.slider("Rendelések (batch-ek) száma", 3, 30, 10)
batch_interval_h = st.sidebar.slider("Rendelések közti idő (óra)", 2, 24, DEFAULT_BATCH_INTERVAL // 60)
total_per_batch = st.sidebar.slider("Batch méret (db/rendelés)", 10, 100, DEFAULT_TOTAL_PIECES_PER_BATCH)
a_share = st.sidebar.slider("'A' termék aránya a mixben", 0.0, 1.0, 0.5, step=0.05)

st.sidebar.subheader("Gépenkénti felülírás (opcionális)")
st.sidebar.caption("Ha nem nyitod ki egy gép sorát, az az alap (prod_config.py) értékét kapja.")

machine_overrides = {}
for machine_name, base_params in DEFAULT_MACHINE_PARAMS.items():
    with st.sidebar.expander(machine_name):
        override_on = st.checkbox("Felülírás bekapcsolása", key=f"ov_{machine_name}")
        cycle_time = st.slider(
            "Ciklusidő (perc)", 1.0, 15.0, float(base_params["cycle_time"]),
            step=0.1, key=f"ct_{machine_name}", disabled=not override_on,
        )
        quality = st.slider(
            "Minőségi arány", 0.5, 1.0, float(base_params["quality"]),
            step=0.01, key=f"q_{machine_name}", disabled=not override_on,
        )
        mtbf = st.slider(
            "MTBF cél (perc)", 100, 2000, int(base_params["mtbf"]),
            step=50, key=f"mtbf_{machine_name}", disabled=not override_on,
        )
        mttr = st.slider(
            "MTTR cél (perc)", 10, 300, int(base_params["mttr"]),
            step=10, key=f"mttr_{machine_name}", disabled=not override_on,
        )
        if override_on:
            machine_overrides[machine_name] = {
                "cycle_time": cycle_time, "quality": quality,
                "mtbf": mtbf, "mttr": mttr,
            }

run_clicked = st.sidebar.button("🚀 Run new simulation", type="primary", width="stretch")

if run_clicked:
    batches = generate_batches(n_batches, total_per_batch, a_share=a_share, seed=int(seed))
    with st.spinner("Szimuláció fut..."):
        new_run_id = run_simulation(
            sim_time=sim_days * DAY_LENGTH,
            seed=int(seed),
            batches=batches,
            batch_interval=batch_interval_h * 60,
            machine_overrides=machine_overrides or None,
            notes="Streamlit dashboard futtatás",
        )
    with st.spinner("KPI-k számítása..."):
        run_kpi_engine(new_run_id)
    st.session_state["selected_run_id"] = new_run_id
    st.sidebar.success(f"Kész -- run_id = {new_run_id}")
    st.rerun()


# ---------------------------------------------------------------------------
# FŐ TARTALOM -- run kiválasztó + KPI-k
# ---------------------------------------------------------------------------
st.title("Manufacturing Digitalization Dashboard")

runs_df = get_completed_runs()

if runs_df.empty:
    st.warning(
        "Nincs még COMPLETED státuszú szimulációs futás az adatbázisban. "
        "Indíts egyet az oldalsávon a 'Run new simulation' gombbal."
    )
    st.stop()

default_run_id = st.session_state.get("selected_run_id", runs_df.iloc[0]["run_id"])
run_id = st.selectbox(
    "Megjelenítendő futás",
    options=runs_df["run_id"].tolist(),
    index=runs_df["run_id"].tolist().index(default_run_id) if default_run_id in runs_df["run_id"].tolist() else 0,
    format_func=lambda rid: f"run_id={rid}",
)

meta = get_run_meta(run_id)
col1, col2, col3, col4 = st.columns(4)
col1.metric("Indítva", str(meta["started_at"])[:19])
col2.metric("Hossz (nap)", meta["sim_duration"] // DAY_LENGTH)
col3.metric("Seed", meta["random_seed"])
col4.metric("Megjegyzés", meta["notes"] or "--")

kpi_df = get_kpi_daily(run_id)

if kpi_df.empty:
    st.info("Erre a futásra még nincs kiszámolt KPI. Futtasd le a kpi_engine.py-t rá.")
    st.stop()

# --- US-101: OEE breakdown per machine -------------------------------------
st.header("📊 OEE breakdown per machine")

avg_kpi = kpi_df.groupby("machine_id")[["availability", "performance", "quality", "oee"]].mean().reset_index()

fig_breakdown = go.Figure()
for component, color in [("availability", "#4C78A8"), ("performance", "#F58518"), ("quality", "#54A24B")]:
    fig_breakdown.add_trace(go.Bar(
        x=avg_kpi["machine_id"], y=avg_kpi[component], name=component.capitalize(),
        marker_color=color,
    ))
fig_breakdown.add_trace(go.Scatter(
    x=avg_kpi["machine_id"], y=avg_kpi["oee"], name="OEE",
    mode="markers+lines", marker=dict(color="black", size=10, symbol="diamond"),
))
fig_breakdown.update_layout(barmode="group", yaxis_tickformat=".0%", yaxis_title="Arány",
                             legend_title="Komponens", height=420)
st.plotly_chart(fig_breakdown, width="stretch")
st.caption("A oszlopok az Availability / Performance / Quality napi átlagát mutatják gépenként; "
           "a fekete gyémánt jel az OEE-t (a három szorzata).")

with st.expander("Napi bontású KPI tábla"):
    st.dataframe(kpi_df, width="stretch")

# --- US-103: MTBF / MTTR ----------------------------------------------------
st.header("🔧 MTBF / MTTR gépenként")
mttr_mtbf = kpi_df.groupby("machine_id")[["mtbf", "mttr"]].mean().reset_index()
c1, c2 = st.columns(2)
with c1:
    st.plotly_chart(
        px.bar(mttr_mtbf, x="machine_id", y="mtbf", title="Átlagos MTBF (perc)"),
        width="stretch",
    )
with c2:
    st.plotly_chart(
        px.bar(mttr_mtbf, x="machine_id", y="mttr", title="Átlagos MTTR (perc)"),
        width="stretch",
    )

# --- US-203: Machine state visualization ------------------------------------
st.header("🛠️ Gépállapot az idő során (working / blocked / repair)")

status_df = get_machine_status_log(run_id)
state_rows = []
for machine_id in sorted(status_df["machine_id"].unique()):
    segments = _build_segments(status_df, machine_id, sim_end_time=meta["sim_duration"])
    totals = {"working": 0.0, "blocked": 0.0, "repair": 0.0}
    for start, end, status in segments:
        totals[status] = totals.get(status, 0.0) + (end - start)
    for status, duration in totals.items():
        state_rows.append({"machine_id": machine_id, "status": status, "minutes": duration})

state_df = pd.DataFrame(state_rows)
fig_state = px.bar(
    state_df, x="machine_id", y="minutes", color="status", barmode="stack",
    color_discrete_map={"working": "#54A24B", "blocked": "#F58518", "repair": "#E45756"},
    title="Idő eloszlása állapotonként, gépenként (teljes futás)",
)
st.plotly_chart(fig_state, width="stretch")
