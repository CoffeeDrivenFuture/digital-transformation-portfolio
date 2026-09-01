# -*- coding: utf-8 -*-
"""
shift_allocation.py
-------------------
Jira WO-4: assign the operators of one shift to the workstations of that
shift, maximising total competency.

Model (binary program, PuLP / CBC)
  variables   x[i, j] = 1 if operator i works station j
              only created for eligible (i, j) pairs
  objective   maximise  sum  competency[i, j] * x[i, j]
  s.t.        sum_i x[i, j] <= required_operators[j]     for each station j
              sum_j x[i, j] <= 1                          for each operator i

The per-station constraint is "<=", not "==" (Decision Log): if a station
cannot be filled, it is simply left short and flagged in `gaps` -- the
rest of the shift is still assigned. FR-09.

Because every competency score is positive, the solver already fills as
many slots as it can (each extra assignment strictly raises the
objective), so there is no separate "maximise coverage" term -- more
coverage and higher competency point the same way here.

"One optimum is enough" (Decision Log) -- we take CBC's first optimal
solution, no tie-break pass.
"""

import os
import sys
from dataclasses import dataclass, field

import pandas as pd
import pulp

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # project root

from data_io.loaders import InputData  # noqa: E402
from optimization.competency import competency_matrix, eligibility_matrix  # noqa: E402


@dataclass
class AllocationResult:
    shift: str
    status: str
    assignments: pd.DataFrame          # operator_id, station, skill, routine, competency
    gaps: pd.DataFrame                 # station, required_operators, assigned, shortfall
    unassigned_operators: list = field(default_factory=list)
    objective: float = 0.0
    weights: dict = field(default_factory=dict)

    @property
    def has_gaps(self) -> bool:
        return not self.gaps.empty


def allocate_shift(data: InputData, shift: str, weights: dict = None) -> AllocationResult:
    operators = data.operators_in_shift(shift)
    stations = data.station_list

    comp = competency_matrix(data, weights)
    elig = eligibility_matrix(data)

    pairs = [(i, j) for i in operators for j in stations if bool(elig.loc[i, j])]

    model = pulp.LpProblem(f"shift_allocation_{shift}", pulp.LpMaximize)
    x = {(i, j): pulp.LpVariable(f"x_{i}_{j}", cat=pulp.LpBinary) for (i, j) in pairs}

    model += pulp.lpSum(comp.loc[i, j] * x[i, j] for (i, j) in pairs)

    for j in stations:
        j_pairs = [(i, j) for i in operators if (i, j) in x]
        if j_pairs:
            model += (
                pulp.lpSum(x[p] for p in j_pairs) <= data.required_operators(j),
                f"headcount_{j}",
            )
    for i in operators:
        i_pairs = [(i, j) for j in stations if (i, j) in x]
        if i_pairs:
            model += pulp.lpSum(x[p] for p in i_pairs) <= 1, f"one_station_{i}"

    model.solve(pulp.PULP_CBC_CMD(msg=False))
    status = pulp.LpStatus[model.status]

    rows = []
    for (i, j), var in x.items():
        if var.value() is not None and round(var.value()) == 1:
            rows.append({
                "operator_id": i,
                "station": j,
                "skill": int(data.skill.loc[i, j]),
                "routine": int(data.routine.loc[i, j]),
                "competency": float(comp.loc[i, j]),
            })
    assignments = pd.DataFrame(rows, columns=["operator_id", "station", "skill", "routine", "competency"])
    if not assignments.empty:
        assignments = assignments.sort_values(["station", "competency"], ascending=[True, False]).reset_index(drop=True)

    assigned_per_station = assignments["station"].value_counts().to_dict() if not assignments.empty else {}
    gap_rows = []
    for j in stations:
        req = data.required_operators(j)
        got = int(assigned_per_station.get(j, 0))
        if got < req:
            gap_rows.append({
                "station": j,
                "required_operators": req,
                "assigned": got,
                "shortfall": req - got,
            })
    gaps = pd.DataFrame(gap_rows, columns=["station", "required_operators", "assigned", "shortfall"])

    assigned_ops = set(assignments["operator_id"]) if not assignments.empty else set()
    unassigned = [o for o in operators if o not in assigned_ops]

    objective = pulp.value(model.objective) or 0.0

    return AllocationResult(
        shift=shift,
        status=status,
        assignments=assignments,
        gaps=gaps,
        unassigned_operators=unassigned,
        objective=float(objective),
        weights=weights or {},
    )


def allocate_all_shifts(data: InputData, weights: dict = None) -> dict:
    """{shift: AllocationResult} for every shift in the data."""
    return {s: allocate_shift(data, s, weights) for s in data.shift_list}


if __name__ == "__main__":
    from data_io.loaders import load_from_dir

    here = os.path.dirname(os.path.abspath(__file__))
    d = load_from_dir(os.path.join(os.path.dirname(here), "sample_data"))
    for shift, res in allocate_all_shifts(d).items():
        print(f"\n=== shift {shift} -- {res.status}, objective {res.objective:.0f} ===")
        print(res.assignments.to_string(index=False))
        if res.has_gaps:
            print("GAPS:")
            print(res.gaps.to_string(index=False))
        if res.unassigned_operators:
            print("unassigned:", res.unassigned_operators)
