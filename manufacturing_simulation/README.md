# Manufacturing Simulation

A simulation-driven decision-support tool for a small, two-product manufacturing
line: SimPy production simulation → SQLite persistence → KPI engine (OEE,
MTBF/MTTR) → Streamlit dashboard.

## Background & methodology

This project implements the simulation and KPI-engineering component of an
academic thesis: Gábor Filep, *"Lean-Oriented Development of a Production
Unit — From Systems Thinking to Simulation Support"* (Lean Engineer
postgraduate program, Debrecen, 2025).

The thesis addresses a common challenge in newly launched production lines:
unstructured processes, frequent unplanned downtime, and inconsistent data
collection make it difficult to estimate true line capacity or plan staffing
and material flow with any confidence. Its proposed approach combines two
things:

1. A hierarchical **KPI-tree** structured around the **SQDCP** methodology
   (Safety, Quality, Delivery, Cost, People), broken down by management tier
   (T1–T4), giving each level of the organization visibility into the metrics
   relevant to their role.
2. A **discrete-event simulation** (SimPy) of the production line — machine
   cycle times, failure/repair behavior (modeled via exponential
   distributions, standard practice for reliability modeling), and a
   "supermarket"-style material supply system with its own pre-production
   replenishment logic — to answer "what-if" capacity, bottleneck, and
   inventory questions before committing to a real production plan.

This repository is the applied, code-level continuation of that second part:
the **Cost-Efficient Operations** branch of the KPI tree (OEE and its
Availability/Performance/Quality decomposition, MTBF/MTTR) and the
simulation engine itself, rebuilt around a persistent SQL layer and an
interactive dashboard rather than a one-off analysis script. The
minimum-stock-level logic (`stock_recommendation.py`) implements the same
consumption-rate-vs-production-rate methodology derived in the thesis, with
a configurable safety factor.

**Deliberately out of scope for this repository**: the full organizational
framework around the KPI tree (the tiered daily-management meeting
structure, line-board data collection, skill-matrix-based workforce
optimization) is covered in the thesis but isn't part of this simulation
codebase — the skill-based operator assignment component now lives in a
separate project.

## Architecture

```
config/       Central factory configuration (structural + default runtime params)
simulation/   SimPy simulation + SQLite persistence layer
kpi/          OEE / MTBF / MTTR computation engine
dashboard/    Streamlit UI: configurable runs, KPI visualization, Yamazumi chart
data/         Generated at runtime (git-ignored) — the SQLite database lives here
docs/         Jira backlog, Confluence/SQL schema export, status notes
```

## How to run

```powershell
pip install -r requirements.txt
streamlit run dashboard/app.py
```

The database is created automatically on first run. No manual setup needed.

## Changing the configuration

All structural and default-runtime parameters live in `config/prod_config.py`
(machine list, product routes, material rules, `DEFAULT_*` values,
`TARGET_OEE`) -- see that file's own docstring for the structural-vs-runtime
distinction. There are two different ways to change behavior, with two
different restart requirements:

**Per-run, from the dashboard sidebar** -- no restart needed. Order pattern
(batch size, interval, product mix) and per-machine cycle_time / quality /
MTBF / MTTR overrides are just widget state; every "Run new simulation"
click reads whatever the sidebar currently shows and passes it straight to
`run_simulation()`. This is the normal way to explore "what-if" scenarios.

**Editing `config/prod_config.py` directly** -- for changing a *default*
every future run should start from, or the factory's structure itself
(adding a machine, changing a product's route). This needs a full
**restart of the Streamlit process** (`Ctrl+C`, then `streamlit run
dashboard/app.py` again) to reliably take effect. Saving the file while the
app is already running is not enough, for two separate reasons:

- Streamlit's local file watcher does hot-reload `prod_config.py` itself,
  but `production_sim_db.py` (and `kpi_engine.py`, `stock_recommendation.py`)
  each hold their *own* `from config.prod_config import ...` binding, made
  once when *that* file was first imported this session. Editing only
  `prod_config.py` doesn't re-trigger those other files' imports, so the
  code that actually runs the simulation can keep using the old values even
  though the sidebar looks updated.
- Even inside `dashboard/app.py` itself, the per-machine override sliders
  pass their config default as `value=` alongside a `key=`; by Streamlit's
  widget rules, `value=` only applies the *first* time that key is seen in
  a given browser session -- an already-open dashboard tab won't pick up a
  new default either, only a fresh tab/session would.

A full process restart avoids both: it's a new Python process, so every
module re-imports the current file contents from scratch.

## Scope note: what the KPI engine is (and isn't)

The `kpi_daily` table and the OEE/MTBF/MTTR dashboard sections are intentionally
scoped as a **per-scenario calculation, not a live production-monitoring system**.

A classical SQDCP KPI framework is normally built on top of a continuous stream
of real shop-floor data — day after day, shift after shift — with trend lines,
target-vs-actual tracking, and drill-down by category/tier. This project's data
source is different by design: each simulation `run_id` is a **bounded, isolated
scenario** (e.g. "5 days at this order pattern, with these machine parameters"),
not a slice of an ongoing production history. There is no "yesterday" or
"tomorrow" across runs — every run is its own self-contained world.

Rather than pretending otherwise, the project leans into this: the dashboard's
run selector lets you compare KPIs **across different simulated scenarios**
(different order patterns, different machine configurations) side by side. That
positions this less as a shop-floor monitoring dashboard and more as a **what-if
scenario comparison tool** — which is what the underlying simulation is actually
good at.

One practical consequence of this scope: an **SQDCP category/tier filter** on
the dashboard is not implemented, because the current schema has no SQDCP
categorization attached to `kpi_daily` rows. If this gets picked up later, the
intended approach is a small **static lookup/config mapping** (e.g. "OEE →
Quality + Delivery category, T1 tier"), not a simulation-derived value.

## Known limitations (tracked as backlog items, not bugs)

- **OEE breakdown chart UX**: iterated multiple times for clarity (dedicated
  sorted bar chart with industry-benchmark and target reference lines); the
  underlying "component breakdown" chart is intentionally kept as a secondary
  view rather than the primary one.
- **Yamazumi chart takt-time caveat**: the takt-time reference line reflects
  the *currently configured* order pattern (dashboard sidebar), not
  necessarily the historical order pattern of whichever run is selected for
  viewing — the app doesn't persist order-pattern parameters per run today,
  only machine/material parameters.
- **Historical runs with per-machine overrides**: any simulation run created
  before the run-specific parameter snapshot was added (see commit history)
  cannot have its KPI values retroactively corrected if it used a per-machine
  sidebar override — the actual parameters in effect at the time weren't
  recorded. Newer runs are unaffected.

See `docs/` for the full status breakdown and decision history.
