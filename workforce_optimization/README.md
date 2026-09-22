# Workforce Optimization

A decision-support tool that assigns manual-workstation operators to
stations for a shift, based on how well each operator is trained (skill)
and how much hands-on practice they have (routine). It surfaces coverage
risks -- stations that depend on a single person -- and suggests who to
promote and who to cross-train.

Live link : https://workforce-optimization.streamlit.app/

Second project of the digital transformation portfolio, alongside
`manufacturing_simulation`, with its own virtual environment.

## Background

Lines, equipment and layout get optimized; the people running them are
often treated as interchangeable headcount whose only attribute is "has
the work permit". This tool makes training and experience the basis of
the allocation instead: every shift should be coverable by the right
people, with no single points of failure.

The optimization core started as a small PuLP model in a Colab notebook
(`skillmatrix`) -- 10 operators, 4 stations, maximize `2*skill + routine`
subject to per-station headcount and one-station-per-operator.

## AI-assisted development

I used AI assistance (Claude) to turn that notebook into this project:
CSV input with validation, a shift-reorganization model, coverage / gap
analysis, promotion and training recommendations, an Excel export, and a
Streamlit dashboard. The optimization formulation is from my reference
notebook; AI assistance went into the surrounding structure, the data
layer, the analysis functions, docs and the dashboard. I reviewed and
tested all of it.

## Architecture

```
CSV upload  ->  pandas (validate + index)  ->  PuLP / CBC  ->  Streamlit dashboard (Plotly) + Excel export
```

```
config/        Default weights, resilience target, validation scale
data_io/       CSV validation, loading, the sample package, last-upload retention
optimization/  competency + eligibility, per-shift allocation (WO-4), shift reorganization (WO-5)
analysis/      coverage / gaps (FR-07), experts / promotion / training (FR-08/10/11)
export/        Excel workbook (Assignments + Gaps)
dashboard/     Streamlit UI (app.py) + Plotly figures (charts.py)
docs/          backlog, decision log, data schema
sample_data/   the reference dataset as CSVs (also the built-in default)
```

The dashboard has four tabs -- shift allocation, shift reorganization,
skill matrix & coverage, recommendations -- built around status-coloured
charts (station staffing bars, an eligibility-coded skill matrix,
coverage heatmaps) rather than raw tables; the underlying tables are kept
in expanders. It renders on a dark theme (`.streamlit/config.toml`).

No database. The loaded scenario lives in the Streamlit session; the last
valid upload is mirrored to `.cache/` (git-ignored) so it returns as the
default on the next start. There is no run history -- see `docs/decisions.md`.

## How to run

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run dashboard/app.py
```

Every module also runs standalone against the sample data, e.g.:

```powershell
python optimization/shift_allocation.py
python optimization/shift_reorg.py
python analysis/recommendations.py
```

Tests: `python tests/test_wo.py` (plain asserts, also collectible by pytest).

## The model

- **Eligibility** (hard): `skill >= station.required_level` and `routine > 0`.
- **Competency**: `w_skill * skill + w_routine * routine`; weights are
  sidebar inputs, defaults 2 and 1.
- **Per-shift allocation (WO-4)**: maximize total competency; each station
  gets *at most* `required_operators` (a station that can't be filled is
  left short and flagged, not blocked); each operator at most one station.
- **Shift reorganization (WO-5)**: split the workforce into N shifts,
  balanced in size, maximizing the number of (shift, station) pairs that
  reach the resilience target (default 2 eligible operators).

## Business value / KPIs

The tool supports:

- assigning the right people to the right stations
- more than one qualified operator per station per shift (coverage risk down)
- targeted training instead of ad-hoc allocation
- identifying operators ready to take on more

Portfolio-level KPIs for the transformation initiative are tracked in the
portfolio README, not here.

## Limitations

- **Synthetic data only.** No connection to a real skill database or shift
  system; skill / routine values are maintained outside the tool.
- **One run is one plan.** No history, no versioning, no comparison
  between runs.
- **Reorganization proposes a fresh split.** It does not try to keep
  people on their current shift.
- **A single optimum.** Where several assignments score equally, one is
  returned with no preference between them.
- The FR-11 training cut-offs (bottom third by skill, redundancy >= 0.5)
  are design choices, not derived from the requirements -- see
  `docs/decisions.md`.
