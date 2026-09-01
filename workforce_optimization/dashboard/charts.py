# -*- coding: utf-8 -*-
"""
charts.py
---------
Plotly figures for the dashboard, kept out of app.py so the page code
stays about layout and flow.

House style (shared with the manufacturing_simulation dashboard):
transparent backgrounds so the chart sits inside Streamlit's dark theme,
a traffic-light status palette, and a 2px gap between adjacent marks. The
skill / coverage grids encode *status* (eligible / short) as fill and put
the exact number in the cell, so they read at a glance instead of like a
spreadsheet.
"""

import plotly.graph_objects as go
from plotly.subplots import make_subplots

OK = "#4CAF50"       # meets target / eligible
WARN = "#FFC107"     # partial / trained but no practice
BAD = "#EF5350"      # short / not eligible
ACCENT = "#2196F3"   # reference lines, single-series bars
INK = "#FAFAFA"

OK_FILL = "rgba(76,175,80,0.30)"
WARN_FILL = "rgba(255,193,7,0.28)"
BAD_FILL = "rgba(239,83,80,0.32)"

# Fixed station colour order (identity encoding, never cycled).
STATION_COLORS = ["#4C78A8", "#F58518", "#B279A2", "#72B7B2",
                  "#9D755D", "#BAB0AC", "#54A24B", "#EECA3B"]

EXPERTS_PER_PANEL = 6


def station_palette(stations: list) -> dict:
    return {s: STATION_COLORS[i % len(STATION_COLORS)] for i, s in enumerate(stations)}


def apply_dark_theme(fig: go.Figure) -> go.Figure:
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font_color=INK,
        title=dict(x=0.01, xanchor="left", font=dict(size=16)),
        margin=dict(l=10, r=10, t=64, b=10),
        legend=dict(bgcolor="rgba(0,0,0,0)", orientation="h", y=-0.15),
        xaxis=dict(gridcolor="rgba(255,255,255,0.08)", zerolinecolor="rgba(255,255,255,0.15)"),
        yaxis=dict(gridcolor="rgba(255,255,255,0.08)", zerolinecolor="rgba(255,255,255,0.15)"),
    )
    return fig


# ---------------------------------------------------------------------------
# SHIFT ALLOCATION (tab 1)
# ---------------------------------------------------------------------------
def station_staffing_bar(stations: list, required: dict, assigned: dict) -> go.Figure:
    """Horizontal bar per station, total length = required headcount:
    a filled segment and, if short, a red gap segment. The 'filled /
    required' count is written at the start of every row."""
    req = [required[s] for s in stations]
    got = [min(assigned.get(s, 0), r) for s, r in zip(stations, req)]
    gap = [r - g for g, r in zip(got, req)]
    fill_colors = [OK if g >= r else WARN for g, r in zip(got, req)]

    fig = go.Figure()
    fig.add_bar(y=stations, x=got, orientation="h", marker_color=fill_colors,
                showlegend=False, hovertemplate="%{y}: %{x} assigned<extra></extra>", name="filled")
    fig.add_bar(y=stations, x=gap, orientation="h", marker_color=BAD_FILL,
                showlegend=False, hovertemplate="%{y}: %{x} short<extra></extra>", name="gap")
    for stn, g, r in zip(stations, got, req):
        fig.add_annotation(x=0, y=stn, text=f"  {g}/{r}", showarrow=False,
                           xanchor="left", font=dict(color=INK, size=13))
    fig.update_layout(
        barmode="stack", title="Station staffing (filled / required)",
        height=120 + 44 * len(stations), bargap=0.45,
        xaxis=dict(title="operators", dtick=1),
        yaxis=dict(autorange="reversed"),
    )
    return apply_dark_theme(fig)


