#  Manufacturing Digitalization


## EPIC 1: Production KPI Framework (SQDCP)

**Epic description:** Establish a unified, SQDCP-based KPI structure fed by a single source of truth, replacing inconsistent Excel-based calculations.

**Components:** KPI Engine, SQL Layer

---

### US-101 — OEE breakdown per machine

**As a** Plant Manager
**I want** to see OEE broken down into Availability, Performance and Quality per machine
**So that** I can identify which component drives losses

**Acceptance Criteria:**
- OEE, Availability, Performance, Quality are calculated per `machine_id` and per day.
- Values are pulled directly from the SQLite database, not hardcoded.
- Dashboard shows a breakdown chart per machine.

**Priority:** Must have | **Labels:** `kpi`, `oee`

---

### US-102 — KPI filtering by SQDCP category and tier

**As a** Production Supervisor
**I want** to view KPIs filtered by SQDCP category and tier (T1–T4)
**So that** I only see what's relevant to my role

**Acceptance Criteria:**
- A filter/dropdown exists for SQDCP category.
- A filter/dropdown exists for tier level.
- Selecting a filter updates the visible KPI cards without a full page reload.

**Priority:** Should have | **Labels:** `kpi`, `dashboard`

---

### US-103 — MTBF/MTTR from event log

**As a** data analyst
**I want** MTBF and MTTR calculated from the simulation event log
**So that** Availability is grounded in real event data rather than assumptions

**Acceptance Criteria:**
- MTBF = average time between `breakdown_start` events per machine.
- MTTR = average duration between `breakdown_start` and `repair_end`.
- Both values are stored in a `kpi_daily` table row.

**Priority:** Must have | **Labels:** `kpi`, `oee`, `sql`

---

## EPIC 2: Production Capacity & Inventory Decision Support

**Epic description:** Provide simulation-based answers to "what-if" capacity, bottleneck and inventory questions.

**Components:** Simulation, Dashboard

---

### US-201 — Configurable order pattern simulation

**As a** production planner
**I want** to simulate a configurable order pattern
**So that** I can estimate whether the line can meet a given demand

**Acceptance Criteria:**
- Simulation accepts configurable batch size, interval, and product mix as input parameters.
- Simulation runs for a configurable duration (default: 5 days).
- Output includes total produced units per product, good vs. bad count.

**Priority:** Must have | **Labels:** `simulation`

---

### US-202 — Minimum stock level recommendation

**As a** supply chain coordinator
**I want** a recommended minimum stock level per material
**So that** I can avoid downtime caused by material shortage

**Acceptance Criteria:**
- The system calculates consumption rate and production (replenishment) rate per material.
- A minimum stock level with a configurable safety factor (default 1.2×) is output.
- Result is written to a `material_recommendations` table.

**Priority:** Must have | **Labels:** `simulation`, `sql`

---

### US-203 — Machine state visualization

**As a** plant manager
**I want** to see machine state (working / blocked / under repair) visualized over the simulation period
**So that** I can identify which machines are the biggest constraint

**Acceptance Criteria:**
- Stacked bar chart per machine showing time in each state.
- Data sourced from `machine_status_log` table.

**Priority:** Should have | **Labels:** `dashboard`, `simulation`

---

### US-204 — Yamazumi-style cycle time vs. takt time chart

**As a** process engineer
**I want** a Yamazumi-style chart showing each station's cycle time against the takt time
**So that** I can visually identify the bottleneck station without running a full simulation analysis

**Acceptance Criteria:**
- Chart shows one bar per station, grouped by product route (A and B separately, or combined view toggle).
- Bar height = station cycle time.
- A horizontal reference line marks the target takt time, calculated from order interval and batch size.
- Any station whose cycle time exceeds the takt time line is visually flagged (e.g. different bar color).
- Data is sourced from existing simulation configuration (`cycle_time`) and the already-implemented takt time calculation — no new simulation logic required.

**Priority:** Should have | **Labels:** `dashboard`, `lean`

---

### US-205 — Bottleneck-paced line scheduling (stretch goal)

**As a** process engineer
**I want** non-bottleneck stations to pace their output to the bottleneck rate
**So that** excess work-in-progress inventory is avoided between stations

**Acceptance Criteria:**
- Non-bottleneck machines deliberately delay processing to match the identified bottleneck's throughput rate.
- The bottleneck station is identified dynamically at simulation runtime (e.g. highest utilization or longest queue).
- A comparison view shows WIP levels with and without pacing enabled.

**Priority:** Could have (deferred) | **Labels:** `simulation`, `lean`, `stretch-goal`

---

## EPIC 3: Workforce Allocation Optimization

**Epic description:** Optimize operator-to-station assignment based on a skill/routine matrix using linear programming.

**Components:** Optimization

---

### US-301 — Optimized operator-station assignment

**As a** shift supervisor
**I want** an optimized operator-station assignment proposal
**So that** stations are staffed with the most competent available operators

**Acceptance Criteria:**
- Input: skill matrix (0–5), routine matrix (0–5), minimum required skill per station, required headcount per station.
- Objective function maximizes `2×skill + routine` per assignment.
- Output is a table of operator–station pairs.

**Priority:** Must have | **Labels:** `optimization`, `pulp`

---

### US-302 — Infeasible assignment warning

**As a** shift supervisor
**I want** to be warned if no operator meets the minimum skill requirement for a station
**So that** I can plan training or reassignment

**Acceptance Criteria:**
- If no feasible assignment exists for a station, the system flags it explicitly rather than failing silently.

**Priority:** Should have | **Labels:** `optimization`, `pulp`

---

## EPIC 4: Data Persistence & Reporting Layer

**Epic description:** Build the SQLite layer connecting simulation, KPI engine and dashboards, with Streamlit as the primary reporting interface.

**Components:** SQL Layer, Dashboard

---

### US-401 — Simulation writes to SQLite

**As a** developer
**I want** the simulation to write all events to a SQLite database
**So that** results persist across runs and can be queried independently

**Acceptance Criteria:**
- Each simulation run gets a unique `run_id`.
- Tables: `simulation_runs`, `production_events`, `machine_status_log`, `material_stock_log` are populated during the run.
- `simulation_runs` includes a status flag (`RUNNING`, `COMPLETED`, `FAILED`) so downstream consumers only process finalized runs.

**Priority:** Must have| **Labels:** `sql`, `simulation`

---

### US-402 — Interactive Streamlit dashboard

**As a** user
**I want** a Streamlit dashboard that reads from the database and updates after each simulation run
**So that** I don't need to touch code to see results

**Acceptance Criteria:**
- Dashboard loads data via SQL queries against the SQLite file.
- A "Run new simulation" button triggers a fresh run and refresh.
- Simulation input parameters (order pattern, batch size, product mix, machine cycle time, MTBF/MTTR, quality rate) are adjustable through the interface, not hardcoded.

**Priority:** Must have | **Labels:** `dashboard`

---

### US-403 — Power BI screenshots (optional)

**As a** recruiter/interviewer
**I want** a Power BI report connected to the same data model
**So that** the solution also demonstrates familiarity with enterprise BI tooling

**Acceptance Criteria:**
- At minimum, 2–3 Power BI screenshots connected to the SQLite export (e.g. via CSV) are included in the repo/Confluence.
- Content mirrors a subset of the Streamlit dashboard (not a full parallel build).

**Priority:** Could have | **Labels:** `dashboard`, `optional`

---



