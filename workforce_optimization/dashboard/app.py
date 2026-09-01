# -*- coding: utf-8 -*-
"""
app.py -- Workforce Optimization dashboard (Jira WO-7, plus the entry
points for WO-2..WO-6).

Layout
  sidebar : data source (sample / upload the five CSVs), competency
            weights, resilience target, sample-package download
  tab 1   : Shift allocation      (WO-4 + WO-6 Excel export)
  tab 2   : Shift reorganization  (WO-5, exports a shifts.csv proposal)
  tab 3   : Skill matrix & coverage  (FR-07 -- gaps highlighted)
  tab 4   : Recommendations       (FR-08 experts, FR-10 promotion, FR-11 training)

No database: the loaded scenario lives in st.session_state for the
session, and the last valid upload is mirrored to .cache/ so it comes
back as the default next start (see data_io/store.py).
"""

import os
import sys

import pandas as pd
import streamlit as st

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, BASE_DIR)

from config.wo_config import (  # noqa: E402
    DEFAULT_COMPETENCY_WEIGHTS,
    DEFAULT_MIN_QUALIFIED_PER_STATION,
    DEFAULT_NUM_SHIFTS,
)
from data_io import store  # noqa: E402
from data_io.loaders import load_from_frames  # noqa: E402
from data_io.sample_package import sample_frames, sample_package_zip_bytes  # noqa: E402
from data_io.validation import ValidationError  # noqa: E402
from optimization.shift_allocation import allocate_shift  # noqa: E402
from optimization.shift_reorg import reorganize_shifts  # noqa: E402
from analysis.coverage import coverage_by_shift, workforce_coverage, coverage_gaps  # noqa: E402
from analysis.recommendations import (  # noqa: E402
    experts_by_station,
    promotion_candidates,
    training_candidates,
)
from export.excel_export import build_workbook_bytes  # noqa: E402
import charts  # noqa: E402

st.set_page_config(page_title="Workforce Optimization", layout="wide")

UPLOAD_FILES = ["operators", "skill", "routine", "stations", "shifts"]


# ---------------------------------------------------------------------------
# DATA LOADING
# ---------------------------------------------------------------------------
def _initial_data():
    if store.has_last_valid():
        try:
            return load_from_frames(store.load_last_valid_frames()), "last upload"
        except ValidationError:
            pass
    return load_from_frames(sample_frames()), "sample data"


def _ensure_data():
    if "data" not in st.session_state:
        data, label = _initial_data()
        st.session_state.data = data
        st.session_state.data_label = label


def _weights():
    return {
        "skill": st.session_state.get("w_skill", DEFAULT_COMPETENCY_WEIGHTS["skill"]),
        "routine": st.session_state.get("w_routine", DEFAULT_COMPETENCY_WEIGHTS["routine"]),
    }


# ---------------------------------------------------------------------------
# SIDEBAR
# ---------------------------------------------------------------------------
def sidebar():
    st.sidebar.header("Data")

    st.sidebar.download_button(
        "Download sample input package (.zip)",
        data=sample_package_zip_bytes(),
        file_name="workforce_optimization_sample.zip",
        mime="application/zip",
        help="Five CSVs in the expected format -- use as a template or demo data (WO-3).",
    )

    mode = st.sidebar.radio("Source", ["Keep current", "Upload CSV files", "Reset to sample"],
                            label_visibility="collapsed")

    if mode == "Upload CSV files":
        uploads = {}
        for name in UPLOAD_FILES:
            uploads[name] = st.sidebar.file_uploader(f"{name}.csv", type="csv", key=f"up_{name}")
        if st.sidebar.button("Load uploaded data", type="primary"):
            _handle_upload(uploads)
    elif mode == "Reset to sample":
        if st.sidebar.button("Confirm reset to sample", type="primary"):
            store.clear_last_valid()
            st.session_state.data = load_from_frames(sample_frames())
            st.session_state.data_label = "sample data"
            st.rerun()

    st.sidebar.caption(f"Loaded: **{st.session_state.data_label}**")

    st.sidebar.header("Competency weights")
    st.sidebar.number_input("skill weight", min_value=0.0, max_value=10.0, step=0.5,
                            value=float(DEFAULT_COMPETENCY_WEIGHTS["skill"]), key="w_skill")
    st.sidebar.number_input("routine weight", min_value=0.0, max_value=10.0, step=0.5,
                            value=float(DEFAULT_COMPETENCY_WEIGHTS["routine"]), key="w_routine")
    st.sidebar.info(
        "competency(operator, station) = skill weight x skill + routine weight x routine\n\n"
        "Used to rank assignments. Eligibility (skill >= station level and routine > 0) "
        "is a separate hard rule and is not affected by these weights."
    )

    st.sidebar.header("Resilience target")
    st.sidebar.number_input("min. eligible operators per station per shift", min_value=1, max_value=10,
                            value=DEFAULT_MIN_QUALIFIED_PER_STATION, key="min_qualified")


