# -*- coding: utf-8 -*-
"""
recommendations.py
------------------
The development-side outputs, shown on the dashboard only (never in the
Excel export):

FR-08  experts_by_station()
       Per station, the eligible operators ranked by competency. Stations
       with fewer than the resilience target are flagged as single-point
       -of-failure.

FR-10  promotion_candidates()
       Top N operators by cumulated skill across all stations. Ties are
       broken by cumulated routine. These are the people closest to being
       able to move up / take on more.

FR-11  training_candidates()
       Operators recommended for training because they either
         (a) have the lowest cumulated skill, or
         (b) are "broadly covered" -- redundancy_ratio: of all stations,
             the share this operator is eligible for AND where the
             workforce already has enough other cover. A high ratio means
             training this person in a NEW area costs the least.
       The recommended area itself is prioritised as:
         1. a station with low coverage in the operator's own shift
         2. failing that, a station with low coverage workforce-wide
       (only stations the operator is not already eligible for).

The "low skill" cut-off (bottom third) and the "broadly covered" ratio
threshold (0.5) are design choices, recorded in decisions.md; both are
plain module constants so they are easy to revisit.
"""

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # project root

from config.wo_config import DEFAULT_MIN_QUALIFIED_PER_STATION, PROMOTION_TOP_N  # noqa: E402
from data_io.loaders import InputData  # noqa: E402
from optimization.competency import competency_matrix, eligibility_matrix  # noqa: E402
from analysis.coverage import coverage_by_shift, workforce_coverage  # noqa: E402

LOW_SKILL_QUANTILE = 1 / 3      # bottom third by cumulated skill -> training candidate (a)
BROADLY_COVERED_RATIO = 0.5     # redundancy_ratio at/above this -> training candidate (b)


def experts_by_station(data: InputData, weights: dict = None,
                       min_qualified: int = None) -> dict:
    """{station: DataFrame(operator_id, skill, routine, competency)} ranked by competency."""
    threshold = DEFAULT_MIN_QUALIFIED_PER_STATION if min_qualified is None else min_qualified
    comp = competency_matrix(data, weights)
    elig = eligibility_matrix(data)
    out = {}
    for station in data.station_list:
        ops = elig.index[elig[station]].tolist()
        df = pd.DataFrame({
            "operator_id": ops,
            "skill": [int(data.skill.loc[o, station]) for o in ops],
            "routine": [int(data.routine.loc[o, station]) for o in ops],
            "competency": [float(comp.loc[o, station]) for o in ops],
        }).sort_values("competency", ascending=False).reset_index(drop=True)
        df.attrs["single_point_of_failure"] = len(df) < threshold
        out[station] = df
    return out


def promotion_candidates(data: InputData, top_n: int = PROMOTION_TOP_N) -> pd.DataFrame:
    """FR-10: highest cumulated skill, tie-break on cumulated routine."""
    df = pd.DataFrame({
        "operator_id": data.operator_list,
        "cumulated_skill": data.skill.sum(axis=1).astype(int).values,
        "cumulated_routine": data.routine.sum(axis=1).astype(int).values,
    })
    df = df.sort_values(
        ["cumulated_skill", "cumulated_routine"], ascending=[False, False]
    ).reset_index(drop=True)
    df.insert(0, "rank", df.index + 1)
    return df.head(top_n)


def _redundancy_ratio(data: InputData) -> pd.Series:
    """
    Per operator: of ALL stations, the share the operator is eligible for
    AND where the workforce already has more than the resilience target of
    cover (so this operator's cover there is redundant).
    """
    elig = eligibility_matrix(data)
    wf_cov = workforce_coverage(data)
    redundant_station = wf_cov > DEFAULT_MIN_QUALIFIED_PER_STATION
    n_stations = len(data.station_list)
    covered_and_redundant = (elig & redundant_station).sum(axis=1)
    return (covered_and_redundant / n_stations).rename("redundancy_ratio")


def _recommended_training_station(data: InputData, operator: str,
                                  shift_cov: pd.DataFrame, wf_cov: pd.Series) -> str:
    elig = eligibility_matrix(data)
    not_yet = [j for j in data.station_list if not bool(elig.loc[operator, j])]
    if not_yet:
        shift = data.shifts.get(operator)
        row = shift_cov.loc[shift] if shift in shift_cov.index else wf_cov
        not_yet.sort(key=lambda j: (int(row.get(j, 0)), int(wf_cov.get(j, 0))))
        return not_yet[0]
    return ""


def training_candidates(data: InputData) -> pd.DataFrame:
    cum_skill = data.skill.sum(axis=1).astype(int)
    redundancy = _redundancy_ratio(data)
    shift_cov = coverage_by_shift(data)
    wf_cov = workforce_coverage(data)

    low_skill_cut = cum_skill.quantile(LOW_SKILL_QUANTILE)

    rows = []
    for o in data.operator_list:
        is_low_skill = cum_skill[o] <= low_skill_cut
        is_broadly_covered = redundancy[o] >= BROADLY_COVERED_RATIO
        if not (is_low_skill or is_broadly_covered):
            continue
        recommended = _recommended_training_station(data, o, shift_cov, wf_cov)
        if not recommended:
            # Already eligible for every station -- nothing left to train.
            continue
        reasons = []
        if is_low_skill:
            reasons.append("low overall skill")
        if is_broadly_covered:
            reasons.append("skills already well covered")
        rows.append({
            "operator_id": o,
            "shift": data.shifts.get(o),
            "cumulated_skill": int(cum_skill[o]),
            "redundancy_ratio": round(float(redundancy[o]), 2),
            "reason": ", ".join(reasons),
            "recommended_training": recommended,
        })
    df = pd.DataFrame(rows, columns=[
        "operator_id", "shift", "cumulated_skill", "redundancy_ratio",
        "reason", "recommended_training",
    ])
    return df.sort_values(["cumulated_skill", "redundancy_ratio"],
                          ascending=[True, False]).reset_index(drop=True)


if __name__ == "__main__":
    from data_io.loaders import load_from_dir

    here = os.path.dirname(os.path.abspath(__file__))
    d = load_from_dir(os.path.join(os.path.dirname(here), "sample_data"))

    print("=== experts by station (FR-08) ===")
    for station, df in experts_by_station(d).items():
        flag = "  [single point of failure]" if df.attrs["single_point_of_failure"] else ""
        print(f"\nstation {station}{flag}")
        print(df.to_string(index=False))

    print("\n=== promotion candidates (FR-10) ===")
    print(promotion_candidates(d).to_string(index=False))

    print("\n=== training candidates (FR-11) ===")
    print(training_candidates(d).to_string(index=False))
