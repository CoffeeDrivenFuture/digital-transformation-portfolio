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
    TARGET_OEE,
    generate_batches,
)
from db_layer import get_connection, init_db                        # noqa: E402
from production_sim_db import run_simulation, DB_PATH               # noqa: E402
from kpi_engine import run_kpi_engine, _build_segments, _split_segments_by_day  # noqa: E402, PLC0415  # type: ignore[import-not-found]

DAY_LENGTH = 24 * 60

# Traffic-light palette for machine status, used everywhere a machine's
# working/blocked/repair state is color-coded.
STATUS_COLORS = {
    "working": "#4CAF50",
    "blocked": "#FFC107",
    "repair": "#EF5350",
}


def apply_dark_theme(fig):
    """Blend a Plotly figure into Streamlit's dark theme instead of it
    rendering its own light background. Transparent backgrounds are used
    (rather than a hardcoded dark hex) so the chart always matches
    Streamlit's actual background, even if the theme changes later."""
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font_color="#FAFAFA",
        legend=dict(bgcolor="rgba(0,0,0,0)"),
        xaxis=dict(gridcolor="rgba(255,255,255,0.1)", zerolinecolor="rgba(255,255,255,0.2)"),
        yaxis=dict(gridcolor="rgba(255,255,255,0.1)", zerolinecolor="rgba(255,255,255,0.2)"),
    )
    return fig


st.set_page_config(page_title="Manufacturing Digitalization", layout="wide")

# On a fresh clone the .db file has no schema yet if the simulation has
# never been run, which used to crash the very first page load with
# "no such table: simulation_runs" instead of showing the "no runs yet"
# message below. init_db() is idempotent (CREATE TABLE IF NOT EXISTS).
_init_conn = get_connection(DB_PATH)
init_db(_init_conn)
_init_conn.close()


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


def get_material_stock_log(run_id: int) -> pd.DataFrame:
    conn = get_connection(DB_PATH)
    try:
        return pd.read_sql(
            "SELECT sim_time, material_id, stock_level FROM material_stock_log WHERE run_id = ?",
            conn, params=(run_id,),
        )
    finally:
        conn.close()


def get_materials() -> pd.DataFrame:
    conn = get_connection(DB_PATH)
    try:
        return pd.read_sql("SELECT material_id, min_level FROM materials", conn)
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

# Recommended demo scenario (MFG-18): the DEFAULT_* order pattern under-loads
# the machines to roughly 13-28% of raw capacity, which gives single-digit
# OEE that isn't representative of a real shop floor. This preset lands in
# a more believable range (avg OEE in the high-40s to mid-50s%) while still
# keeping the genuine Machine3 bottleneck / Machine4 material-supply story
# visible.
RECOMMENDED_PRESET = {
    "sim_days": 5, "seed": 7, "n_batches": 50,
    "batch_interval_h": 2.5, "total_per_batch": 40, "a_share": 0.5,
}

