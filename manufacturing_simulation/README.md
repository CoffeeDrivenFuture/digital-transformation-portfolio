# Manufacturing Simulation

A decision-support tool for a small two-product production line: it
simulates machine cycle times, breakdowns, and material replenishment, then
turns the resulting event log into OEE/MTBF/MTTR figures you can compare
across "what if" scenarios -- different order volumes, machine parameters,
or stock policies -- without touching a real line.

## Background

This started as my own SimPy simulation and scheduling/routing code from
university coursework, plus earlier visualization work on top of it. The
broader motivation is an academic thesis, Gábor Filep, *"Lean-Oriented
Development of a Production Unit -- From Systems Thinking to Simulation
Support"* (Lean Engineer postgraduate program, Debrecen, 2025), pairing a
tiered SQDCP KPI framework with a discrete-event simulation to answer
capacity/bottleneck questions before committing to a real production plan.
This repo continues the simulation half of that work; the organizational
side of the KPI tree isn't part of this codebase.

## AI-assisted development

I used AI assistance (Claude) to extend and restructure the original code into this
repository: a persistent SQLite layer instead of one-off scripts, a proper
KPI engine, and an interactive Streamlit dashboard. The core simulation
model and routing logic are mine; AI assistance went mainly into
refactoring, the SQL/data layer, the KPI engine, documentation, and the
Streamlit build-out. I reviewed, adjusted, and tested all of it myself
rather than taking generated code as-is.

## What it's for

- **Bottleneck analysis** -- which machine limits overall output, and by how much.
- **Capacity / flow analysis** -- can the line keep up with a given order
  pattern; where does work pile up.
- **Machine-failure impact** -- how one machine's MTBF/MTTR ripples into
  OEE and downstream blocking.
- **What-if comparison** -- run different order patterns, machine
  parameters, or stock policies as separate scenarios and compare KPIs.

Think of it as a simulation-based digital-twin *approach* rather than a
live one: no connection to real shop-floor data or equipment, and every run
is a standalone, offline scenario.

**Lean relevance**: the model lets you observe bottlenecks, WIP buildup,
material-blocking, and how a disruption ripples downstream -- it doesn't
implement a Lean methodology itself, it's a model to look at those
questions through.

## Architecture

```
config/       Central factory configuration (structural + default runtime params)
simulation/   SimPy simulation + SQLite persistence layer
kpi/          OEE / MTBF / MTTR computation engine
dashboard/    Streamlit UI: configurable runs, KPI visualization, Yamazumi chart
data/         Generated at runtime (git-ignored) -- the SQLite database lives here
docs/         Jira backlog, SQL schema export, status notes
```

Each layer only depends on the one before it: `simulation` writes to
SQLite, `kpi` reads the event log and writes KPIs back, `dashboard` just
queries the database. Streamlit is a thin presentation layer -- it could be
swapped for Power BI or another BI tool reading the same file, untouched
simulation/KPI code.

**Example run**: the sidebar dispatches a batch, say 20 units of product A.
Each unit moves through `Machine0 -> Machine2 -> Machine3`, consuming
material at each station; a machine may be mid-repair (exponential
MTBF/MTTR) or blocked on material, both logged as status events. Every
processing step writes a `production_events` row (good/bad, per that
machine's quality rate). `kpi_engine.py` aggregates the log per simulated
day into Availability, Performance, Quality, OEE, MTBF, MTTR per machine,
and the dashboard renders those, comparable across runs.

## OEE, MTBF, MTTR

- **Availability** = working time / (working + blocked + repair time)
- **Performance** = (ideal cycle time x units produced) / working time --
  can exceed 100% if a machine outpaces its nominal cycle time (a property
  of the simplified model, not a bug)
- **Quality** = good units / total units produced
- **OEE** = Availability x Performance x Quality
- **MTBF** = average time between the start of consecutive repair events
- **MTTR** = average duration of a repair event

Computed per simulated day, per machine, from the raw event log.

## How to run

```powershell
pip install -r requirements.txt
streamlit run dashboard/app.py
```

The database is created automatically on first run.

## Changing the configuration

Machine list, product routes, material rules, and defaults live in
`config/prod_config.py`. Sidebar changes take effect on the next "Run new
simulation" click, no restart needed. Editing `prod_config.py` itself needs
a full restart (`Ctrl+C`, then `streamlit run` again) -- Python's module
caching and Streamlit's widget-state persistence mean a plain file save
while the app is running won't reliably propagate.

## Limitations

- **Single runs aren't statistically validated results.** The simulation
  is stochastic (exponential MTBF/MTTR, random quality draws); one run is
  one sample, not a proven average. Multi-run replication isn't
  implemented -- a natural next step. Read numbers as indicative, not final.
- **No live data connection**, and no SQDCP category/tier filter (KPI rows
  aren't tagged with one).
- **Yamazumi takt-time** reflects the currently configured sidebar order
  pattern, not necessarily the selected run's historical one -- order
  pattern isn't persisted per run, only machine/material parameters are.
- **Runs predating the per-run parameter snapshot** can't have their KPIs
  retroactively corrected if they used a per-machine override.

See `docs/` for the fuller backlog and decision history.
