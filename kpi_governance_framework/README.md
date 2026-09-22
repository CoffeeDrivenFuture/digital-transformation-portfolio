# KPI Governance Framework — Tiered KPI Tree & Meeting Cadence

A structured performance-management framework for a newly ramping-up
production unit: a hierarchical KPI tree that cascades a single company
objective down through five strategic pillars to concrete, ownable
metrics, paired with a tiered daily-management (TDM) meeting cadence
that puts the right metric in front of the right person at the right
level.

Fourth case study in the digital transformation portfolio. Where
[`manufacturing_simulation/`](../manufacturing_simulation) models
machine-level throughput and OEE through simulation, this case defines
the **organizational** side of the same problem: how a plant decides
what to measure, who owns each number, and how issues escalate from
shop floor to senior management.

## Background

This is the governance/KPI-tree half of my postgraduate thesis, Gábor
Filep, *"Lean-Oriented Development of a Production Unit — From Systems
Thinking to Simulation Support"* (Lean Engineer postgraduate program,
Debrecen, 2025). The simulation half of that thesis is implemented in
`manufacturing_simulation/`; this case study covers the framework
designed to run a new production line from day one, before reliable
digital data capture is in place.

## What it's for

A common failure mode when starting up a new production line: teams
disagree on priorities, data is incomplete, and — because processes
aren't yet standardized — the same underlying event gets reported as
different numbers by different people. This framework is a starting
KPI system meant to prevent exactly that, designed to be adapted to
specific needs once the line stabilizes.

![KPI Tree](./KPI_Tree_EN.jpg)

See [`docs/methodology.md`](./docs/methodology.md) for the full
breakdown: the KPI tree structure, the five strategic pillars and their
metrics, data-capture approach, and the four-tier meeting cadence.

## Status

Documentation-only case study: framework and methodology, translated
and restructured from the original thesis chapter. No code — this
complements the simulation case study's technical model with the
organizational structure it assumes.
