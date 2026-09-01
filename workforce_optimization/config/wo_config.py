# -*- coding: utf-8 -*-
"""
wo_config.py
------------
Central configuration for Workforce Optimization.

Per the Confluence "Assumptions & Constraints" note, configuration is meant
to be adjustable through the interface rather than hardcoded -- so the
values here are *defaults*. The Streamlit UI reads them as starting points
and passes overrides down into the optimization / analysis functions
(competency weights, number of shifts, the "resilience" minimum). Nothing
in the logic layer reaches back into this module for a live value.

The structural pieces (which stations exist, their required level and
headcount) are NOT here -- those come from stations.csv at runtime, since
the whole point of the tool is to try different station setups without
touching code.
"""

# ---------------------------------------------------------------------------
# COMPETENCY SCORING (default, UI-overridable)
# ---------------------------------------------------------------------------
# competency(operator, station) = w_skill * skill + w_routine * routine
# The reference PuLP model used 2 * skill + routine; that stays the default,
# but the dashboard exposes both weights as sliders.
DEFAULT_COMPETENCY_WEIGHTS = {"skill": 2.0, "routine": 1.0}

# ---------------------------------------------------------------------------
# ELIGIBILITY RULE (carried over from the reference implementation)
# ---------------------------------------------------------------------------
# An operator is eligible for a station only if BOTH hold:
#   - skill   >= station's required_level
#   - routine >  0   (never worked there at all -> not eligible, even if
#                     formally trained; conscious decision, see decisions.md)
MIN_ROUTINE_FOR_ELIGIBILITY = 1  # routine must be >= this (i.e. > 0)

# ---------------------------------------------------------------------------
# SHIFT RESILIENCE (FR-07)
# ---------------------------------------------------------------------------
# Target: at least this many eligible operators per station, per shift, so
# no station depends on a single key person. Used by the coverage/gap
# analysis and as the objective of the shift-reorganization model (WO-5).
DEFAULT_MIN_QUALIFIED_PER_STATION = 2

# Default number of shifts the reorganization proposal splits the workforce
# into, when the user has not set it explicitly.
DEFAULT_NUM_SHIFTS = 3

# ---------------------------------------------------------------------------
# INPUT VALIDATION
# ---------------------------------------------------------------------------
SKILL_SCALE_MIN = 0
SKILL_SCALE_MAX = 5

# Expected CSV layout. Station columns in skill.csv / routine.csv are not
# fixed here -- they must match the `station` values in stations.csv, which
# is checked at load time.
CSV_SCHEMA = {
    "operators": {"columns": ["operator_id"]},
    "skill": {"columns": ["operator_id"], "plus_station_columns": True},
    "routine": {"columns": ["operator_id"], "plus_station_columns": True},
    "stations": {"columns": ["station", "required_level", "required_operators"]},
    "shifts": {"columns": ["operator_id", "shift"]},
}

# File name each logical table is expected to arrive as.
CSV_FILENAMES = {
    "operators": "operators.csv",
    "skill": "skill.csv",
    "routine": "routine.csv",
    "stations": "stations.csv",
    "shifts": "shifts.csv",
}

# ---------------------------------------------------------------------------
# PROMOTION / TRAINING RECOMMENDATIONS
# ---------------------------------------------------------------------------
PROMOTION_TOP_N = 5  # FR-10: rank the top N by cumulated skill
