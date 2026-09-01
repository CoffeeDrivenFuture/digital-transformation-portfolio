# -*- coding: utf-8 -*-
"""
test_wo.py
----------
Sanity tests for Workforce Optimization. Runs two ways:

    python tests/test_wo.py       # plain asserts, prints a summary
    pytest tests/test_wo.py

Everything runs against the bundled sample dataset.
"""

import io
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # project root

from data_io.sample_package import sample_frames  # noqa: E402
from data_io.loaders import load_from_frames  # noqa: E402
from data_io.validation import validate_frames, ValidationError  # noqa: E402
from optimization.competency import competency_matrix, eligibility_matrix  # noqa: E402
from optimization.shift_allocation import allocate_shift, allocate_all_shifts  # noqa: E402
from optimization.shift_reorg import reorganize_shifts  # noqa: E402
from analysis.coverage import coverage_by_shift, coverage_gaps  # noqa: E402
from analysis.recommendations import promotion_candidates, training_candidates, experts_by_station  # noqa: E402
from export.excel_export import build_workbook_bytes  # noqa: E402


def _data():
    return load_from_frames(sample_frames())


def test_sample_loads():
    d = _data()
    assert d.station_list == ["A", "B", "C", "D"]
    assert len(d.operator_list) == 10
    assert set(d.shift_list) == {"Day", "Night"}
    assert d.required_operators("B") == 2
    assert d.required_level("C") == 3


def test_validation_accepts_sample():
    assert validate_frames(sample_frames()) == []


def test_validation_missing_column():
    frames = sample_frames()
    frames["stations"] = frames["stations"].drop(columns=["required_level"])
    errors = validate_frames(frames)
    assert any("required_level" in e for e in errors)


def test_validation_out_of_range():
    frames = sample_frames()
    frames["skill"] = frames["skill"].copy()
    frames["skill"].loc[0, "A"] = 9
    errors = validate_frames(frames)
    assert any("outside 0-5" in e for e in errors)


def test_validation_unknown_operator_in_shifts():
    frames = sample_frames()
    frames["shifts"] = pd.concat(
        [frames["shifts"], pd.DataFrame([{"operator_id": "OP99", "shift": "Day"}])],
        ignore_index=True,
    )
    errors = validate_frames(frames)
    assert any("OP99" in e for e in errors)


def test_validation_duplicate_shift_assignment():
    frames = sample_frames()
    frames["shifts"] = pd.concat(
        [frames["shifts"], pd.DataFrame([{"operator_id": "OP01", "shift": "Night"}])],
        ignore_index=True,
    )
    errors = validate_frames(frames)
    assert any("more than one shift" in e for e in errors)


def test_eligibility_requires_routine():
    d = _data()
    elig = eligibility_matrix(d)
    # OP06 has skill 2 at D (>= required_level 2) but routine 0 -> not eligible.
    assert d.skill.loc["OP06", "D"] >= d.required_level("D")
    assert d.routine.loc["OP06", "D"] == 0
    assert not bool(elig.loc["OP06", "D"])


def test_allocation_day_fills_every_station():
    d = _data()
    res = allocate_shift(d, "Day")
    assert res.status == "Optimal"
    assert res.gaps.empty
    counts = res.assignments["station"].value_counts().to_dict()
    for station in d.station_list:
        assert counts.get(station, 0) == d.required_operators(station)


def test_allocation_respects_constraints():
    d = _data()
    for res in allocate_all_shifts(d).values():
        # at most one station per operator
        assert res.assignments["operator_id"].is_unique
        # never over required_operators
        counts = res.assignments["station"].value_counts().to_dict()
        for station, n in counts.items():
            assert n <= d.required_operators(station)


def test_allocation_night_reports_gaps():
    d = _data()
    res = allocate_shift(d, "Night")
    gap_stations = set(res.gaps["station"])
    assert "D" in gap_stations  # nobody eligible for D at night


def test_weights_change_objective():
    d = _data()
    base = allocate_shift(d, "Day", {"skill": 2.0, "routine": 1.0}).objective
    routine_heavy = allocate_shift(d, "Day", {"skill": 1.0, "routine": 3.0}).objective
    assert base != routine_heavy


def test_reorg_balances_and_assigns_once():
    d = _data()
    res = reorganize_shifts(d, num_shifts=3)
    assert res.status == "Optimal"
    assert res.shifts_frame["operator_id"].is_unique
    assert (res.shifts_frame["shift"] != "").all()
    counts = res.headcount.tolist()
    assert max(counts) - min(counts) <= 1


def test_promotion_candidates():
    d = _data()
    df = promotion_candidates(d)
    assert len(df) == 5
    assert list(df["rank"]) == [1, 2, 3, 4, 5]
    skills = df["cumulated_skill"].tolist()
    assert skills == sorted(skills, reverse=True)
    assert df.iloc[0]["operator_id"] == "OP09"  # highest cumulated skill in the sample


def test_training_candidates_have_a_target():
    d = _data()
    df = training_candidates(d)
    assert not df.empty
    assert (df["recommended_training"] != "").all()
    assert df["recommended_training"].isin(d.station_list).all()


def test_experts_flag_single_point_of_failure():
    d = _data()
    experts = experts_by_station(d)
    # Station D has only 3 eligible operators workforce-wide; still >= 2, not SPOF.
    assert experts["D"].attrs["single_point_of_failure"] is False
    assert len(experts["D"]) == 3


def test_upload_flow_reads_one_shot_streams():
    # Mimics the dashboard: Streamlit UploadedFile is a one-shot stream, so
    # each file must be seek(0)'d and parsed exactly once.
    uploads = {n: io.BytesIO(df.to_csv(index=False).encode())
               for n, df in sample_frames().items()}
    frames = {}
    for name in ["operators", "skill", "routine", "stations", "shifts"]:
        uploads[name].seek(0)
        frames[name] = pd.read_csv(uploads[name])
    data = load_from_frames(frames)
    assert len(data.operator_list) == 10


def test_excel_export_has_two_sheets():
    d = _data()
    wb = build_workbook_bytes(allocate_all_shifts(d))
    assert len(wb) > 0
    sheets = pd.ExcelFile(io.BytesIO(wb)).sheet_names
    assert sheets == ["Assignments", "Gaps"]


def test_coverage_gaps_flag_night():
    d = _data()
    cov = coverage_by_shift(d)
    assert int(cov.loc["Night", "D"]) == 0
    gaps = coverage_gaps(d, min_qualified=2)
    assert {"shift", "station"}.issubset(gaps.columns)
    assert ((gaps["shift"] == "Night") & (gaps["station"] == "D")).any()


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
        passed += 1
    print(f"\n{passed}/{len(tests)} passed")


if __name__ == "__main__":
    _run_all()
