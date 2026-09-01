# -*- coding: utf-8 -*-
"""
store.py
--------
Retention of the most recently accepted upload, per the Confluence
"Assumptions & Constraints": no run history, no versions -- just the last
valid dataset kept as a convenience default so the dashboard has
something to load on the next start.

Implemented as a plain folder of five CSVs under `.cache/` (git-ignored).
A save fully replaces the previous one.
"""

import os
import shutil

import pandas as pd

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".cache")

_FILES = ["operators", "skill", "routine", "stations", "shifts"]


def has_last_valid() -> bool:
    return all(os.path.exists(os.path.join(CACHE_DIR, f"{n}.csv")) for n in _FILES)


def save_last_valid(frames: dict) -> None:
    """frames: {logical_name: DataFrame}. Replaces any previously stored set."""
    if os.path.isdir(CACHE_DIR):
        shutil.rmtree(CACHE_DIR)
    os.makedirs(CACHE_DIR, exist_ok=True)
    for name in _FILES:
        frames[name].to_csv(os.path.join(CACHE_DIR, f"{name}.csv"), index=False)


def load_last_valid_frames() -> dict:
    return {n: pd.read_csv(os.path.join(CACHE_DIR, f"{n}.csv")) for n in _FILES}


def clear_last_valid() -> None:
    if os.path.isdir(CACHE_DIR):
        shutil.rmtree(CACHE_DIR)
