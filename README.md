# Digital Transformation Portfolio

Two decision-support tools built to test, in practice, ideas I'd
previously only written about: that manufacturing transformation depends
as much on how people understand and engage with change as on the
systems built for them.

A CV lists what you've done. It doesn't show how you think through a
problem and take it from a vague business question to a working tool.
This repo is that: two independent case studies, each starting from an
operational problem, not from a technology I wanted to try out.

## Case studies

- **[`manufacturing_simulation/`](./manufacturing_simulation)** --
  discrete-event production line simulation (SimPy + SQLite) turned into
  an OEE/MTBF/MTTR decision-support dashboard. Builds on the simulation
  half of my Lean Engineer thesis, which paired a tiered SQDCP KPI
  framework with this kind of model *(diagram to be added)*.
- **[`workforce_optimization/`](./workforce_optimization)** -- operator-
  to-station assignment based on skill and hands-on routine rather than
  interchangeable headcount, with coverage-risk and training/promotion
  analysis (PuLP optimization + Streamlit).

## How this was built

I used AI assistance (Claude) throughout, mainly to turn existing
analytical/simulation code -- from earlier academic and personal work --
into proper applications: persistence layers, KPI/analysis engines,
dashboards, documentation. I directed the architecture, made the scope
and modeling decisions, and reviewed and tested everything myself. Each
project's README has more detail on that split.

The point of this portfolio: turning a business problem into something
that actually runs, end to end.

## Process documentation

Requirements, backlog, and decisions for both projects are tracked in
Jira and Confluence.

## Status

Both projects are functional and independently runnable -- see each
project's README for setup. Portfolio still being extended.

```
manufacturing_simulation/   Case study 1
workforce_optimization/     Case study 2
api-mock/                   in progress
```
