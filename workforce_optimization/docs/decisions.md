# Decision Log -- Workforce Optimization

## From the Confluence Decision Log

| Decision | Alternative | Rationale |
|---|---|---|
| Per-station headcount constraint is `<=`, not `==` | Keep `==` (reference model) | `==` makes the whole solver infeasible if even one station can't be filled. `<=` leaves that station short and keeps the rest of the run (FR-09). |
| `routine > 0` eligibility filter kept as-is, no dedicated FR | Drop it; or formalize as an FR | Carrying it as an implicit rule keeps the FR list at business level. Trade-off: less traceable. |
| No persistent database -- CSV processed in-memory | SQLite (as in the Manufacturing Simulation project) | Optimization input must stay flexible and re-testable; no requirement to track results. Trade-off: no run history. |
| Last valid upload retained as default | Re-upload every time; or full version history | Convenience for repeated / demo use. Trade-off: only the most recent state is kept. |
| Exam -> skill/routine progression workflow out of scope | Model it inside the system | Keeps this a decision-support tool over externally maintained data, not an HR workflow system. |

## Decisions made while defining the build

| Decision | Rationale |
|---|---|
| **Competency weights are UI inputs**, defaults `w_skill = 2`, `w_routine = 1` | Confluence "Assumptions": configuration is loaded through the interface, not hardcoded. The reference `2*skill + routine` becomes the default only. An infobox in the sidebar states the formula. |
| **Shifts are a fifth input file** (`shifts.csv`: `operator_id, shift`), one shift per operator, shift names free text | The optimization is per-shift (FR-06); WO-4 needs to know who is in the shift. WO-5 can generate this file. |
| **WO-5 objective**: maximize the number of (shift, station) pairs with `>= target` eligible operators | Direct expression of "every shift needs >= 2 experts for every station". |
| **WO-5 headcount balance is a hard constraint** (`floor(n/S)..ceil(n/S)` per shift) | "Shifts should be the same size where possible." The sum of `required_operators` is shown as a per-shift reference but not forced -- with enough shifts it can be arithmetically impossible. |
| **WO-5 does not minimize movement** vs the current `shifts.csv` | Explicitly dropped to keep the model simple; the proposal is a fresh split. |
| **Infeasible (shift, station) coverage in WO-5** -> warning + pair reported as uncovered, solution still returned | Same spirit as FR-09. |
| **One optimum is enough** | No lexicographic / tie-break second pass on either model. CBC's first optimal solution is taken. |
| **"Expert" (FR-08) = operator eligible for the station** | The "more than one expert per station" target is covered by the `>= 2 eligible` resilience check; no separate higher skill threshold, to avoid another tunable. |
| **FR-11 "broadly covered" metric**: `redundancy_ratio` = of all stations, the share the operator is eligible for AND where workforce coverage already exceeds the target | Implements "hany helyen fedi le a szukseges igenyt az osszes munkaallomashoz kepest". |
| **FR-11 candidate cut-offs**: bottom third by cumulated skill; `redundancy_ratio >= 0.5`; operators already eligible everywhere are excluded (nothing to train) | Design choices, kept as plain constants in `analysis/recommendations.py`. |
| **Operator ids normalized to `OP01..OP10`** in the sample data | The reference notebook mixed `O1..O4` with `05..10`. Real input comes via CSV, so this only affects the bundled sample. |

## Carried over from the reference implementation

An operator is eligible for a station only if, on top of meeting the
minimum skill level, their routine value is `> 0`. Deliberate; formal
training alone is not treated as readiness.
