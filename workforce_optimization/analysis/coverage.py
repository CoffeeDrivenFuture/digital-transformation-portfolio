# -*- coding: utf-8 -*-
"""
coverage.py
-----------
Resilience view of the workforce (FR-07): for every station, in every
shift, how many operators are *eligible* to run it -- and where that
number drops below the target (default 2), so no station leans on a
single key person.

This is separate from the WO-4 allocation gaps:
  - allocation gap  = a station could not be filled to required_operators
                      in an actual run
  - coverage gap    = fewer than N people *could* cover the station in
                      this shift, regardless of who was assigned

The coverage numbers also feed the training recommendations (FR-11): a
station with low coverage in a shift is a priority training target.
"""

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # project root

from config.wo_config import DEFAULT_MIN_QUALIFIED_PER_STATION  # noqa: E402
from data_io.loaders import InputData  # noqa: E402
from optimization.competency import eligibility_matrix  # noqa: E402


def coverage_by_shift(data: InputData) -> pd.DataFrame:
    """
    Rows = shifts, columns = stations, values = number of eligible
    operators assigned to that shift.
    """
    elig = eligibility_matrix(data)
    rows = {}
    for shift in data.shift_list:
        ops = data.operators_in_shift(shift)
        rows[shift] = elig.loc[ops].sum()
    return pd.DataFrame(rows).T.reindex(columns=data.station_list)


def workforce_coverage(data: InputData) -> pd.Series:
    """Total eligible operators per station across the whole workforce."""
    return eligibility_matrix(data).sum().reindex(data.station_list)


def coverage_gaps(data: InputData, min_qualified: int = None) -> pd.DataFrame:
    """
    One row per (shift, station) where the eligible count is below
    `min_qualified`. Empty DataFrame means every station is resilient in
    every shift.
    """
    threshold = DEFAULT_MIN_QUALIFIED_PER_STATION if min_qualified is None else min_qualified
    cov = coverage_by_shift(data)
    rows = []
    for shift in cov.index:
        for station in cov.columns:
            n = int(cov.loc[shift, station])
            if n < threshold:
                rows.append({
                    "shift": shift,
                    "station": station,
                    "eligible": n,
                    "target": threshold,
                    "shortfall": threshold - n,
                })
    return pd.DataFrame(rows, columns=["shift", "station", "eligible", "target", "shortfall"])


if __name__ == "__main__":
    from data_io.loaders import load_from_dir

    here = os.path.dirname(os.path.abspath(__file__))
    d = load_from_dir(os.path.join(os.path.dirname(here), "sample_data"))
    print("coverage by shift (eligible operators per station):")
    print(coverage_by_shift(d), "\n")
    print("workforce coverage:")
    print(workforce_coverage(d), "\n")
    print("coverage gaps (target 2):")
    print(coverage_gaps(d).to_string(index=False))
