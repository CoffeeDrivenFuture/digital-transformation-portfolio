# -*- coding: utf-8 -*-
"""
app.py -- Case A Streamlit dashboard (US-402)

Covers the US-402 acceptance criteria: the dashboard reads from the SQLite
file via SQL queries, the "Run new simulation" button kicks off a fresh run
and refreshes the view, and the runtime parameters (order pattern, batch
size, product mix, per-machine cycle_time, MTBF/MTTR, quality rate) are
adjustable in the sidebar instead of hardcoded.

It also shows the results of the already-built KPI engine (US-101/US-103)
and the machine_status_log (US-203 -- machine state timeline), since the
dashboard would otherwise be pretty empty.

Deliberately not implemented here, left in the backlog: US-102 (SQDCP
category/tier filter -- the current schema has no SQDCP categorization for
the KPIs, that's a separate story), US-204 (Yamazumi chart -- belongs in
its own component), and US-403 (Power BI -- a different tool entirely).
"""

import os
import sys

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# --- accessing config/simulation/kpi modules, independent of folder structure --
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
from kpi_engine import run_kpi_engine, _build_segments               # noqa: E402, PLC0415  # type: ignore[import-not-found]

DAY_LENGTH = 24 * 60

st.set_page_config(page_title="Manufacturing Digitalization", layout="wide")


# ---------------------------------------------------------------------------
# DATA-LOADING HELPER FUNCTIONS (each one an SQL query against the SQLite file)
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
# SIDEBAR -- runtime parameters + "Run new simulation"
# ---------------------------------------------------------------------------
st.sidebar.header("Simulation parameters")

sim_days = st.sidebar.slider("Simulation length (days)", 1, 10, DEFAULT_SIM_TIME // DAY_LENGTH)
seed = st.sidebar.number_input("Random seed", value=DEFAULT_RANDOM_SEED, step=1)

st.sidebar.subheader("Order pattern")
n_batches = st.sidebar.slider("Number of orders (batches)", 3, 30, 10)
batch_interval_h = st.sidebar.slider("Time between orders (hours)", 2, 24, DEFAULT_BATCH_INTERVAL // 60)
total_per_batch = st.sidebar.slider("Batch size (pcs/order)", 10, 100, DEFAULT_TOTAL_PIECES_PER_BATCH)
a_share = st.sidebar.slider("Share of product 'A' in the mix", 0.0, 1.0, 0.5, step=0.05)

st.sidebar.subheader("Per-machine overrides (optional)")
st.sidebar.caption("If you don't expand a machine's row, it gets its default (prod_config.py) value.")

machine_overrides = {}
for machine_name, base_params in DEFAULT_MACHINE_PARAMS.items():
    with st.sidebar.expander(machine_name):
        override_on = st.checkbox("Enable override", key=f"ov_{machine_name}")
        cycle_time = st.slider(
            "Cycle time (min)", 1.0, 15.0, float(base_params["cycle_time"]),
            step=0.1, key=f"ct_{machine_name}", disabled=not override_on,
        )
        quality = st.slider(
            "Quality rate", 0.5, 1.0, float(base_params["quality"]),
            step=0.01, key=f"q_{machine_name}", disabled=not override_on,
        )
        mtbf = st.slider(
            "MTBF target (min)", 100, 2000, int(base_params["mtbf"]),
            step=50, key=f"mtbf_{machine_name}", disabled=not override_on,
        )
        mttr = st.slider(
            "MTTR target (min)", 10, 300, int(base_params["mttr"]),
            step=10, key=f"mttr_{machine_name}", disabled=not override_on,
        )
        if override_on:
            machine_overrides[machine_name] = {
                "cycle_time": cycle_time, "quality": quality,
                "mtbf": mtbf, "mttr": mttr,
            }

run_clicked = st.sidebar.button("Run new simulation", type="primary", width="stretch")

if run_clicked:
    batches = generate_batches(n_batches, total_per_batch, a_share=a_share, seed=int(seed))
    with st.spinner("Simulation running..."):
        new_run_id = run_simulation(
            sim_time=sim_days * DAY_LENGTH,
            seed=int(seed),
            batches=batches,
            batch_interval=batch_interval_h * 60,
            machine_overrides=machine_overrides or None,
            notes="Streamlit dashboard run",
        )
    with st.spinner("Computing KPIs..."):
        run_kpi_engine(new_run_id)
    st.session_state["selected_run_id"] = new_run_id
    st.sidebar.success(f"Done -- run_id = {new_run_id}")
    st.rerun()


# ---------------------------------------------------------------------------
# MAIN CONTENT -- run selector + KPIs
# ---------------------------------------------------------------------------
st.title("Manufacturing Digitalization Dashboard")

runs_df = get_completed_runs()

if runs_df.empty:
    st.warning(
        "There is no COMPLETED simulation run in the database yet. "
        "Start one in the sidebar with the 'Run new simulation' button."
    )
    st.stop()

default_run_id = st.session_state.get("selected_run_id", runs_df.iloc[0]["run_id"])
run_id = st.selectbox(
    "Run to display",
    options=runs_df["run_id"].tolist(),
    index=runs_df["run_id"].tolist().index(default_run_id) if default_run_id in runs_df["run_id"].tolist() else 0,
    format_func=lambda rid: f"run_id={rid}",
)

meta = get_run_meta(run_id)
col1, col2, col3, col4 = st.columns(4)
col1.metric("Started", str(meta["started_at"])[:19])
col2.metric("Length (days)", meta["sim_duration"] // DAY_LENGTH)
col3.metric("Seed", meta["random_seed"])
col4.metric("Notes", meta["notes"] or "--")

kpi_df = get_kpi_daily(run_id)

if kpi_df.empty:
    st.info("No KPI has been computed for this run yet. Run kpi_engine.py against it.")
    st.stop()

# --- US-101: OEE breakdown per machine -------------------------------------
st.header("OEE breakdown per machine")

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
fig_breakdown.update_layout(barmode="group", yaxis_tickformat=".0%", yaxis_title="Ratio",
                             legend_title="Component", height=420)
st.plotly_chart(fig_breakdown, width="stretch")
st.caption("The bars show the daily average of Availability / Performance / Quality per machine; "
           "the black diamond marker shows OEE (the product of the three).")

with st.expander("Daily KPI table"):
    st.dataframe(kpi_df, width="stretch")

# --- US-103: MTBF / MTTR ----------------------------------------------------
st.header("MTBF / MTTR per machine")
mttr_mtbf = kpi_df.groupby("machine_id")[["mtbf", "mttr"]].mean().reset_index()
c1, c2 = st.columns(2)
with c1:
    st.plotly_chart(
        px.bar(mttr_mtbf, x="machine_id", y="mtbf", title="Average MTBF (min)"),
        width="stretch",
    )
with c2:
    st.plotly_chart(
        px.bar(mttr_mtbf, x="machine_id", y="mttr", title="Average MTTR (min)"),
        width="stretch",
    )

# --- US-203: Machine state visualization ------------------------------------
st.header("Machine state over time (working / blocked / repair)")

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
    title="Time distribution by state, per machine (full run)",
)
st.plotly_chart(fig_state, width="stretch")
