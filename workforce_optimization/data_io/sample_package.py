# -*- coding: utf-8 -*-
"""
sample_package.py
-----------------
The sample input package offered for download in the UI (Jira WO-3).

It doubles as the built-in default dataset: on a fresh install, with no
prior upload, the dashboard falls back to this so there is always
something to run. The values come from the reference `skillmatrix`
notebook -- 10 operators, 4 stations -- with the operator ids normalised
to OP01..OP10 (the notebook mixed "O1".."O4" with "05".."10").

Everything is defined here as DataFrames so the CSV files under
`sample_data/` cannot silently drift from the code -- run this module as a
script to regenerate them.

Assumption check: this data is fully synthetic, no real company data.
"""

import io
import os
import zipfile

import pandas as pd

STATIONS = ["A", "B", "C", "D"]

OPERATORS = [f"OP{n:02d}" for n in range(1, 11)]

# skill / routine on the 0-5 scale, operator x station.
_SKILL = {
    "A": [3, 5, 0, 3, 2, 1, 3, 4, 4, 0],
    "B": [2, 2, 4, 0, 2, 0, 1, 0, 5, 0],
    "C": [1, 3, 2, 4, 3, 5, 2, 2, 5, 0],
    "D": [0, 1, 1, 5, 1, 2, 1, 0, 3, 5],
}
_ROUTINE = {
    "A": [4, 5, 0, 3, 3, 5, 2, 1, 3, 0],
    "B": [2, 1, 4, 0, 3, 0, 2, 0, 2, 0],
    "C": [0, 4, 3, 4, 3, 2, 3, 1, 3, 4],
    "D": [0, 2, 1, 5, 3, 0, 4, 0, 4, 2],
}

# Minimum skill level and headcount required per station (from the
# reference notebook: required_level and required_operators_per_station).
_STATIONS_ROWS = [
    # station, required_level, required_operators
    ("A", 1, 1),
    ("B", 2, 2),
    ("C", 3, 1),
    ("D", 2, 2),
]

# A two-shift split. "Day" is deliberately staffed so every station can be
# filled; "Night" is left thin on purpose, so the sample exercises the
# gap / warning path (station D has nobody eligible at night) as well as
# the clean one.
_SHIFTS = {
    "OP01": "Day", "OP02": "Day", "OP04": "Day", "OP06": "Day",
    "OP09": "Day", "OP10": "Day",
    "OP03": "Night", "OP05": "Night", "OP07": "Night", "OP08": "Night",
}


def sample_operators() -> pd.DataFrame:
    return pd.DataFrame({"operator_id": OPERATORS})


def sample_skill() -> pd.DataFrame:
    return pd.DataFrame({"operator_id": OPERATORS, **_SKILL})


def sample_routine() -> pd.DataFrame:
    return pd.DataFrame({"operator_id": OPERATORS, **_ROUTINE})


def sample_stations() -> pd.DataFrame:
    return pd.DataFrame(
        _STATIONS_ROWS, columns=["station", "required_level", "required_operators"]
    )


def sample_shifts() -> pd.DataFrame:
    return pd.DataFrame(
        {"operator_id": OPERATORS, "shift": [_SHIFTS[o] for o in OPERATORS]}
    )


def sample_frames() -> dict:
    """{logical_name: DataFrame} for all five input files."""
    return {
        "operators": sample_operators(),
        "skill": sample_skill(),
        "routine": sample_routine(),
        "stations": sample_stations(),
        "shifts": sample_shifts(),
    }


def write_sample_package(target_dir: str) -> list:
    """Writes the five sample CSVs into target_dir. Returns the paths."""
    os.makedirs(target_dir, exist_ok=True)
    paths = []
    for name, df in sample_frames().items():
        path = os.path.join(target_dir, f"{name}.csv")
        df.to_csv(path, index=False)
        paths.append(path)
    return paths


def sample_package_zip_bytes() -> bytes:
    """The five sample CSVs as an in-memory .zip, for a UI download button."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, df in sample_frames().items():
            zf.writestr(f"{name}.csv", df.to_csv(index=False))
    return buf.getvalue()


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    out = os.path.join(os.path.dirname(here), "sample_data")
    written = write_sample_package(out)
    for p in written:
        print("wrote", p)
