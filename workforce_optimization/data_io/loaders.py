# -*- coding: utf-8 -*-
"""
loaders.py
----------
Turns the five raw input CSVs into one validated `InputData` object that
the optimization and analysis layers consume. Nothing downstream reads
CSV files or re-checks formats -- if you hold an `InputData`, it is clean.

The three entry points differ only in where the raw frames come from:
  - load_from_frames()  : already-parsed DataFrames (used by tests and by
                          the built-in sample dataset)
  - load_from_dir()     : a directory of *.csv files
  - load_from_uploads() : Streamlit UploadedFile objects, keyed by logical
                          name

All three run validation.validate_frames() first and raise
ValidationError (with the full message list) if anything is wrong.
"""

import os
import sys
from dataclasses import dataclass

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # project root

from config.wo_config import CSV_FILENAMES  # noqa: E402
from data_io.validation import ValidationError, validate_frames  # noqa: E402


@dataclass
class InputData:
    """
    Clean, indexed view of one scenario.

    stations : DataFrame indexed by station -> required_level, required_operators
    skill    : DataFrame indexed by operator_id, one column per station (0-5)
    routine  : DataFrame indexed by operator_id, one column per station (0-5)
    shifts   : Series indexed by operator_id -> shift name
    """

    stations: pd.DataFrame
    skill: pd.DataFrame
    routine: pd.DataFrame
    shifts: pd.Series

    @property
    def station_list(self) -> list:
        return list(self.stations.index)

    @property
    def operator_list(self) -> list:
        return list(self.skill.index)

    @property
    def shift_list(self) -> list:
        return sorted(self.shifts.unique())

    def required_level(self, station: str) -> int:
        return int(self.stations.loc[station, "required_level"])

    def required_operators(self, station: str) -> int:
        return int(self.stations.loc[station, "required_operators"])

    def operators_in_shift(self, shift: str) -> list:
        return self.shifts.index[self.shifts == shift].tolist()


def _build_input_data(frames: dict) -> InputData:
    stations = frames["stations"].copy()
    stations["station"] = stations["station"].astype(str).str.strip()
    stations = stations.set_index("station")
    stations["required_level"] = pd.to_numeric(stations["required_level"]).astype(int)
    stations["required_operators"] = pd.to_numeric(stations["required_operators"]).astype(int)

    station_cols = list(stations.index)

    def _matrix(frame: pd.DataFrame) -> pd.DataFrame:
        m = frame.copy()
        m["operator_id"] = m["operator_id"].astype(str).str.strip()
        m = m.set_index("operator_id")[station_cols]
        return m.apply(pd.to_numeric).astype(int)

    skill = _matrix(frames["skill"])
    routine = _matrix(frames["routine"])

    sh = frames["shifts"].copy()
    sh["operator_id"] = sh["operator_id"].astype(str).str.strip()
    sh["shift"] = sh["shift"].astype(str).str.strip()
    shifts = sh.set_index("operator_id")["shift"]

    # Keep every table in the operators.csv order.
    operator_order = frames["operators"]["operator_id"].astype(str).str.strip().tolist()
    skill = skill.reindex(operator_order)
    routine = routine.reindex(operator_order)
    shifts = shifts.reindex(operator_order)

    return InputData(stations=stations, skill=skill, routine=routine, shifts=shifts)


def load_from_frames(frames: dict) -> InputData:
    errors = validate_frames(frames)
    if errors:
        raise ValidationError(errors)
    return _build_input_data(frames)


def load_from_dir(path: str) -> InputData:
    frames = {}
    for name, filename in CSV_FILENAMES.items():
        fpath = os.path.join(path, filename)
        if os.path.exists(fpath):
            frames[name] = pd.read_csv(fpath)
    return load_from_frames(frames)


def load_from_uploads(uploads: dict) -> InputData:
    """uploads: {logical_name: file-like / path}. Missing entries are reported by validation."""
    frames = {name: pd.read_csv(f) for name, f in uploads.items() if f is not None}
    return load_from_frames(frames)


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    data = load_from_dir(os.path.join(os.path.dirname(here), "sample_data"))
    print("stations:\n", data.stations, "\n")
    print("shifts:", dict(data.shifts), "\n")
    print("operators:", data.operator_list)
    print("shift list:", data.shift_list)