def assignment_competency_bar(assignments) -> go.Figure:
    """Each assigned operator as a bar, length = competency, grouped by
    station, coloured by station."""
    if assignments.empty:
        fig = go.Figure()
        fig.update_layout(title="Assigned operators by competency", height=200)
        return apply_dark_theme(fig)

    df = assignments.sort_values(["station", "competency"], ascending=[False, True])
    pal = station_palette(sorted(assignments["station"].unique()))
    labels = [f"{op}  ({st})" for op, st in zip(df["operator_id"], df["station"])]

    fig = go.Figure(go.Bar(
        y=labels, x=df["competency"], orientation="h",
        marker_color=[pal[s] for s in df["station"]],
        text=[f"skill {s} / routine {r}" for s, r in zip(df["skill"], df["routine"])],
        textposition="auto", textfont_color=INK,
        hovertemplate="%{y}: competency %{x}<extra></extra>",
    ))
    fig.update_layout(title="Assigned operators by competency",
                      height=120 + 36 * len(df), xaxis_title="competency", showlegend=False)
    return apply_dark_theme(fig)


# ---------------------------------------------------------------------------
# COVERAGE HEATMAP (tabs 2 and 3)
# ---------------------------------------------------------------------------
def coverage_heatmap(coverage_df, target: int, title: str) -> go.Figure:
    """shift x station grid; cell fill = resilient (>= target) or not, the
    eligible count is written in each cell."""
    shifts = list(coverage_df.index)
    stations = list(coverage_df.columns)
    counts = coverage_df.values.tolist()
    codes = [[1 if c >= target else 0 for c in row] for row in counts]

    fig = go.Figure(go.Heatmap(
        z=codes, x=stations, y=shifts, xgap=3, ygap=3,
        colorscale=[[0, BAD_FILL], [1, OK_FILL]], showscale=False, zmin=0, zmax=1,
        customdata=counts,
        hovertemplate="%{y} / station %{x}: %{customdata} eligible<extra></extra>",
    ))
    for iy, sh in enumerate(shifts):
        for ix, stn in enumerate(stations):
            fig.add_annotation(x=stn, y=sh, text=str(counts[iy][ix]), showarrow=False,
                               font=dict(size=14, color=INK))
    fig.update_layout(
        title=title, height=150 + 52 * len(shifts),
        xaxis=dict(title="station", showgrid=False),
        yaxis=dict(autorange="reversed", showgrid=False),
    )
    return apply_dark_theme(fig)


# ---------------------------------------------------------------------------
# SKILL MATRIX (tab 3)
# ---------------------------------------------------------------------------
def skill_matrix_heatmap(skill_df, routine_df, levels) -> go.Figure:
    """Operator x station grid. Fill = eligibility status (green eligible /
    amber trained-but-no-practice / red below the required level); the
    number in each cell is the skill value."""
    operators = list(skill_df.index)
    stations = list(skill_df.columns)

    codes, colors = [], {0: BAD_FILL, 1: WARN_FILL, 2: OK_FILL}
    for op in operators:
        row = []
        for stn in stations:
            sk, rt = int(skill_df.loc[op, stn]), int(routine_df.loc[op, stn])
            row.append(0 if sk < levels[stn] else (1 if rt == 0 else 2))
        codes.append(row)

    fig = go.Figure(go.Heatmap(
        z=codes, x=stations, y=operators, xgap=3, ygap=3,
        colorscale=[[0.0, colors[0]], [0.5, colors[1]], [1.0, colors[2]]],
        zmin=0, zmax=2, showscale=False,
        customdata=skill_df.values,
        hovertemplate="%{y} / station %{x}: skill %{customdata}<extra></extra>",
    ))
    for op in operators:
        for stn in stations:
            fig.add_annotation(x=stn, y=op, text=str(int(skill_df.loc[op, stn])),
                               showarrow=False, font=dict(size=12, color=INK))
    for name, color in [("eligible", OK), ("trained, no practice", WARN), ("below required level", BAD)]:
        fig.add_trace(go.Scatter(x=[None], y=[None], mode="markers",
                                 marker=dict(size=11, color=color, symbol="square"), name=name))
    fig.update_layout(
        title="Skill matrix", height=170 + 32 * len(operators),
        xaxis=dict(title="station", showgrid=False),
        yaxis=dict(autorange="reversed", showgrid=False),
        showlegend=True,
    )
    return apply_dark_theme(fig)


