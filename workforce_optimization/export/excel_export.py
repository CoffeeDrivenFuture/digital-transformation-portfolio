# -*- coding: utf-8 -*-
"""
excel_export.py
---------------
Jira WO-6: the optimization result as a downloadable .xlsx with two
sheets.

  Assignments : final operator -> station assignment for the shift(s)
  Gaps        : stations left short of required_operators (FR-07 / FR-09)

Only the allocation result goes in the workbook. The recommendation views
(experts, promotion, training) are dashboard-only and are deliberately
kept out of the export -- see the Integration Design page.
"""

import io
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # project root

from optimization.shift_allocation import AllocationResult  # noqa: E402


def _as_result_dict(results) -> dict:
    if isinstance(results, AllocationResult):
        return {results.shift: results}
    return dict(results)


def build_assignments_frame(results) -> pd.DataFrame:
    results = _as_result_dict(results)
    parts = []
    for shift, res in results.items():
        if res.assignments.empty:
            continue
        df = res.assignments.copy()
        df.insert(0, "shift", shift)
        parts.append(df)
    if not parts:
        return pd.DataFrame(columns=["shift", "operator_id", "station", "skill", "routine", "competency"])
    return pd.concat(parts, ignore_index=True)


def build_gaps_frame(results) -> pd.DataFrame:
    results = _as_result_dict(results)
    parts = []
    for shift, res in results.items():
        if res.gaps.empty:
            continue
        df = res.gaps.copy()
        df.insert(0, "shift", shift)
        parts.append(df)
    if not parts:
        return pd.DataFrame(columns=["shift", "station", "required_operators", "assigned", "shortfall"])
    return pd.concat(parts, ignore_index=True)


def build_workbook_bytes(results) -> bytes:
    """Returns the .xlsx file as bytes, ready for a Streamlit download button."""
    assignments = build_assignments_frame(results)
    gaps = build_gaps_frame(results)

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        assignments.to_excel(writer, sheet_name="Assignments", index=False)
        gaps.to_excel(writer, sheet_name="Gaps", index=False)
        for sheet_name, df in (("Assignments", assignments), ("Gaps", gaps)):
            ws = writer.sheets[sheet_name]
            for i, col in enumerate(df.columns, start=1):
                width = max(len(str(col)), *(df[col].astype(str).map(len).tolist() or [0])) + 2
                ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = width
    return buf.getvalue()


if __name__ == "__main__":
    from data_io.loaders import load_from_dir
    from optimization.shift_allocation import allocate_all_shifts

    here = os.path.dirname(os.path.abspath(__file__))
    d = load_from_dir(os.path.join(os.path.dirname(here), "sample_data"))
    results = allocate_all_shifts(d)
    wb = build_workbook_bytes(results)
    print(f"workbook built: {len(wb)} bytes, 2 sheets")
    print("\nAssignments:\n", build_assignments_frame(results).to_string(index=False))
    print("\nGaps:\n", build_gaps_frame(results).to_string(index=False))