def _handle_upload(uploads: dict):
    provided = {k: v for k, v in uploads.items() if v is not None}
    if len(provided) < len(UPLOAD_FILES):
        missing = [f"{n}.csv" for n in UPLOAD_FILES if n not in provided]
        st.sidebar.error("Missing file(s): " + ", ".join(missing))
        return

    # Read each upload once -- a Streamlit UploadedFile is a one-shot
    # stream, so parsing it twice raises EmptyDataError on the second try.
    try:
        frames = {}
        for name in UPLOAD_FILES:
            f = uploads[name]
            f.seek(0)
            frames[name] = pd.read_csv(f)
    except (pd.errors.EmptyDataError, pd.errors.ParserError) as exc:
        st.sidebar.error(f"Upload rejected -- could not parse a CSV: {exc}")
        return

    try:
        data = load_from_frames(frames)
    except ValidationError as exc:
        st.sidebar.error("Upload rejected:")
        for e in exc.errors:
            st.sidebar.write(f"- {e}")
        return

    store.save_last_valid(frames)
    st.session_state.data = data
    st.session_state.data_label = "last upload"
    st.sidebar.success("Loaded and saved as the new default.")
    st.rerun()


# ---------------------------------------------------------------------------
# TAB 1 -- SHIFT ALLOCATION (WO-4 / WO-6)
# ---------------------------------------------------------------------------
def tab_allocation(data):
    st.subheader("Shift allocation")
    st.caption("Assign the operators of one shift to workstations, maximising total competency (WO-4).")

    shift = st.selectbox("Shift", data.shift_list)
    run = st.button("Run optimization", type="primary")
    if run:
        st.session_state.alloc = allocate_shift(data, shift, _weights())

    res = st.session_state.get("alloc")
    if res is None or res.shift != shift:
        st.info("Pick a shift and run the optimization.")
        return

    c1, c2, c3 = st.columns(3)
    c1.metric("Solver status", res.status)
    c2.metric("Total competency", f"{res.objective:.0f}")
    c3.metric("Stations short", len(res.gaps))

    required = {s: data.required_operators(s) for s in data.station_list}
    assigned = (res.assignments["station"].value_counts().to_dict()
                if not res.assignments.empty else {})
    left, right = st.columns(2)
    left.plotly_chart(charts.station_staffing_bar(data.station_list, required, assigned),
                      width="stretch")
    right.plotly_chart(charts.assignment_competency_bar(res.assignments), width="stretch")

    if res.has_gaps:
        st.warning("Some stations could not be fully staffed -- left understaffed on purpose (FR-09).")
        st.dataframe(res.gaps, width="stretch", hide_index=True)
    else:
        st.success("Every station filled to its required headcount.")

    if res.unassigned_operators:
        st.caption("Not assigned this shift: " + ", ".join(res.unassigned_operators))

    if not res.assignments.empty:
        with st.expander("Assignment table"):
            st.dataframe(
                res.assignments, width="stretch", hide_index=True,
                column_config={"competency": st.column_config.ProgressColumn(
                    "competency", format="%.0f", min_value=0,
                    max_value=float(res.assignments["competency"].max()))},
            )

    all_results = {s: (res if s == shift else allocate_shift(data, s, _weights())) for s in data.shift_list}
    st.download_button(
        "Download Excel (Assignments + Gaps, all shifts)",
        data=build_workbook_bytes(all_results),
        file_name="workforce_allocation.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# ---------------------------------------------------------------------------
# TAB 2 -- SHIFT REORGANIZATION (WO-5)
# ---------------------------------------------------------------------------
def tab_reorg(data):
    st.subheader("Shift reorganization")
    st.caption("Split the whole workforce into N shifts so each shift can be run resiliently. "
               "Manual, separate from the per-shift allocation (WO-5).")

    n_shifts = st.number_input("Number of shifts", min_value=1, max_value=10, value=DEFAULT_NUM_SHIFTS)
    if st.button("Propose reorganization", type="primary"):
        st.session_state.reorg = reorganize_shifts(
            data, num_shifts=int(n_shifts), target=st.session_state.get("min_qualified")
        )

    res = st.session_state.get("reorg")
    if res is None:
        st.info("Set the number of shifts and run the proposal.")
        return

    c1, c2, c3 = st.columns(3)
    c1.metric("Solver status", res.status)
    c2.metric("Resilient station-shift pairs", f"{res.covered_pairs}/{res.total_pairs}")
    c3.metric("Headcount reference / shift", res.headcount_reference)

    st.plotly_chart(
        charts.coverage_heatmap(res.coverage, res.target,
                                "Eligible operators per station, per proposed shift"),
        width="stretch",
    )
    st.plotly_chart(charts.shift_headcount_bar(res.headcount, res.headcount_reference),
                    width="stretch")

    if res.has_uncovered:
        st.warning(f"{len(res.uncovered_pairs)} station-shift pair(s) below the resilience target "
                   f"of {res.target} -- not enough eligible operators in the workforce to do better.")
        st.dataframe(res.uncovered_pairs, width="stretch", hide_index=True)
    else:
        st.success("Every station reaches the resilience target in every proposed shift.")

    with st.expander("Proposed shift assignment (table)"):
        st.dataframe(res.shifts_frame, width="stretch", hide_index=True)

    st.download_button(
        "Download proposed shifts.csv",
        data=res.shifts_frame.to_csv(index=False),
        file_name="shifts.csv",
        mime="text/csv",
        help="Upload this back as shifts.csv to use the proposed split.",
    )


# ---------------------------------------------------------------------------
# TAB 3 -- SKILL MATRIX & COVERAGE (FR-07)
# ---------------------------------------------------------------------------
def tab_matrix(data):
    st.subheader("Skill matrix & coverage")

    levels = data.stations["required_level"]
    target = st.session_state.get("min_qualified", DEFAULT_MIN_QUALIFIED_PER_STATION)

    st.plotly_chart(charts.skill_matrix_heatmap(data.skill, data.routine, levels), width="stretch")
    st.plotly_chart(
        charts.coverage_heatmap(coverage_by_shift(data), target,
                                f"Eligible operators per station, per shift (target {target})"),
        width="stretch",
    )
    st.plotly_chart(charts.workforce_coverage_bar(workforce_coverage(data), target), width="stretch")

    gaps = coverage_gaps(data, target)
    if len(gaps):
        st.warning("Resilience gaps (single-point-of-failure risk):")
        st.dataframe(gaps, width="stretch", hide_index=True)
    else:
        st.success("Every station reaches the resilience target in every shift.")

    with st.expander("Routine matrix & station requirements"):
        st.dataframe(data.routine, width="stretch")
        st.dataframe(data.stations, width="stretch")


# ---------------------------------------------------------------------------
# TAB 4 -- RECOMMENDATIONS (FR-08 / FR-10 / FR-11)
# ---------------------------------------------------------------------------
def tab_recommendations(data):
    st.subheader("Recommendations")
    st.caption("Dashboard-only -- not part of the Excel export.")
    weights = _weights()
    target = st.session_state.get("min_qualified", DEFAULT_MIN_QUALIFIED_PER_STATION)

    experts = experts_by_station(data, weights, target)
    st.markdown("### Experts per station (FR-08)")
    st.plotly_chart(charts.experts_figure(experts), width="stretch")
    spof = [s for s, df in experts.items() if df.attrs["single_point_of_failure"]]
    if spof:
        st.warning("Single point of failure -- fewer than the target number of experts: "
                   + ", ".join(f"station {s}" for s in spof))

    st.markdown("### Promotion candidates (FR-10)")
    st.caption("Highest cumulated skill across all stations; ties broken by cumulated routine.")
    promo = promotion_candidates(data)
    st.plotly_chart(charts.promotion_bar(promo), width="stretch")
    with st.expander("Promotion table"):
        st.dataframe(promo, width="stretch", hide_index=True)

    st.markdown("### Training candidates (FR-11)")
    st.caption("Lowest cumulated skill, or skills already broadly covered. Recommended area: "
               "lowest-coverage station in the operator's own shift first, then workforce-wide.")
    st.dataframe(
        training_candidates(data), width="stretch", hide_index=True,
        column_config={
            "redundancy_ratio": st.column_config.ProgressColumn(
                "redundancy", format="%.2f", min_value=0.0, max_value=1.0),
            "recommended_training": st.column_config.TextColumn("train for"),
        },
    )


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------
def main():
    _ensure_data()
    st.title("Workforce Optimization")
    st.caption("Skill-based shift allocation decision support. Synthetic data only.")

    sidebar()
    data = st.session_state.data

    t1, t2, t3, t4 = st.tabs(
        ["Shift allocation", "Shift reorganization", "Skill matrix & coverage", "Recommendations"]
    )
    with t1:
        tab_allocation(data)
    with t2:
        tab_reorg(data)
    with t3:
        tab_matrix(data)
    with t4:
        tab_recommendations(data)


main()
