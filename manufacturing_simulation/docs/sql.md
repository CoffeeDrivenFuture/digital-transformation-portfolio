# SQL SCHEME (SQLite)

```sql
-- Static master data
CREATE TABLE machines (
    machine_id      TEXT PRIMARY KEY,
    name            TEXT,
    mtbf_target     REAL,
    mttr_target     REAL,
    cycle_time_base REAL
);

CREATE TABLE products (
    product_id      TEXT PRIMARY KEY,
    name            TEXT
);

CREATE TABLE product_routes (
    product_id      TEXT REFERENCES products(product_id),
    sequence_order  INTEGER,
    machine_id      TEXT REFERENCES machines(machine_id),
    PRIMARY KEY (product_id, sequence_order)
);

CREATE TABLE materials (
    material_id       TEXT PRIMARY KEY,
    name              TEXT,
    min_level         INTEGER,
    batch_size        INTEGER,
    unit_time         REAL,
    changeover_time   REAL
);

-- Szimulációs futások
CREATE TABLE simulation_runs (
    run_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at      TEXT,
    sim_duration    INTEGER,
    random_seed     INTEGER,
    notes           TEXT
);

CREATE TABLE production_events (
    event_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          INTEGER REFERENCES simulation_runs(run_id),
    sim_time        REAL,
    machine_id      TEXT REFERENCES machines(machine_id),
    product_id      TEXT REFERENCES products(product_id),
    is_good         INTEGER  -- 0/1
);

CREATE TABLE machine_status_log (
    log_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          INTEGER REFERENCES simulation_runs(run_id),
    sim_time        REAL,
    machine_id      TEXT REFERENCES machines(machine_id),
    status          TEXT   -- 'working' | 'blocked' | 'repair'
);

CREATE TABLE material_stock_log (
    log_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          INTEGER REFERENCES simulation_runs(run_id),
    sim_time        REAL,
    material_id     TEXT REFERENCES materials(material_id),
    stock_level     REAL
);

CREATE TABLE material_recommendations (
    run_id            INTEGER REFERENCES simulation_runs(run_id),
    material_id       TEXT REFERENCES materials(material_id),
    min_stock_level   REAL,
    safety_stock      REAL,
    PRIMARY KEY (run_id, material_id)
);

-- Számított KPI-k
CREATE TABLE kpi_daily (
    run_id          INTEGER REFERENCES simulation_runs(run_id),
    sim_day         INTEGER,
    machine_id      TEXT REFERENCES machines(machine_id),
    availability    REAL,
    performance     REAL,
    quality         REAL,
    oee             REAL,
    mtbf            REAL,
    mttr            REAL,
    PRIMARY KEY (run_id, sim_day, machine_id)
);

-- Erőforrás-optimalizáció
CREATE TABLE operators (
    operator_id     TEXT PRIMARY KEY,
    name            TEXT
);

CREATE TABLE skill_matrix (
    operator_id     TEXT REFERENCES operators(operator_id),
    station_id      TEXT,
    skill_level     INTEGER,   -- 0-5
    routine_level   INTEGER,   -- 0-5
    PRIMARY KEY (operator_id, station_id)
);

CREATE TABLE operator_assignments (
    run_id          INTEGER REFERENCES simulation_runs(run_id),
    operator_id     TEXT REFERENCES operators(operator_id),
    station_id      TEXT,
    competency_score REAL,
    PRIMARY KEY (run_id, operator_id)
);
```
