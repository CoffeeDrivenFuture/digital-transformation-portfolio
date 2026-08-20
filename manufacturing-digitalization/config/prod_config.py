# -*- coding: utf-8 -*-
"""
prod_config.py
---------------
Egyetlen, központi hely a gyár konfigurációjára. Célja, hogy se a
szimuláció (production_sim_db.py), se a KPI-motor (kpi_engine.py), se a
majdani Streamlit dashboard NE tartalmazza duplikálva ugyanazokat a
gépparamétereket, útvonalakat, anyagokat — mindenki innen importál.

A fájl két, egyértelműen elkülönített részre oszlik:

  1. STRUKTURÁLIS KONFIGURÁCIÓ
     A gyár "fizikai" felépítése: milyen gépek vannak, milyen útvonalon
     megy át rajtuk egy-egy termék, milyen alapanyagot igényelnek.
     -> Ez NEM Streamlit-widget. Ha ez futásonként változna, az nem
        "mi lenne, ha" szimuláció volna, hanem egy másik gyár.

  2. ALAPÉRTELMEZETT FUTTATÁSI PARAMÉTEREK
     Minden, amit a Jira US-402 explicit felsorol Streamlit-bemenetként:
     "order pattern, batch size, product mix, machine cycle time,
     MTBF/MTTR, quality rate". Itt csak az ALAPÉRTÉKEK vannak megadva —
     a run_simulation() függvény (production_sim_db.py) argumentumként
     fogadja ugyanezeket, és felülírja velük az itteni defaultot, ha a
     Streamlit (vagy bármilyen más hívó) megadja őket.

Fontos: a MACHINE_PARAMS-ban a cycle_time és quality alap esetben is
"futtatási paraméternek" számít a Jira szerint (a felhasználó tudja
állítani a dashboardon) — de mivel gépenként külön kell tudni módosítani
őket, nem egy sima globális default, hanem maga a MACHINE_PARAMS dict
lesz az, amit a Streamlit majd gépenként felülír (lásd a run_simulation
`machine_overrides` paraméterét).
"""

# ---------------------------------------------------------------------------
# 1. STRUKTURÁLIS KONFIGURÁCIÓ — a gyár felépítése, ritkán/soha nem változik
# ---------------------------------------------------------------------------

# Melyik géppel milyen alap MTBF/MTTR/cycle_time/quality tartozik.
# A cycle_time és quality értékét a Streamlit futásonként felülírhatja
# (lásd run_simulation(machine_overrides=...)), de a gépek LISTÁJA
# (Machine0..Machine4) strukturális adat.
MACHINE_PARAMS = {
    "Machine0": {"mtbf": 500, "mttr": 60, "quality": 0.7322999408201399, "cycle_time": 4.57},
    "Machine1": {"mtbf": 500, "mttr": 60, "quality": 0.7617075260435038, "cycle_time": 5.29},
    "Machine2": {"mtbf": 500, "mttr": 60, "quality": 0.8756414891134877, "cycle_time": 4.73},
    "Machine3": {"mtbf": 500, "mttr": 60, "quality": 0.8998779966556945, "cycle_time": 5.03},
    "Machine4": {"mtbf": 500, "mttr": 60, "quality": 0.9470171087907475, "cycle_time": 4.74},
}

# Melyik termék milyen gépsoron megy végig, és melyik gépen milyen
# alapanyagból mennyit igényel. Ez a gyár topológiája -> strukturális.
PRODUCT_PARAMS = {
    "A": {
        "route": ["Machine0", "Machine2", "Machine3"],
        "materials": {"Machine0": {"material1": 1}, "Machine2": {"material2": 2}},
    },
    "B": {
        "route": ["Machine1", "Machine3", "Machine4"],
        "materials": {"Machine1": {"material1": 2}, "Machine4": {"material2": 3}},
    },
}

# Alapanyag-utánpótlási szabályok (min szint, batch méret, gyártási/átállási idő).
# Ez is strukturális: az, hogy "material1"-ből mennyi idő alatt lehet
# utángyártani, a beszállítói/gyártási folyamat tulajdonsága, nem egy
# "mi lenne ha" kérdés.
MATERIAL_PARAMS = {
    "material1": {"min_level": 28, "batch_size": 15, "unit_time": 4, "changeover_time": 60},
    "material2": {"min_level": 36, "batch_size": 30, "unit_time": 6, "changeover_time": 90},
}


# ---------------------------------------------------------------------------
# 2. ALAPÉRTELMEZETT FUTTATÁSI PARAMÉTEREK — ezeket írja majd felül a Streamlit
# ---------------------------------------------------------------------------

DEFAULT_RANDOM_SEED = 42
DEFAULT_SIM_TIME = 5 * 24 * 60  # 5 nap percben
DEFAULT_BATCH_INTERVAL = 12 * 60  # 720 perc
DEFAULT_TOTAL_PIECES_PER_BATCH = 40

# Rendelési minta (order pattern): batch-enként termék-mix.
# A Jira US-201 "configurable batch size, interval, and product mix"
# elvárása ide fut be -- ez a legvalószínűbb dolog, amit a Streamlit
# egy slider-triplettel (batch méret, intervallum, A/B arány) generál
# majd újra, ahelyett hogy ezt a kézzel írt listát használná.
DEFAULT_BATCHES = [
    {"A": 18, "B": 22}, {"A": 30, "B": 10}, {"A": 12, "B": 28},
    {"A": 27, "B": 13}, {"A": 20, "B": 20}, {"A": 17, "B": 23},
    {"A": 17, "B": 23}, {"A": 22, "B": 18}, {"A": 28, "B": 12},
    {"A": 15, "B": 25},
]


def generate_batches(n_batches: int, total_per_batch: int, a_share: float = 0.5, seed: int = None) -> list:
    """
    Segédfüggvény, amivel a Streamlit (vagy bárki) új order pattern-t tud
    generálni ahelyett, hogy a DEFAULT_BATCHES-t hardkódolva használná.

    a_share: az "A" termék hozzávetőleges aránya (0-1 között). A pontos
    darabszám batch-enként kicsit szór a véletlen miatt, hogy realisztikus
    maradjon a minta.
    """
    import random as _random

    rng = _random.Random(seed)
    batches = []
    for _ in range(n_batches):
        a_qty = max(0, min(total_per_batch, round(rng.gauss(total_per_batch * a_share, total_per_batch * 0.1))))
        b_qty = total_per_batch - a_qty
        batches.append({"A": a_qty, "B": b_qty})
    return batches