# Seed session_state with the ordinary defaults only on first load. After
# that, the sliders below read/write session_state exclusively via `key=`;
# passing a `value=` on top of a key whose session_state was already set
# from outside the widget (as the preset button does) triggers a Streamlit
# warning, so defaults are set here once instead of as slider arguments.
_widget_defaults = {
    "sim_days": DEFAULT_SIM_TIME // DAY_LENGTH, "seed": DEFAULT_RANDOM_SEED,
    "n_batches": 10, "batch_interval_h": float(DEFAULT_BATCH_INTERVAL // 60),
    "total_per_batch": DEFAULT_TOTAL_PIECES_PER_BATCH, "a_share": 0.5,
}
for _key, _value in _widget_defaults.items():
    if _key not in st.session_state:
        st.session_state[_key] = _value

if st.sidebar.button("Load recommended demo scenario", width="stretch"):
    for preset_key, preset_value in RECOMMENDED_PRESET.items():
        st.session_state[preset_key] = preset_value
    st.rerun()

sim_days = st.sidebar.slider("Simulation length (days)", 1, 10, key="sim_days")
seed = st.sidebar.number_input("Random seed", step=1, key="seed")

st.sidebar.subheader("Order pattern")
n_batches = st.sidebar.slider("Number of orders (batches)", 3, 60, key="n_batches")
batch_interval_h = st.sidebar.slider("Time between orders (hours)", 1.0, 24.0, step=0.5, key="batch_interval_h")
total_per_batch = st.sidebar.slider("Batch size (pcs/order)", 10, 100, key="total_per_batch")
a_share = st.sidebar.slider("Share of product 'A' in the mix", 0.0, 1.0, step=0.05, key="a_share")

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
col1, col2, col3 = st.columns(3)
col1.metric("Started", str(meta["started_at"])[:19])
col2.metric("Length (days)", meta["sim_duration"] // DAY_LENGTH)
col3.metric("Seed", meta["random_seed"])
if meta["notes"]:
    st.caption(f"Notes: {meta['notes']}")

kpi_df = get_kpi_daily(run_id)

if kpi_df.empty:
    st.info("No KPI has been computed for this run yet. Run kpi_engine.py against it.")
    st.stop()

# --- How this simulation works (static flow diagram) ------------------------
st.header("How this simulation works")

_flow_diagram_path = os.path.join(PROJECT_ROOT, "assets", "production_flow_diagram.jpg")
if os.path.exists(_flow_diagram_path):
    st.image(
        _flow_diagram_path,
        caption="Production order routing (left) and inventory replenishment logic (right)",
        width="stretch",
    )
else:
    st.info("Production flow diagram not found -- expected at assets/production_flow_diagram.jpg")

# --- US-101: OEE breakdown per machine -------------------------------------
st.header("OEE breakdown per machine")

avg_kpi = kpi_df.groupby("machine_id")[["availability", "performance", "quality", "oee"]].mean().reset_index()

st.subheader("OEE per machine")
avg_kpi_sorted = avg_kpi.sort_values("oee")  # ascending -> highest OEE renders at the top of the h-bar chart
fig_oee = px.bar(
    avg_kpi_sorted, x="oee", y="machine_id", orientation="h",
    color="oee", color_continuous_scale="RdYlGn", range_color=[0, 1],
    text=avg_kpi_sorted["oee"].apply(lambda v: f"{v:.0%}"),
    labels={"oee": "OEE", "machine_id": "Machine"},
)
fig_oee.update_traces(textposition="outside")
_oee_axis_max = max(1.0, float(avg_kpi_sorted["oee"].max())) * 1.15
fig_oee.update_layout(
    xaxis_tickformat=".0%", xaxis_title="OEE", yaxis_title="Machine",
    xaxis_range=[0, _oee_axis_max], height=380,
)
fig_oee.add_vline(x=TARGET_OEE, line_dash="solid", line_color="#2196F3", line_width=2,
                   annotation_text=f"<b>Target: {TARGET_OEE:.0%}</b>", annotation_position="bottom")
apply_dark_theme(fig_oee)
st.plotly_chart(fig_oee, width="stretch")

with st.expander("How these numbers are calculated", expanded=False):
    st.markdown("""
- **Availability** = working time / (working + blocked + repair time), per machine per day
- **Performance** = (ideal cycle time x units produced) / working time -- can exceed 100% if a machine processes faster than its nominal cycle time within its working window
- **Quality** = good units / total units produced
- **OEE** = Availability x Performance x Quality
- **MTBF** = average time between the start of consecutive repair events, per machine
- **MTTR** = average duration of a repair event, per machine

All values are computed per simulated day from the raw event log
(`production_events`, `machine_status_log`) -- nothing is hardcoded.
""")

st.subheader("OEE component breakdown per machine")
fig_breakdown = go.Figure()
for component, color in [("availability", "#4C78A8"), ("performance", "#F58518"), ("quality", "#54A24B")]:
    fig_breakdown.add_trace(go.Bar(
        x=avg_kpi["machine_id"], y=avg_kpi[component], name=component.capitalize(),
        marker_color=color,
    ))
fig_breakdown.update_layout(
    barmode="group", yaxis_tickformat=".0%", xaxis_title="Machine", yaxis_title="Ratio",
    legend_title="Component", height=420,
)
apply_dark_theme(fig_breakdown)
st.plotly_chart(fig_breakdown, width="stretch")
st.caption("The bars show the daily average of Availability / Performance / Quality per machine "
           "-- see the OEE per machine chart above for the combined score.")

with st.expander("Daily KPI trends", expanded=False):
    # Explicit color map, built once and reused across all 4 tabs, so a
    # given machine keeps the same color in every tab -- a fresh px.line
    # call per tab would otherwise assign colors independently and could
    # give the same machine different colors from one tab to the next.
    _trend_machines = sorted(kpi_df["machine_id"].unique())
    _trend_colors = px.colors.qualitative.Plotly
    machine_color_map = {
        machine_id: _trend_colors[i % len(_trend_colors)]
        for i, machine_id in enumerate(_trend_machines)
    }

    tabs = st.tabs(["OEE", "Availability", "Performance", "Quality"])
    metric_cols = ["oee", "availability", "performance", "quality"]
    for tab, metric_col in zip(tabs, metric_cols):
        with tab:
            fig_trend = px.line(
                kpi_df, x="sim_day", y=metric_col, color="machine_id",
                markers=True, color_discrete_map=machine_color_map,
                labels={"sim_day": "Day", metric_col: metric_col.capitalize(), "machine_id": "Machine"},
            )
            fig_trend.update_layout(yaxis_tickformat=".0%")
            apply_dark_theme(fig_trend)
            st.plotly_chart(fig_trend, width="stretch")

with st.expander("Daily KPI table"):
    # ProgressColumn's printf-style format ("%.0f%%") is applied to the raw
    # cell value with no automatic x100 scaling -- passing the 0-1 fraction
    # directly rounds e.g. 0.75 to "1%" and 0.3 to "0%". Scale a display copy
    # to 0-100 first so the percent formatting actually shows real numbers.
    kpi_display = kpi_df.copy()
    ratio_cols = ["availability", "performance", "quality", "oee"]
    kpi_display[ratio_cols] = kpi_display[ratio_cols] * 100

    st.dataframe(
        kpi_display,
        width="stretch",
        column_config={
            "availability": st.column_config.ProgressColumn(
                "Availability", format="%.0f%%", min_value=0, max_value=100
            ),
            "performance": st.column_config.ProgressColumn(
                "Performance", format="%.0f%%", min_value=0,
                max_value=max(100.0, kpi_display["performance"].max()),
            ),
            "quality": st.column_config.ProgressColumn(
                "Quality", format="%.0f%%", min_value=0, max_value=100
            ),
            "oee": st.column_config.ProgressColumn(
                "OEE", format="%.0f%%", min_value=0, max_value=100
            ),
            "mtbf": st.column_config.NumberColumn("MTBF", format="%.0f min"),
            "mttr": st.column_config.NumberColumn("MTTR", format="%.0f min"),
            "machine_id": st.column_config.TextColumn("Machine"),
            "sim_day": st.column_config.NumberColumn("Day"),
            "run_id": None,  # hide, redundant within a single-run table
        },
    )

# --- US-103: MTBF / MTTR ----------------------------------------------------
st.header("MTBF / MTTR per machine")
mttr_mtbf = kpi_df.groupby("machine_id")[["mtbf", "mttr"]].mean().reset_index()
c1, c2 = st.columns(2)
with c1:
    fig_mtbf = px.bar(
        mttr_mtbf, x="machine_id", y="mtbf", title="Average MTBF (min)",
        labels={"machine_id": "Machine", "mtbf": "MTBF (min)"},
    )
    apply_dark_theme(fig_mtbf)
    st.plotly_chart(fig_mtbf, width="stretch")
with c2:
    fig_mttr = px.bar(
        mttr_mtbf, x="machine_id", y="mttr", title="Average MTTR (min)",
        labels={"machine_id": "Machine", "mttr": "MTTR (min)"},
    )
    apply_dark_theme(fig_mttr)
    st.plotly_chart(fig_mttr, width="stretch")

# --- US-203: Machine state visualization ------------------------------------
st.header("Machine state over time (working / blocked / repair)")

status_df = get_machine_status_log(run_id)

view_mode = st.radio(
    "View", ["Aggregated (full run)", "Daily breakdown"],
    horizontal=True, key="machine_state_view_mode",
)

if view_mode == "Aggregated (full run)":
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
        color_discrete_map=STATUS_COLORS,
        labels={"machine_id": "Machine", "minutes": "Minutes", "status": "Status"},
        title="Time distribution by state, per machine (full run)",
    )
    apply_dark_theme(fig_state)
    st.plotly_chart(fig_state, width="stretch")
else:
    n_days = meta["sim_duration"] // DAY_LENGTH
    selected_day = st.slider("Day", 0, max(0, n_days - 1), 0, key="machine_state_day")
    daily_rows = []
    for machine_id in sorted(status_df["machine_id"].unique()):
        segments = _build_segments(status_df, machine_id, sim_end_time=meta["sim_duration"])
        day_status_duration = _split_segments_by_day(segments)
        durations = day_status_duration.get(selected_day, {})
        for status in ["working", "blocked", "repair"]:
            daily_rows.append({"machine_id": machine_id, "status": status, "minutes": durations.get(status, 0.0)})

    daily_state_df = pd.DataFrame(daily_rows)
    fig_daily_state = px.bar(
        daily_state_df, x="machine_id", y="minutes", color="status", barmode="stack",
        color_discrete_map=STATUS_COLORS,
        title=f"Machine state on day {selected_day}",
        labels={"machine_id": "Machine", "minutes": "Minutes", "status": "Status"},
    )
    apply_dark_theme(fig_daily_state)
    st.plotly_chart(fig_daily_state, width="stretch")

# --- Material stock level over time ------------------------------------------
st.header("Material stock level over time")

stock_df = get_material_stock_log(run_id)
materials_df = get_materials()

if stock_df.empty:
    st.info("No material stock data for this run.")
else:
    # Deliberately not downsampled or smoothed: the raw fluctuation is the
    # point -- it's what makes a material running consistently close to its
    # reorder threshold (e.g. material2) visible at a glance. A future
    # feature will compute recommended minimum stock levels from this same
    # raw signal, so smoothing it away here would work against that later.
    stock_df = stock_df.sort_values(["material_id", "sim_time"])
    stock_df["hours"] = stock_df["sim_time"] / 60

    min_level_by_material = dict(zip(materials_df["material_id"], materials_df["min_level"]))

    for material_id in sorted(stock_df["material_id"].unique()):
        mat_data = stock_df[stock_df["material_id"] == material_id]
        fig_mat = go.Figure()
        fig_mat.add_trace(go.Scatter(
            x=mat_data["hours"], y=mat_data["stock_level"],
            mode="lines", line_shape="hv", fill="tozeroy", name=material_id,
        ))
        if material_id in min_level_by_material:
            fig_mat.add_hline(
                y=min_level_by_material[material_id], line_dash="dash", line_color="#FFC107",
                annotation_text=f"{material_id} reorder threshold",
                annotation_position="top right",
            )
        fig_mat.update_layout(
            title=f"{material_id} stock level over time",
            xaxis_title="Time (hours)", yaxis_title="Stock level",
            showlegend=False, height=280,
        )
        apply_dark_theme(fig_mat)
        st.plotly_chart(fig_mat, width="stretch")
