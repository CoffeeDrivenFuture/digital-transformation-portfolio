# -*- coding: utf-8 -*-
"""
validation.py
-------------
Format checks for the five input CSVs, per Jira WO-2 and the Confluence
"Error Scenarios" table.

The rule from the spec is all-or-nothing: if any file is malformed, the
whole upload is rejected and the UI tells the user exactly which file and
what is wrong -- we never partially load. So every check appends a
human-readable string to one list, and `validate_frames()` returns that
list; an empty list means the upload is good.

Checked here:
  - each file has exactly its expected columns (missing or extra -> error)
  - skill.csv / routine.csv carry one column per station from stations.csv
  - skill / routine values are whole numbers within the 0-5 scale
  - required_level is on the 0-5 scale, required_operators is a
    non-negative whole number
  - operator ids are unique and consistent across operators / skill /
    routine / shifts
  - every operator is assigned to exactly one shift, and no shift row
    references an unknown operator

NOT checked here (it is a separate, later concern): whether the data is
*solvable* -- that a station has enough eligible operators is handled by
the optimization layer, which leaves the station short rather than
failing (FR-09).
"""

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # project root

from config.wo_config import CSV_SCHEMA, SKILL_SCALE_MIN, SKILL_SCALE_MAX  # noqa: E402


class ValidationError(Exception):
    """Raised when an upload fails validation. `errors` is the message list."""

    def __init__(self, errors: list):
        self.errors = errors
        super().__init__("; ".join(errors))


def _is_whole_number_series(s: pd.Series) -> pd.Series:
    """Boolean mask: True where the value is a finite whole number."""
    numeric = pd.to_numeric(s, errors="coerce")
    return numeric.notna() & (numeric == numeric.round())


def _check_exact_columns(df: pd.DataFrame, expected: list, filename: str, errors: list) -> bool:
    actual = list(df.columns)
    missing = [c for c in expected if c not in actual]
    extra = [c for c in actual if c not in expected]
    ok = True
    if missing:
        errors.append(f"{filename}: missing column(s): {', '.join(missing)}")
        ok = False
    if extra:
        errors.append(f"{filename}: unexpected column(s): {', '.join(extra)}")
        ok = False
    return ok


def _validate_operators(df: pd.DataFrame, errors: list) -> list:
    fname = "operators.csv"
    if not _check_exact_columns(df, CSV_SCHEMA["operators"]["columns"], fname, errors):
        return []
    ids = df["operator_id"].astype(str).str.strip()
    if (ids == "").any():
        errors.append(f"{fname}: blank operator_id value(s)")
    dupes = ids[ids.duplicated()].unique().tolist()
    if dupes:
        errors.append(f"{fname}: duplicate operator_id(s): {', '.join(dupes)}")
    return ids.tolist()


def _validate_stations(df: pd.DataFrame, errors: list) -> list:
    fname = "stations.csv"
    if not _check_exact_columns(df, CSV_SCHEMA["stations"]["columns"], fname, errors):
        return []

    names = df["station"].astype(str).str.strip()
    if (names == "").any():
        errors.append(f"{fname}: blank station value(s)")
    dupes = names[names.duplicated()].unique().tolist()
    if dupes:
        errors.append(f"{fname}: duplicate station(s): {', '.join(dupes)}")

    lvl_ok = _is_whole_number_series(df["required_level"])
    if not lvl_ok.all():
        errors.append(f"{fname}: required_level must be a whole number (rows: {_bad_rows(lvl_ok)})")
    else:
        lvl = pd.to_numeric(df["required_level"])
        out = (lvl < SKILL_SCALE_MIN) | (lvl > SKILL_SCALE_MAX)
        if out.any():
            errors.append(
                f"{fname}: required_level outside {SKILL_SCALE_MIN}-{SKILL_SCALE_MAX} "
                f"(rows: {_bad_rows(~out)})"
            )

    cnt_ok = _is_whole_number_series(df["required_operators"])
    if not cnt_ok.all():
        errors.append(f"{fname}: required_operators must be a whole number (rows: {_bad_rows(cnt_ok)})")
    else:
        cnt = pd.to_numeric(df["required_operators"])
        if (cnt < 0).any():
            errors.append(f"{fname}: required_operators must not be negative")

    return names.tolist()


