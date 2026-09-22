# Coffee Fleet Maintenance — BPMN 2.0 / Camunda 8 Process Orchestration

A working, tested process orchestration case study built on **Camunda 8 (Zeebe)** — the third piece in a three-part digital transformation portfolio.

This case deliberately demonstrates a **different skill area** from the other two portfolio pieces:

| Case | Core skill |
|---|---|
| Manufacturing Simulation | Discrete-event simulation (SimPy) |
| Workforce Optimization | Mathematical optimization (PuLP / linear programming) |
| **Coffee Fleet Maintenance (this repo)** | **Process orchestration & system integration (BPMN 2.0 / Camunda 8)** |

## What this is

A coffee machine fleet operator monitors machines that report alerts (low stock, low water, malfunctions). This project models the **decision and coordination layer** that handles those alerts — not the physical behavior of the machines themselves. It answers questions like: *is this alert routine or does it need escalation? who handles it? what happens if nobody responds in time?*

It is **not** a diagram sitting in a drawer. It is a deployed, executable process running on a real Camunda 8 engine, wired to a real (mock) REST API through a Python job worker, and verified end-to-end with an automated test script.

## Architecture

![Architecture](architecture_en.svg)

Four independent layers, each with a single responsibility:

1. **BPMN diagram** (`coffee_service.bpmn`) — the static description of the state machine
2. **Zeebe Engine** (Camunda 8 Run) — executes the state machine: tracks instance state, evaluates gateways, tracks timers
3. **Python job worker** (`camunda_worker.py`, via `pyzeebe`) — bridges the engine to real business logic
4. **REST API** (`api_mock/app.py`, Flask) — owns the actual data and business logic

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full breakdown of who talks to whom, on which protocol, and why.

## What the process actually does

![Process timeline](timeline_en.svg)

- An alert comes in as either a **material shortage** or a **machine breakdown** (`exclusiveGateway`)
- Automated steps (stock locking, technician allocation, logging) run as `serviceTask`s handled by the job worker
- Partner and technician notifications fire **in parallel** (`parallelGateway`, correctly paired split/join)
- Physical work (repair, refilling, cleaning) is modeled as `userTask`s, completed by a human via **Tasklist**
- A **non-interrupting boundary timer** on the repair step escalates to a manager after 8 hours without blocking the ongoing repair
- The final "was it resolved?" gateway has an explicit **default flow** — if the human forgot to fill in the form field, the process safely falls back to the "not resolved" branch instead of crashing

## Deliberately out of scope

- **Simulation of machine/queue behavior** — that is the Manufacturing Simulation case's territory
- **Optimization** (order quantities, routing) — that is the Workforce Optimization case's territory
- **AI/LLM integration** — considered and explicitly rejected. The alert type arrives as structured data (an enum, not free text), so a plain `exclusiveGateway` handles the routing exactly as well as an LLM call would, with none of the added complexity, latency, or cost. Real business knowledge and deliberate scope decisions matter more here than adding AI for its own sake.

## Repository structure

```
coffee_service.bpmn      — the process definition (deploy this to Camunda 8)
camunda_worker.py        — pyzeebe job worker (service/send task handlers)
api_mock/
  app.py                 — Flask REST API (mock backend)
  requirements.txt
e2e_test.py               — automated end-to-end test (Camunda 8 REST v2 API)
issue_solved.form         — Tasklist form definition for the "General cleaning" user task
ARCHITECTURE.md           — detailed technical documentation
```

## Running it

1. **Start Camunda 8 Run** locally (gRPC gateway on `:26500`, REST/Tasklist/Operate on `:8080`)
2. **Deploy** `coffee_service.bpmn` (via Camunda Desktop Modeler, or `zbctl`)
3. **Start the REST API**:
   ```bash
   pip install -r api_mock/requirements.txt
   python api_mock/app.py
   ```
4. **Start the job worker**:
   ```bash
   pip install pyzeebe httpx
   python camunda_worker.py
   ```
5. **Run the automated test**:
   ```bash
   pip install httpx
   python e2e_test.py
   ```
   This drives three scenarios end-to-end (material path resolved / material path unresolved / machine breakdown path) purely through the REST v2 API — no manual clicking required — and confirms each instance reaches `COMPLETED`.

Alternatively, start an instance manually from Camunda Modeler or Tasklist with a starting variable such as `{"alert_type": "material"}` or `{"alert_type": "machine_breakdown"}`, and complete the open user tasks by hand in Tasklist (`:8080/tasklist`). Progress can be followed live in Operate (`:8080/operate`).

## Design decisions worth knowing

- **Why a job worker if there's a REST API?** Zeebe cannot call an HTTP endpoint directly from a service task — an external job worker is the only way to bridge the engine to a real backend.
- **Why a default flow on the "issue solved" gateway?** Without it, a missing or malformed `issue_solved` variable would throw a runtime error instead of degrading gracefully to the safer "unresolved" path.
- **Why non-interrupting (not interrupting) on the repair timer?** The goal is an escalation notice, not stopping the technician's work in progress.
- **Why no AI?** See "Deliberately out of scope" above — this was a conscious call, not an oversight.

## Learning context

This case was built while learning BPMN 2.0 and Camunda 8 from scratch — including working through real deployment errors (duplicate blank start events, missing task definition types, unconditioned sequence flows, gRPC vs. REST port confusion, `pyzeebe` API version differences) rather than a idealized first-try build. The debugging trail is part of the value: every fix reflects an actual understanding of *why* Zeebe behaves the way it does, not just a working end state.