def workforce_coverage_bar(coverage, target: int) -> go.Figure:
    stations = list(coverage.index)
    vals = [int(v) for v in coverage.values]
    colors = [OK if v >= target else BAD for v in vals]
    fig = go.Figure(go.Bar(
        x=stations, y=vals, marker_color=colors, text=vals, textposition="outside",
        textfont_color=INK, hovertemplate="station %{x}: %{y} eligible<extra></extra>",
    ))
    fig.add_hline(y=target, line_dash="dash", line_color=ACCENT,
                  annotation_text=f"target {target}", annotation_position="top left")
    fig.update_layout(title="Eligible operators per station (whole workforce)",
                      height=320, xaxis_title="station", yaxis=dict(title="operators", dtick=1))
    return apply_dark_theme(fig)


# ---------------------------------------------------------------------------
# REORGANIZATION (tab 2)
# ---------------------------------------------------------------------------
def shift_headcount_bar(headcount, reference: int) -> go.Figure:
    shifts = list(headcount.index)
    vals = [int(v) for v in headcount.values]
    fig = go.Figure(go.Bar(
        x=shifts, y=vals, marker_color=ACCENT, text=vals, textposition="outside",
        textfont_color=INK, hovertemplate="%{x}: %{y} operators<extra></extra>",
    ))
    if reference:
        fig.add_hline(y=reference, line_dash="dash", line_color=WARN,
                      annotation_text=f"headcount reference {reference}",
                      annotation_position="top left")
    fig.update_layout(title="Proposed headcount per shift", height=320,
                      xaxis_title="shift", yaxis=dict(title="operators", dtick=1))
    return apply_dark_theme(fig)


# ---------------------------------------------------------------------------
# RECOMMENDATIONS (tab 4)
# ---------------------------------------------------------------------------
def promotion_bar(promo_df) -> go.Figure:
    """Top promotion candidates, bar length = cumulated skill, cumulated
    routine shown as the label."""
    df = promo_df.iloc[::-1]  # rank 1 at the top
    fig = go.Figure(go.Bar(
        y=df["operator_id"], x=df["cumulated_skill"], orientation="h", marker_color=ACCENT,
        text=[f"skill {s}  /  routine {r}" for s, r in zip(df["cumulated_skill"], df["cumulated_routine"])],
        textposition="auto", textfont_color=INK,
        hovertemplate="%{y}: cumulated skill %{x}<extra></extra>",
    ))
    fig.update_layout(title="Promotion candidates (cumulated skill)", height=110 + 46 * len(df),
                      xaxis_title="cumulated skill across all stations", showlegend=False)
    return apply_dark_theme(fig)


def experts_figure(experts: dict) -> go.Figure:
    """One row of small horizontal bar panels, one per station, top
    operators by competency. A red panel means fewer experts than the
    resilience target."""
    stations = list(experts.keys())
    fig = make_subplots(rows=1, cols=len(stations),
                        subplot_titles=[f"Station {s}" for s in stations],
                        horizontal_spacing=0.09)
    shown = []
    for col, station in enumerate(stations, start=1):
        full = experts[station]
        df = full.head(EXPERTS_PER_PANEL).iloc[::-1]
        shown.append(len(df))
        spof = full.attrs.get("single_point_of_failure", False)
        fig.add_trace(go.Bar(
            y=df["operator_id"], x=df["competency"], orientation="h",
            marker_color=BAD if spof else ACCENT,
            text=df["competency"], textposition="auto", textfont_color=INK,
            hovertemplate="%{y}: competency %{x}<extra></extra>", showlegend=False,
        ), row=1, col=col)
    fig.update_layout(title="Experts per station (red = single point of failure)",
                      height=150 + 34 * max(shown, default=1), bargap=0.35)
    return apply_dark_theme(fig)
