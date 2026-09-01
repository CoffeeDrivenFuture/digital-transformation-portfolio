# -*- coding: utf-8 -*-
"""
competency.py
-------------
The two derived matrices every optimization / analysis step builds on:

  competency = w_skill * skill + w_routine * routine
      A single score per (operator, station). Defaults w_skill=2,
      w_routine=1 (the reference model's "2*skill + routine"), but both
      weights come in as arguments -- the dashboard exposes them as
      sliders, per the "configuration through the interface" assumption.

  eligibility (boolean)
      operator may be assigned to / counts as cover for a station only if
        skill   >= station.required_level   AND
        routine >= MIN_ROUTINE_FOR_ELIGIBILITY   (i.e. routine > 0)
      The routine>0 half is a deliberate carry-over from the reference
      implementation -- formal training alone is not enough, see
      decisions.md.
"""

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # project root

from config.wo_config import (  # noqa: E402
    DEFAULT_COMPETENCY_WEIGHTS,
    MIN_ROUTINE_FOR_ELIGIBILITY,
)
from data_io.loaders import InputData  # noqa: E402


def competency_matrix(data: InputData, weights: dict = None) -> pd.DataFrame:
    """operator x station competency score. weights: {'skill': w, 'routine': w}."""
    w = weights or DEFAULT_COMPETENCY_WEIGHTS
    return w["skill"] * data.skill + w["routine"] * data.routine


def eligibility_matrix(data: InputData) -> pd.DataFrame:
    """operator x station boolean: meets the station's required_level and has routine > 0."""
    levels = data.stations["required_level"]
    meets_level = data.skill.ge(levels, axis=1)
    has_routine = data.routine.ge(MIN_ROUTINE_FOR_ELIGIBILITY)
    return meets_level & has_routine


def eligible_operators(data: InputData, station: str, among: list = None) -> list:
    """Operators eligible for `station`, optionally restricted to `among`."""
    col = eligibility_matrix(data)[station]
    ops = col.index[col].tolist()
    if among is not None:
        allowed = set(among)
        ops = [o for o in ops if o in allowed]
    return ops


if __name__ == "__main__":
    from data_io.loaders import load_from_dir

    here = os.path.dirname(os.path.abspath(__file__))
    d = load_from_dir(os.path.join(os.path.dirname(here), "sample_data"))
    print("competency (2*skill + routine):")
    print(competency_matrix(d), "\n")
    print("eligibility:")
    print(eligibility_matrix(d))