def _validate_skill_like(df: pd.DataFrame, fname: str, station_names: list,
                         operator_ids: list, errors: list) -> None:
    expected = CSV_SCHEMA["skill"]["columns"] + list(station_names)
    if not _check_exact_columns(df, expected, fname, errors):
        return

    ids = df["operator_id"].astype(str).str.strip()
    if operator_ids and set(ids) != set(operator_ids):
        missing = set(operator_ids) - set(ids)
        extra = set(ids) - set(operator_ids)
        if missing:
            errors.append(f"{fname}: no row for operator(s): {', '.join(sorted(missing))}")
        if extra:
            errors.append(f"{fname}: unknown operator(s) not in operators.csv: {', '.join(sorted(extra))}")

    for col in station_names:
        whole = _is_whole_number_series(df[col])
        if not whole.all():
            errors.append(f"{fname}: column '{col}' has non-numeric / non-integer value(s) "
                          f"(rows: {_bad_rows(whole)})")
            continue
        vals = pd.to_numeric(df[col])
        out = (vals < SKILL_SCALE_MIN) | (vals > SKILL_SCALE_MAX)
        if out.any():
            errors.append(f"{fname}: column '{col}' has value(s) outside "
                          f"{SKILL_SCALE_MIN}-{SKILL_SCALE_MAX} (rows: {_bad_rows(~out)})")


def _validate_shifts(df: pd.DataFrame, operator_ids: list, errors: list) -> None:
    fname = "shifts.csv"
    if not _check_exact_columns(df, CSV_SCHEMA["shifts"]["columns"], fname, errors):
        return

    ids = df["operator_id"].astype(str).str.strip()
    shift_names = df["shift"].astype(str).str.strip()
    if (shift_names == "").any():
        errors.append(f"{fname}: blank shift value(s)")

    dup = ids[ids.duplicated()].unique().tolist()
    if dup:
        errors.append(f"{fname}: operator(s) assigned to more than one shift: {', '.join(dup)}")

    if operator_ids and set(ids) != set(operator_ids):
        missing = set(operator_ids) - set(ids)
        extra = set(ids) - set(operator_ids)
        if missing:
            errors.append(f"{fname}: no shift for operator(s): {', '.join(sorted(missing))}")
        if extra:
            errors.append(f"{fname}: unknown operator(s) not in operators.csv: {', '.join(sorted(extra))}")


def _bad_rows(ok_mask: pd.Series, limit: int = 8) -> str:
    """CSV-style 1-based row numbers (header = row 1) where ok_mask is False."""
    idx = [i + 2 for i, ok in enumerate(ok_mask.tolist()) if not ok]
    shown = ", ".join(str(i) for i in idx[:limit])
    return shown + (" ..." if len(idx) > limit else "")


def validate_frames(frames: dict) -> list:
    """
    frames: {logical_name: DataFrame} for the five inputs.
    Returns a list of error strings -- empty means the upload is valid.
    """
    errors: list = []

    required = set(CSV_SCHEMA.keys())
    present = set(frames.keys())
    for name in sorted(required - present):
        errors.append(f"missing file: {name}.csv")
    if required - present:
        return errors  # cannot cross-check without every file

    operator_ids = _validate_operators(frames["operators"], errors)
    station_names = _validate_stations(frames["stations"], errors)

    # Station columns / cross-file id checks only make sense once the two
    # reference lists parsed cleanly.
    _validate_skill_like(frames["skill"], "skill.csv", station_names, operator_ids, errors)
    _validate_skill_like(frames["routine"], "routine.csv", station_names, operator_ids, errors)
    _validate_shifts(frames["shifts"], operator_ids, errors)

    return errors
