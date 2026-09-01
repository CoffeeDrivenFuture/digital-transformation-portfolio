# -*- coding: utf-8 -*-
"""
shift_reorg.py
--------------
Jira WO-5: propose how to split the whole workforce into N shifts.

This is a separate, manually triggered planning step -- it does NOT touch
the per-shift station allocation (WO-4). Its only job is to decide which
operators share a shift, so that afterwards every shift can be run
resiliently.

Model (binary program, PuLP / CBC)
  variables   y[i, s] = 1  operator i is on shift s
              covered[j, s] = 1  station j has >= target eligible operators on shift s
  objective   maximise  sum  covered[j, s]        (FR-07 resilience)
  s.t.        sum_s y[i, s] = 1                    each operator on exactly one shift
              floor(n/S) <= sum_i y[i, s] <= ceil(n/S)   balanced headcount
              target * covered[j, s] <= sum_{i eligible for j} y[i, s]

The headcount balance is a hard constraint ("shifts should be the same
size where possible"). The per-shift resilience target is the objective,
not a constraint: if there are not enough eligible operators to give
every (shift, station) pair the target, the model still returns a
solution and the short pairs are reported as warnings (same spirit as
FR-09).

"One optimum is enough" -- no secondary tie-break pass. The workstations'
required_operators sum is reported as a headcount reference per shift, but
is not forced (with enough shifts it can be arithmetically impossible).
"""

import os
import sys
import math
from dataclasses import dataclass, field

import pandas as pd
import pulp

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # project root

from config.wo_config import DEFAULT_MIN_QUALIFIED_PER_STATION, DEFAULT_NUM_SHIFTS  # noqa: E402
from data_io.loaders import InputData  # noqa: E402
from optimization.competency import eligibility_matrix  # noqa: E402


@dataclass
class ReorgResult:
    num_shifts: int
    status: str
    shifts_frame: pd.DataFrame          # operator_id, shift  (shifts.csv layout)
    coverage: pd.DataFrame              # shift x station, eligible counts
    uncovered_pairs: pd.DataFrame       # shift, station, eligible, target, shortfall
    headcount: pd.Series                # shift -> operators
    headcount_reference: int = 0        # sum(required_operators)
    covered_pairs: int = 0
    total_pairs: int = 0
    target: int = DEFAULT_MIN_QUALIFIED_PER_STATION
    weights: dict = field(default_factory=dict)

    @property
    def has_uncovered(self) -> bool:
        return not self.uncovered_pairs.empty


def reorganize_shifts(data: InputData, num_shifts: int = DEFAULT_NUM_SHIFTS,
                      target: int = None, shift_labels: list = None) -> ReorgResult:
    target = DEFAULT_MIN_QUALIFIED_PER_STATION if target is None else target
    operators = data.operator_list
    stations = data.station_list
    n = len(operators)
    S = max(1, int(num_shifts))
    labels = shift_labels or [f"Shift {k}" for k in range(1, S + 1)]

    elig = eligibility_matrix(data)
    lo, hi = math.floor(n / S), math.ceil(n / S)

    model = pulp.LpProblem("shift_reorganization", pulp.LpMaximize)
    y = {(i, s): pulp.LpVariable(f"y_{i}_{s}", cat=pulp.LpBinary) for i in operators for s in labels}
    covered = {(j, s): pulp.LpVariable(f"cov_{j}_{s}", cat=pulp.LpBinary) for j in stations for s in labels}

    model += pulp.lpSum(covered.values())

    for i in operators:
        model += pulp.lpSum(y[i, s] for s in labels) == 1, f"one_shift_{i}"
    for s in labels:
        model += pulp.lpSum(y[i, s] for i in operators) >= lo, f"min_head_{s}"
        model += pulp.lpSum(y[i, s] for i in operators) <= hi, f"max_head_{s}"
    for j in stations:
        eligible_ops = elig.index[elig[j]].tolist()
        for s in labels:
            model += (
                target * covered[j, s] <= pulp.lpSum(y[i, s] for i in eligible_ops),
                f"cover_{j}_{s}",
            )

    model.solve(pulp.PULP_CBC_CMD(msg=False))
    status = pulp.LpStatus[model.status]

    assign = {}
    for i in operators:
        for s in labels:
            v = y[i, s].value()
            if v is not None and round(v) == 1:
                assign[i] = s
    shifts_frame = pd.DataFrame({"operator_id": operators, "shift": [assign.get(i, "") for i in operators]})

    cov_rows = {}
    for s in labels:
        shift_ops = [i for i in operators if assign.get(i) == s]
        cov_rows[s] = elig.loc[shift_ops].sum() if shift_ops else pd.Series(0, index=stations)
    coverage = pd.DataFrame(cov_rows).T.reindex(index=labels, columns=stations).fillna(0).astype(int)

    uncovered = []
    for s in labels:
        for j in stations:
            e = int(coverage.loc[s, j])
            if e < target:
                uncovered.append({"shift": s, "station": j, "eligible": e,
                                  "target": target, "shortfall": target - e})
    uncovered_pairs = pd.DataFrame(uncovered, columns=["shift", "station", "eligible", "target", "shortfall"])

    headcount = shifts_frame.groupby("shift").size().reindex(labels).fillna(0).astype(int)
    headcount_reference = int(data.stations["required_operators"].sum())

    return ReorgResult(
        num_shifts=S,
        status=status,
        shifts_frame=shifts_frame,
        coverage=coverage,
        uncovered_pairs=uncovered_pairs,
        headcount=headcount,
        headcount_reference=headcount_reference,
        covered_pairs=len(stations) * S - len(uncovered),
        total_pairs=len(stations) * S,
        target=target,
    )


if __name__ == "__main__":
    from data_io.loaders import load_from_dir

    here = os.path.dirname(os.path.abspath(__file__))
    d = load_from_dir(os.path.join(os.path.dirname(here), "sample_data"))
    for S in (2, 3):
        res = reorganize_shifts(d, num_shifts=S)
        print(f"\n=== {S} shifts -- {res.status} "
              f"({res.covered_pairs}/{res.total_pairs} station-shift pairs resilient) ===")
        print("headcount:", dict(res.headcount), "| reference per shift:", res.headcount_reference)
        print(res.shifts_frame.to_string(index=False))
        print("coverage:\n", res.coverage)
        if res.has_uncovered:
            print("UNCOVERED:\n", res.uncovered_pairs.to_string(index=False))
