# Backlog -- Workforce Optimization (Jira project WO)

Source: Jira project WO + Confluence (Requirements, Solution Concept,
Integration Design). All issues were "To Do" at project start; this file
tracks how each maps onto the code.

## Epic

**WO-1 -- Workforce Optimization: Skill-based Shift Allocation Tool**
Decision support tool that assigns operators to workstations based on
skill and routine, using a PuLP optimization model. Covers data loading,
optimization, shift reorganization, gap / expert / recommendation views,
and Excel export.

## Stories

| Story | Scope | FR | Code |
|---|---|---|---|
| **WO-2** | Load operator / skill / routine / workstation data from CSV, with format validation; last valid upload retained as default | FR-01..04 | `data_io/validation.py`, `data_io/loaders.py`, `data_io/store.py` |
| **WO-3** | Download a sample input package matching the expected format | Integration Design step 0 | `data_io/sample_package.py`, sidebar download button |
| **WO-4** | Run skill-based optimization for the current shift (`w_skill*skill + w_routine*routine`, min. qualification, `routine > 0`); understaffed stations flagged, not blocking | FR-06, FR-09 | `optimization/competency.py`, `optimization/shift_allocation.py` |
| **WO-5** | Manually trigger shift reorganization -- split the workforce into N shifts so each shift is resilient; separate from WO-4 | FR-05 | `optimization/shift_reorg.py` |
| **WO-6** | Export assignment results + gap list to Excel (Assignments + Gaps sheets) | FR-07 | `export/excel_export.py` |
| **WO-7** | Dashboard: skill matrix with gaps highlighted, expert list, promotion candidates, training recommendations | FR-08, FR-10, FR-11 | `analysis/coverage.py`, `analysis/recommendations.py`, `dashboard/app.py`, `dashboard/charts.py` |

## Business / Functional requirements

| BR | |
|---|---|
| BR-01 | Improve resource allocation process |
| BR-02 | Skill gap identification |
| BR-03 | Recommendation system for training and promoting |

| FR | Description | Where |
|---|---|---|
| FR-01 | Operator data loadable | `loaders.load_from_uploads` |
| FR-02 | Skill matrix loadable | same |
| FR-03 | Routine loadable | same |
| FR-04 | Workstation requirements loadable | same |
| FR-05 | Shift allocation manually triggered on reorganization | tab 2, `reorganize_shifts` |
| FR-06 | Operator workstations defined per shift | tab 1, `allocate_shift` |
| FR-07 | Experience / knowledge gaps represented (>= 2 eligible per station per shift) | `coverage.py`, tab 3, Gaps sheet |
| FR-08 | Experts listed | `recommendations.experts_by_station`, tab 4 |
| FR-09 | Missing workforce -> notification + station left empty | `shift_allocation` `<=` constraint + `gaps`, warnings in tab 1 |
| FR-10 | Top 5 by cumulated skill (tie: cumulated routine) as promotion candidates | `recommendations.promotion_candidates` |
| FR-11 | Training candidates (lowest cumulated skill / broadly covered), prioritized training area | `recommendations.training_candidates` |

## Out of scope (Decision Log)

- Persistent database / run history / versioning
- Minimizing operator movement between shifts on reorganization
- Exam -> skill/routine progression workflow (data is maintained outside the tool)
- Real company data (synthetic only)
- Non-functional requirements table on the Confluence page was left empty
