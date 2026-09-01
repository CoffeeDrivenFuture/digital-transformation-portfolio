# Data schema

## Input -- five CSV files

All files are validated on upload as a set: if any file is malformed the
whole upload is rejected and the UI names the file / column / value at
fault. Nothing is partially loaded.

### operators.csv
| Column | Notes |
|---|---|
| `operator_id` | unique, non-blank |

### skill.csv
| Column | Notes |
|---|---|
| `operator_id` | must match operators.csv exactly (same set) |
| one column per station | header names must equal the `station` values in stations.csv; values are whole numbers 0-5 |

### routine.csv
Same layout as skill.csv. Values 0-5.

### stations.csv
| Column | Notes |
|---|---|
| `station` | unique, non-blank |
| `required_level` | whole number 0-5 -- minimum skill to be eligible |
| `required_operators` | whole number >= 0 -- headcount to fill per shift |

### shifts.csv
| Column | Notes |
|---|---|
| `operator_id` | must match operators.csv; each operator appears once |
| `shift` | free-text shift name |

`shifts.csv` can be produced by the "Shift reorganization" tab and
uploaded back.

## Eligibility

Operator *i* is eligible for station *j* when
`skill[i,j] >= stations.required_level[j]` **and** `routine[i,j] > 0`.

## Competency

`competency[i,j] = w_skill * skill[i,j] + w_routine * routine[i,j]`,
where the weights are sidebar inputs (defaults 2 and 1).

## Output -- Excel (.xlsx)

| Sheet | Content |
|---|---|
| `Assignments` | `shift, operator_id, station, skill, routine, competency` -- the final assignment for every shift |
| `Gaps` | `shift, station, required_operators, assigned, shortfall` -- stations left below `required_operators` |

The recommendation views (experts, promotion, training) are shown on the
dashboard only and are not part of the export.
