from core.data import process_file, process_file_content, merge_dataframes_on_time
from core.utils import get_time_filtered_df, y_axis_label
from core.analysis import (
    compute_total_thrust,
    compute_mass_flow_from_tank_weights,
    compute_performance_series,
    compute_venturi_mass_flow_series_kg_s,
    get_burn_window,
    get_burn_window_from_loadcell_spike,
    get_burn_window_from_weight,
    recompute_isp_cstar_with_mdot_total_series,
)

from dash import html, dcc, callback, Input, Output, State, ctx, no_update
import base64
import io
import re
import unicodedata
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import plotly.io as pio
import dash_bootstrap_components as dbc
import random

# Conversions used to turn tank-weight slope (lbf/s) into kg/s for performance equations.
LBM_TO_KG = 0.453592
G0_FT_S2 = 32.174

# -------------- FILE PROCESSING (default dataset) -----------------
DEFAULT_FILE = "data/1047_pt.csv"
df_default, TIME_COL_default, T_MIN_default, T_MAX_default, X_COL_default = process_file(DEFAULT_FILE)


def _parse_store(store_data):
    """Return (df, T_MIN, T_MAX, X_COL, TIME_COL) from store, or None to use defaults."""
    if not store_data or "df_json" not in store_data:
        return None
    try:
        # orient='split' is faster and more compact; fallback for older stored format
        js = store_data["df_json"]
        try:
            df = pd.read_json(io.StringIO(js) if isinstance(js, str) else js, orient="split")
        except (ValueError, TypeError):
            df = pd.read_json(io.StringIO(js) if isinstance(js, str) else js)
        return (
            df,
            store_data["T_MIN"],
            store_data["T_MAX"],
            store_data["X_COL"],
            store_data["TIME_COL"],
        )
    except Exception:
        return None


def _get_dataset(store_data):
    """Return (df, T_MIN, T_MAX, X_COL, TIME_COL); use defaults if store empty."""
    parsed = _parse_store(store_data)
    if parsed is not None:
        return parsed
    return df_default, T_MIN_default, T_MAX_default, X_COL_default, TIME_COL_default


def _slider_marks(t_min, t_max, step=None):
    """Build marks dict for time range slider: ticks at sensible intervals from t_min to t_max."""
    t_min, t_max = float(t_min), float(t_max)
    span = t_max - t_min
    if span <= 0:
        return {t_min: {"label": str(int(t_min)), "style": {"color": "#adb5bd"}}}
    # Adaptive step: aim for ~6–12 ticks; use nice steps (1, 2, 5, 10, 20, ...)
    if step is None:
        if span <= 2:
            step = 0.5
        elif span <= 10:
            step = 1 if span <= 5 else 2
        elif span <= 30:
            step = 5
        elif span <= 60:
            step = 10
        elif span <= 120:
            step = 20
        else:
            step = max(10, int(span / 10))
    ticks = list(np.arange(t_min, t_max + 0.5 * min(step, 1), step))
    if not ticks or ticks[-1] < t_max - 0.01:
        ticks.append(t_max)
    ticks = sorted(set([t_min] + ticks + [t_max]))
    # Use label + style so ticks are visible on dark theme (CYBORG)
    def label(t):
        return str(int(t)) if abs(t - round(t)) < 0.01 else f"{t:.1f}"
    return {
        float(t): {"label": label(t), "style": {"color": "#adb5bd"}}
        for t in ticks
    }

# Initial options from default dataset (updated from store when user uploads)
data_cols_default = [c for c in df_default.columns if c not in [TIME_COL_default, "seconds"]]
palette = px.colors.qualitative.Plotly
random.shuffle(palette)
COLOR_MAP_DEFAULT = {
    col: palette[i % len(palette)]
    for i, col in enumerate(data_cols_default)
}

# Distinct colors for performance analysis plot metrics (order: Total thrust, Isp, Cf, C*)
ANALYSIS_METRIC_COLORS = [
    "#2ca02c",  # green
    "#1f77b4",  # blue
    "#ff7f0e",  # orange
    "#d62728",  # red
]

# =========== GUI ================
# ----------- CONTROLS ------------------
data_channels = dbc.Card(
    [
        dbc.CardHeader(html.H5("Channels", className="mb-0")),
        dbc.CardBody(
            [
                html.P("Select channels to be plotted", className="small text-muted mb-2"),
                dbc.Button("Clear channels", id="clear-channels-button", size="sm", className="mb-2"),
                html.Div(
                    dcc.Checklist(
                        options=[c for c in df_default.columns if c not in [TIME_COL_default, "seconds"]],
                        value=[],
                        id="data-checklist",
                        labelStyle={"color": "white"},
                    ),
                    style={
                        "maxHeight": "500px",
                        "overflowY": "auto",
                    },
                ),
            ]
        ),
    ],
    className="mb-3",
)

BURN_TIME_TIMESERIES_VALUE = "Burn time (timeseries)"

analysis_controls = dbc.Accordion([
    dbc.AccordionItem([
        dcc.Checklist(
            options=[
                {"label": "Regression", "value": "Regression"},
                {"label": "Show Burn Time", "value": BURN_TIME_TIMESERIES_VALUE},
            ],
            value=[],
            id="analysis-checklist",
            labelStyle={"color": "white"},
        ),
    ], title=html.Span("Analysis", style={"color": "white"}))
], className="accordion-dark")

timeseries_side_tabs = dbc.Card(
    dbc.CardBody(
        dbc.Tabs(
            [
                dbc.Tab(data_channels, label="Channels"),
                dbc.Tab(analysis_controls, label="Analysis"),
            ]
        )
    ),
    className="mb-3",
)


time_controls = dbc.Row([
    dbc.Row([
        html.Label(
            "Time Controls",
            className="form-label fw-bold mb-0",
            style={"color": "white", "textAlign": "center", "width": "100%"},
        )
    ], className="w-100"),
    dbc.Row([
        dbc.Col(
            dcc.RangeSlider(
                min=0,
                max=T_MAX_default,
                step=5,
                value=[0, T_MAX_default],
            id="time-range-slider",
            marks={},
        ),
            width=12,
        ),
    ], align="center"),
    dbc.Row([
        dbc.Col(
            html.Div(
                dbc.Button("\tReset\t", id="reset-button"),
                style={"textAlign": "left"},
            ),
            width="auto",
        ),
    ], className="mt-3"),
], align="center")

# Data analysis section: initial options (updated from store when user uploads)
_data_options_default = [c for c in df_default.columns if c not in [TIME_COL_default, "seconds"]]

# Analysis container: Inputs | Venturi | Plot
analysis_tabs_container = dbc.Card(
    [
        dbc.CardHeader(html.H5("Data analysis", className="mb-0")),
        dbc.CardBody(
            dbc.Tabs(
                [
                    dbc.Tab(
                        label="Inputs",
                        children=[
                            html.P("Enter values and select channels", className="small text-muted mb-2"),
                            html.P("Data must be in: thrust lbf, pressure psi, weights lbf, A* m². Pressure is converted to Pa for calculations.", className="small text-muted mb-2"),
                            dbc.Label("Throat Area (m²)", className="fw-bold"),
                            dcc.Input(
                                id="input-throat-area",
                                type="number",
                                placeholder="e.g. 0.001",
                                min=0,
                                step=1e-6,
                                style={
                                    "width": "100%",
                                    "marginBottom": "10px",
                                    "backgroundColor": "#2b3e50",
                                    "color": "#fff",
                                    "border": "1px solid #4a6fa5",
                                },
                            ),
                            dbc.Label("Thrust channels (lbf) — multi-select", className="fw-bold mt-2"),
                            dcc.Dropdown(
                                id="thrust-channels-select",
                                options=[{"label": c, "value": c} for c in _data_options_default],
                                value=[],
                                multi=True,
                                placeholder="Select thrust channels",
                                className="analysis-channel-dropdown",
                                style={
                                    "marginBottom": "10px",
                                    "backgroundColor": "#2b3e50",
                                },
                            ),
                            dbc.Label("Chamber pressure channel (psi)", className="fw-bold mt-2"),
                            dcc.Dropdown(
                                id="chamber-pressure-select",
                                options=[{"label": c, "value": c} for c in _data_options_default],
                                value=None,
                                placeholder="Select chamber pressure",
                                className="analysis-channel-dropdown",
                                style={
                                    "marginBottom": "10px",
                                    "backgroundColor": "#2b3e50",
                                },
                            ),
                            dbc.Label("Fuel tank weight channel (lbf)", className="fw-bold mt-2"),
                            dcc.Dropdown(
                                id="fuel-weight-select",
                                options=[{"label": c, "value": c} for c in _data_options_default],
                                value=None,
                                placeholder="Select fuel tank weight",
                                className="analysis-channel-dropdown",
                                style={
                                    "marginBottom": "10px",
                                    "backgroundColor": "#2b3e50",
                                },
                            ),
                            dbc.Label("Oxidizer tank weight channel (lbf)", className="fw-bold mt-2"),
                            dcc.Dropdown(
                                id="ox-weight-select",
                                options=[{"label": c, "value": c} for c in _data_options_default],
                                value=None,
                                placeholder="Select oxidizer tank weight",
                                className="analysis-channel-dropdown",
                                style={
                                    "marginBottom": "10px",
                                    "backgroundColor": "#2b3e50",
                                },
                            ),
                            html.P(
                                "Fuel/ox flow windows for tank-weight slopes are detected automatically from the selected weight columns.",
                                className="small text-muted",
                            ),
                            html.Div(dbc.Button("Calculate", id="analysis-calculate-button", color="primary", className="mt-3 w-100"), className="d-grid"),
                        ],
                    ),
                    dbc.Tab(
                        label="Venturi",
                        children=[
                            html.P(
                                "Incompressible venturi: ṁ = (C_d A) √(2 ΔP ρ / (1−β⁴)), with ΔP = |P_inlet − P_throat| (psi). "
                                "Enter C_d A (m²) and β = d₂/D₁ for each line. Set fuel and oxidizer ρ (kg/m³). "
                                "When finished, use Calculate on the Inputs tab.",
                                className="small text-muted mb-2",
                            ),
                            dcc.Checklist(
                                id="venturi-use-for-performance-checklist",
                                options=[{"label": "Use venturi ṁ for Isp / C*", "value": "use"}],
                                value=[],
                                labelStyle={"color": "white"},
                                className="mb-2",
                            ),
                            dbc.Label("Fuel density ρ (kg/m³)", className="fw-bold mt-2"),
                            dcc.Input(
                                id="venturi-fuel-rho-constant",
                                type="number",
                                placeholder="e.g. 820",
                                min=0,
                                step=0.1,
                                style={"width": "100%", "marginBottom": "10px"},
                            ),
                            dbc.Label("Oxidizer density ρ (kg/m³)", className="fw-bold mt-2"),
                            dcc.Input(
                                id="venturi-ox-rho-constant",
                                type="number",
                                placeholder="e.g. 1140",
                                min=0,
                                step=0.1,
                                style={"width": "100%", "marginBottom": "12px"},
                            ),
                            dbc.Label("Fuel venturi", className="fw-bold mt-2"),
                            dbc.Row([
                                dbc.Col([
                                    dbc.Label("inlet", className="small text-muted mb-1"),
                                    dcc.Dropdown(
                                        id="venturi-fuel-inlet-select",
                                        options=[],
                                        value=None,
                                        placeholder="inlet",
                                        className="analysis-channel-dropdown",
                                        style={"backgroundColor": "#2b3e50"},
                                    ),
                                ], width=6),
                                dbc.Col([
                                    dbc.Label("throat", className="small text-muted mb-1"),
                                    dcc.Dropdown(
                                        id="venturi-fuel-throat-select",
                                        options=[],
                                        value=None,
                                        placeholder="throat",
                                        className="analysis-channel-dropdown",
                                        style={"backgroundColor": "#2b3e50"},
                                    ),
                                ], width=6),
                            ], className="g-2 mb-2"),
                            dbc.Row([
                                dbc.Col([
                                    dbc.Label("C_d A (m²)", className="small"),
                                    dcc.Input(
                                        id="venturi-fuel-cda",
                                        type="number",
                                        placeholder="C_d A",
                                        min=0,
                                        step=1e-8,
                                        style={"width": "100%"},
                                    ),
                                ], width=6),
                                dbc.Col([
                                    dbc.Label("β", className="small"),
                                    dcc.Input(
                                        id="venturi-fuel-beta",
                                        type="number",
                                        placeholder="d₂/D₁",
                                        min=0,
                                        max=0.999,
                                        step=0.001,
                                        style={"width": "100%"},
                                    ),
                                ], width=6),
                            ], className="g-2 mb-2"),
                            dbc.Label("Ox venturi", className="fw-bold mt-2"),
                            dbc.Row([
                                dbc.Col([
                                    dbc.Label("inlet", className="small text-muted mb-1"),
                                    dcc.Dropdown(
                                        id="venturi-ox-inlet-select",
                                        options=[],
                                        value=None,
                                        placeholder="inlet",
                                        className="analysis-channel-dropdown",
                                        style={"backgroundColor": "#2b3e50"},
                                    ),
                                ], width=6),
                                dbc.Col([
                                    dbc.Label("throat", className="small text-muted mb-1"),
                                    dcc.Dropdown(
                                        id="venturi-ox-throat-select",
                                        options=[],
                                        value=None,
                                        placeholder="throat",
                                        className="analysis-channel-dropdown",
                                        style={"backgroundColor": "#2b3e50"},
                                    ),
                                ], width=6),
                            ], className="g-2 mb-2"),
                            dbc.Row([
                                dbc.Col([
                                    dbc.Label("C_d A (m²)", className="small"),
                                    dcc.Input(
                                        id="venturi-ox-cda",
                                        type="number",
                                        placeholder="C_d A",
                                        min=0,
                                        step=1e-8,
                                        style={"width": "100%"},
                                    ),
                                ], width=6),
                                dbc.Col([
                                    dbc.Label("β", className="small"),
                                    dcc.Input(
                                        id="venturi-ox-beta",
                                        type="number",
                                        placeholder="d₂/D₁",
                                        min=0,
                                        max=0.999,
                                        step=0.001,
                                        style={"width": "100%"},
                                    ),
                                ], width=6),
                            ], className="g-2 mb-2"),
                        ],
                    ),
                    dbc.Tab(
                        label="Plot",
                        children=[
                            dbc.Label("Select metrics to graph (values vs time)", className="fw-bold"),
                            dcc.Checklist(
                                id="analysis-metrics-checklist",
                                options=[
                                    {"label": "Total thrust (lbf)", "value": "Total thrust (lbf)"},
                                    {"label": "Isp (s)", "value": "Isp (s)"},
                                    {"label": "Cf", "value": "Cf"},
                                    {"label": "C* (m/s)", "value": "C* (m/s)"},
                                    {"label": "Venturi fuel mdot (kg/s)", "value": "Venturi fuel mdot (kg/s)"},
                                    {"label": "Venturi ox mdot (kg/s)", "value": "Venturi ox mdot (kg/s)"},
                                    {"label": "Burn time", "value": "Burn time"},
                                ],
                                value=[],
                                style={"marginTop": "8px"},
                                labelStyle={"color": "white"},
                            ),
                        ],
                    ),
                ],
            ),
        ),
    ],
    className="mb-3",
)



# Initial store data (default file so app works before any upload)
def _initial_store():
    data_options = [c for c in df_default.columns if c not in [TIME_COL_default, "seconds", X_COL_default]]
    return {
        "df_json": df_default.to_json(orient="split", date_format="iso"),
        "T_MIN": T_MIN_default,
        "T_MAX": T_MAX_default,
        "X_COL": X_COL_default,
        "TIME_COL": TIME_COL_default,
        "filenames": [DEFAULT_FILE],
        "data_options": data_options,
    }


# ------------------ LAYOUT -------------------------------
# Main layout constrained by theme.css (assets/theme.css)
layout = dbc.Container([
    html.H1(
        'Data Analysis Dashboard',
        style={"textAlign": "center", "marginBottom": "30px"}
    ),

    # File upload at top (multiple files: e.g. pressure + load cell)
    dbc.Card([
        html.H5("Upload data files", className="mb-2"),
        html.P("Upload one or more CSV files (e.g. pressure and load cell). They will be merged on time.", className="text-muted small mb-2"),
        dcc.Upload(
            id="upload-data",
            children=html.Div(["Drag and drop or click to select files"]),
            style={
                "width": "100%",
                "minHeight": "60px",
                "lineHeight": "60px",
                "borderWidth": "1px",
                "borderStyle": "dashed",
                "borderRadius": "8px",
                "textAlign": "center",
                "cursor": "pointer",
            },
            multiple=True,
        ),
        html.Div(id="upload-filenames", className="mt-2", style={"fontSize": "1.1rem", "fontWeight": "600"}),
    ], body=True, className="mb-4"),

    dcc.Store(id="dataset-store", data=_initial_store()),
    dcc.Store(id="filtered-df-store"),  # time-filtered df so graph callback doesn't re-parse full data on checklist change
    dcc.Store(id="user-has-uploaded", data=False),  # True after first successful upload so checklist shows real channels
    dcc.Store(id="analysis-perf-store"),  # cached performance series; graph filters by slider without recomputing
    dcc.Store(id="data-graph-figure-store"),  # current figure for save
    dcc.Store(id="analysis-graph-figure-store"),  # current figure for save
    dcc.Download(id="download-data-graph"),
    dcc.Download(id="download-analysis-graph"),

    # ROW 1: graph + channels
    dbc.Row([
        # COL 1
        dbc.Col([
            html.H5('Timeseries'),
            html.Div(id="timeseries-burn-time-message", className="mb-2"),
            dcc.Graph(
                id="data-graph",
                style={'width': '100%', 'height': '600px'}
            ),
            dbc.Row([
                dbc.Col(dbc.Button("Save", id="data-graph-save-btn", color="primary"), width="auto", className="ms-auto"),
            ], className="mb-2"),
            dbc.Modal(
                [
                    dbc.ModalHeader(dbc.ModalTitle("Save timeseries graph")),
                    dbc.ModalBody([
                        dbc.Label("Title", html_for="data-graph-save-title"),
                        dbc.Input(id="data-graph-save-title", placeholder="Graph title (optional; keeps current title if empty)", type="text", className="mb-2"),
                        dbc.Label("File name", html_for="data-graph-save-filename"),
                        dbc.Input(id="data-graph-save-filename", placeholder="e.g. my_timeseries_plot", type="text", className="mb-2"),
                        dbc.Label("Format", html_for="data-graph-save-format"),
                        dcc.Dropdown(
                            id="data-graph-save-format",
                            options=[
                                {"label": "PNG", "value": "png"},
                                {"label": "JPEG", "value": "jpeg"},
                                {"label": "WebP", "value": "webp"},
                                {"label": "SVG", "value": "svg"},
                            ],
                            value="png",
                            clearable=False,
                            className="mb-2",
                        ),
                    ]),
                    dbc.ModalFooter([
                        dbc.Button("Cancel", id="data-graph-save-cancel", color="secondary", className="me-2"),
                        dbc.Button("Download", id="data-graph-save-download", color="primary"),
                    ]),
                ],
                id="data-graph-save-modal",
                is_open=False,
            ),
        ], width=9),
        # COL 2
        dbc.Col([
            timeseries_side_tabs
        ], width=3),
    ]),

    # ROW 2: time controls + analysis
    dbc.Row([
        # COL 1: all time controls
        dbc.Col([
            time_controls
        ], width=12),
    ]),

    # Data analysis section: (1) graph  (2) container with inputs  (3) multi-select what to plot
    html.Hr(style={"marginTop": "24px", "marginBottom": "16px"}),
    html.H4("Performance analysis", style={"marginBottom": "12px"}),
    dbc.Row([
        dbc.Col([
            dbc.Row([
                dbc.Col([
                    html.Div([
                        html.Span("Fuel tank slope (lbf/s): ", className="small"),
                        html.Span(id="analysis-mdot-fuel-display", children="—"),
                    ], className="p-2 border rounded", style={"backgroundColor": "#2b3e50", "color": "white"}),
                ], width="auto"),
                dbc.Col([
                    html.Div([
                        html.Span("Ox tank slope (lbf/s): ", className="small"),
                        html.Span(id="analysis-mdot-ox-display", children="—"),
                    ], className="p-2 border rounded", style={"backgroundColor": "#2b3e50", "color": "white"}),
                ], width="auto"),
                dbc.Col([
                    html.Div([
                        html.Span("Detected burn time (s): ", className="small"),
                        html.Span(id="analysis-burn-time-display", children="—"),
                    ], className="p-2 border rounded", style={"backgroundColor": "#2b3e50", "color": "white"}),
                ], width="auto"),
                dbc.Col([
                    html.Div([
                        html.Span("Average total thrust, burn (lbf): ", className="small"),
                        html.Span(id="analysis-avg-thrust-burn-display", children="—"),
                    ], className="p-2 border rounded", style={"backgroundColor": "#2b3e50", "color": "white"}),
                ], width="auto"),
                dbc.Col([
                    html.Div([
                        html.Span("Average chamber pressure, burn (psi): ", className="small"),
                        html.Span(id="analysis-avg-chamber-p-burn-display", children="—"),
                    ], className="p-2 border rounded", style={"backgroundColor": "#2b3e50", "color": "white"}),
                ], width="auto"),
                dbc.Col([
                    html.Div([
                        html.Span("Average ox mass flow (kg/s): ", className="small"),
                        html.Span(id="analysis-ox-flow-time-display", children="—"),
                    ], className="p-2 border rounded", style={"backgroundColor": "#2b3e50", "color": "white"}),
                ], width="auto"),
                dbc.Col([
                    html.Div([
                        html.Span("Average fuel mass flow (kg/s): ", className="small"),
                        html.Span(id="analysis-fuel-flow-time-display", children="—"),
                    ], className="p-2 border rounded", style={"backgroundColor": "#2b3e50", "color": "white"}),
                ], width="auto"),
            ], className="g-2 mb-2"),
            dcc.Graph(
                id="analysis-graph",
                style={"width": "100%", "minHeight": "540px", "height": "540px"},
            ),
            dbc.Row([
                dbc.Col(dbc.Button("Save", id="analysis-graph-save-btn", color="primary"), width="auto", className="ms-auto"),
            ], className="mb-2"),
            dbc.Modal(
                [
                    dbc.ModalHeader(dbc.ModalTitle("Save performance analysis graph")),
                    dbc.ModalBody([
                        dbc.Label("Title", html_for="analysis-graph-save-title"),
                        dbc.Input(id="analysis-graph-save-title", placeholder="Graph title (optional; keeps current title if empty)", type="text", className="mb-2"),
                        dbc.Label("File name", html_for="analysis-graph-save-filename"),
                        dbc.Input(id="analysis-graph-save-filename", placeholder="e.g. my_analysis_plot", type="text", className="mb-2"),
                        dbc.Label("Format", html_for="analysis-graph-save-format"),
                        dcc.Dropdown(
                            id="analysis-graph-save-format",
                            options=[
                                {"label": "PNG", "value": "png"},
                                {"label": "JPEG", "value": "jpeg"},
                                {"label": "WebP", "value": "webp"},
                                {"label": "SVG", "value": "svg"},
                            ],
                            value="png",
                            clearable=False,
                            className="mb-2",
                        ),
                    ]),
                    dbc.ModalFooter([
                        dbc.Button("Cancel", id="analysis-graph-save-cancel", color="secondary", className="me-2"),
                        dbc.Button("Download", id="analysis-graph-save-download", color="primary"),
                    ]),
                ],
                id="analysis-graph-save-modal",
                is_open=False,
            ),
            dbc.Row([
                dbc.Col([
                    html.Label("Analysis time range (s)", className="form-label fw-bold mb-0 text-center", style={"color": "white", "textAlign": "center", "width": "100%"}),
                    dcc.RangeSlider(
                        id="analysis-time-range-slider",
                        min=0,
                        max=T_MAX_default,
                        step=5,
                        value=[0, T_MAX_default],
                        marks={},
                    ),
                ], width=12),
            ], align="center", className="mt-2 g-2"),
            dbc.Row([
                dbc.Col(
                    html.Div(
                        dbc.Button("Reset", id="analysis-reset-button"),
                        style={"textAlign": "left"},
                    ),
                    width="auto",
                ),
            ], className="mt-3"),
        ], width=9, style={"minHeight": "580px"}),
        dbc.Col([
            analysis_tabs_container,
        ], width=3),
    ], style={"alignItems": "stretch"}),
], fluid=True, className="dashboard-theme-container")


# ============ INTERACTIVITY (CALLBACKS & FUNCTIONS) ==============
# Upload: process files, merge on time, update store; show filenames; set user-has-uploaded
@callback(
    Output("dataset-store", "data"),
    Output("upload-filenames", "children"),
    Output("user-has-uploaded", "data"),
    Input("upload-data", "contents"),
    State("upload-data", "filename"),
    prevent_initial_call=True,
)
def parse_upload(list_of_contents, list_of_filenames):
    if not list_of_contents or not list_of_filenames:
        return no_update, html.Span("No files uploaded."), no_update
    # Support single file or list (dcc.Upload can send one or many)
    if not isinstance(list_of_contents, list):
        list_of_contents = [list_of_contents]
    if not isinstance(list_of_filenames, list):
        list_of_filenames = [list_of_filenames]
    list_of_tuples = []
    first_error = None
    for content, name in zip(list_of_contents, list_of_filenames):
        if content is None:
            first_error = first_error or "File content was empty."
            continue
        try:
            result = process_file_content(content, name)
            list_of_tuples.append(result)
        except Exception as e:
            first_error = first_error or str(e)
            continue
    if not list_of_tuples:
        msg = f"Could not parse any file. {first_error}" if first_error else "Could not parse any file."
        return no_update, html.Span(msg, className="text-danger"), no_update
    merged, X_COL, _t_min, _t_max = merge_dataframes_on_time(list_of_tuples)
    T_MIN = float(merged[X_COL].min())
    T_MAX = float(merged[X_COL].max())
    TIME_COL = list_of_tuples[0][1]
    data_options = [c for c in merged.columns if c not in [X_COL, "seconds"]]
    store_data = {
        "df_json": merged.to_json(orient="split", date_format="iso"),
        "T_MIN": T_MIN,
        "T_MAX": T_MAX,
        "X_COL": X_COL,
        "TIME_COL": TIME_COL,
        "filenames": list_of_filenames,
        "data_options": data_options,
    }
    names_text = ", ".join(list_of_filenames)
    return store_data, html.Span(f"Loaded: {names_text}"), True


@callback(
    Output("data-checklist", "value"),
    Input("clear-channels-button", "n_clicks"),
    prevent_initial_call=True,
)
def clear_channels(n_clicks):
    """Uncheck all channels and reset the timeseries graph."""
    return []


# Pre-compute time-filtered df so the graph callback only parses this (smaller) data when checklist changes.
MAX_POINTS_DISPLAY = 2500  # downsample for faster Plotly rendering


@callback(
    Output("filtered-df-store", "data"),
    Input("dataset-store", "data"),
    Input("time-range-slider", "value"),
)
def update_filtered_store(store_data, time_range):
    df, T_MIN, T_MAX, X_COL, TIME_COL = _get_dataset(store_data)
    if time_range is not None and len(time_range) == 2:
        t_start, t_end = time_range
    else:
        t_start, t_end = 0, T_MAX
    df_filtered = df[(df[X_COL] >= t_start) & (df[X_COL] <= t_end)]
    return {
        "df_json": df_filtered.to_json(orient="split", date_format="iso"),
        "X_COL": X_COL,
    }


# Single callback: options + time controls (avoids duplicate outputs; uses ctx to distinguish trigger).
@callback(
    Output("data-checklist", "options"),
    Output("thrust-channels-select", "options"),
    Output("chamber-pressure-select", "options"),
    Output("fuel-weight-select", "options"),
    Output("ox-weight-select", "options"),
    Output("time-range-slider", "min"),
    Output("time-range-slider", "max"),
    Output("time-range-slider", "marks"),
    Output("time-range-slider", "value"),
    Output("analysis-time-range-slider", "min"),
    Output("analysis-time-range-slider", "max"),
    Output("analysis-time-range-slider", "marks"),
    Output("analysis-time-range-slider", "value"),
    Input("dataset-store", "data"),
    Input("user-has-uploaded", "data"),
    Input("reset-button", "n_clicks"),
    Input("time-range-slider", "value"),
)
def update_options_and_time_controls(store_data, user_has_uploaded, n_clicks, time_range):
    trigger = ctx.triggered_id
    # When only the time slider moved, avoid parsing full dataset (use cached data_options and T_MAX)
    if trigger == "time-range-slider" and store_data:
        T_MAX = store_data.get("T_MAX", T_MAX_default)
        data_options = store_data.get("data_options", [])
        opts = [{"label": c, "value": c} for c in data_options] if user_has_uploaded else []
        t_start, t_end = (time_range if time_range and len(time_range) == 2 else (0, T_MAX))
        return (
            data_options,
            opts,
            opts,
            opts,
            opts,
            0,
            T_MAX,
            {},
            [t_start, t_end],
            no_update,
            no_update,
            no_update,
            no_update,
        )
    df, T_MIN, T_MAX, X_COL, TIME_COL = _get_dataset(store_data)
    if not user_has_uploaded:
        data_options = []
        opts = []
    else:
        data_options = [c for c in df.columns if c not in [TIME_COL, "seconds"]]
        opts = [{"label": c, "value": c} for c in data_options]

    if trigger == "dataset-store" or trigger is None or trigger == "user-has-uploaded":
        # New dataset or initial load: update options and reset time range (data_options/opts already set above)
        return (
            data_options,
            opts,
            opts,
            opts,
            opts,
            0,
            T_MAX,
            {},
            [0, T_MAX],
            0,
            T_MAX,
            {},
            [0, T_MAX],
        )

    # Time control interaction: only update slider value (keep options consistent with user_has_uploaded)
    if trigger == "reset-button":
        t_start, t_end = 0, T_MAX
    elif trigger == "time-range-slider" and time_range is not None:
        t_start, t_end = time_range
    else:
        t_start, t_end = 0, T_MAX

    if not user_has_uploaded:
        data_options, opts = [], []
    else:
        data_options = [c for c in df.columns if c not in [TIME_COL, "seconds"]]
        opts = [{"label": c, "value": c} for c in data_options]
    return (
        data_options,
        opts,
        opts,
        opts,
        opts,
        0,
        T_MAX,
        {},
        [t_start, t_end],
        0,
        T_MAX,
        {},
        [0, T_MAX],
    )


@callback(
    Output("analysis-time-range-slider", "value", allow_duplicate=True),
    Input("analysis-reset-button", "n_clicks"),
    State("dataset-store", "data"),
    prevent_initial_call=True,
)
def reset_analysis_time_range(n_clicks, store_data):
    T_MAX = store_data.get("T_MAX", T_MAX_default) if store_data else T_MAX_default
    return [0, T_MAX]


# Clear cached performance when dataset changes (new upload) so graph doesn't show stale data
@callback(
    Output("analysis-perf-store", "data", allow_duplicate=True),
    Input("dataset-store", "data"),
    prevent_initial_call=True,
)
def clear_analysis_perf_on_dataset_change(store_data):
    return None


@callback(
    Output("venturi-fuel-inlet-select", "options"),
    Output("venturi-fuel-throat-select", "options"),
    Output("venturi-ox-inlet-select", "options"),
    Output("venturi-ox-throat-select", "options"),
    Input("dataset-store", "data"),
    Input("user-has-uploaded", "data"),
)
def update_venturi_channel_options(store_data, user_has_uploaded):
    empty = []
    if not user_has_uploaded or not store_data:
        return empty, empty, empty, empty
    df, _T_MIN, _T_MAX, X_COL, TIME_COL = _get_dataset(store_data)
    cols = [c for c in df.columns if c not in [TIME_COL, "seconds"]]
    opts = [{"label": c, "value": c} for c in cols]
    return opts, opts, opts, opts


# Compute performance and cache in store (only on Calculate click); avoids recompute on slider drag
@callback(
    Output("analysis-perf-store", "data"),
    Input("analysis-calculate-button", "n_clicks"),
    State("dataset-store", "data"),
    State("input-throat-area", "value"),
    State("thrust-channels-select", "value"),
    State("chamber-pressure-select", "value"),
    State("fuel-weight-select", "value"),
    State("ox-weight-select", "value"),
    State("venturi-use-for-performance-checklist", "value"),
    State("venturi-fuel-rho-constant", "value"),
    State("venturi-ox-rho-constant", "value"),
    State("venturi-fuel-inlet-select", "value"),
    State("venturi-fuel-throat-select", "value"),
    State("venturi-fuel-cda", "value"),
    State("venturi-fuel-beta", "value"),
    State("venturi-ox-inlet-select", "value"),
    State("venturi-ox-throat-select", "value"),
    State("venturi-ox-cda", "value"),
    State("venturi-ox-beta", "value"),
    prevent_initial_call=True,
)
def compute_and_store_analysis_perf(
    n_clicks, store_data, A_star, thrust_channels, chamber_pressure_col, fuel_weight_col, ox_weight_col,
    venturi_use_for_perf,
    venturi_fuel_rho_const,
    venturi_ox_rho_const,
    venturi_fuel_inlet, venturi_fuel_throat,
    venturi_fuel_cda, venturi_fuel_beta,
    venturi_ox_inlet, venturi_ox_throat,
    venturi_ox_cda, venturi_ox_beta,
):
    if not n_clicks:
        return None
    df, T_MIN, T_MAX, X_COL, TIME_COL = _get_dataset(store_data)
    if df is None or df.empty:
        return None
    thrust_channels = thrust_channels or []
    if not thrust_channels:
        return None
    total_thrust = compute_total_thrust(df, thrust_channels)

    def _valid_window(t_start, t_end):
        return (
            t_start is not None and t_end is not None
            and np.isfinite(t_start) and np.isfinite(t_end)
            and float(t_end) > float(t_start)
        )
    # 1) Flow windows from selected tank weight columns (automatic).
    fuel_flow_t_start, fuel_flow_t_end = np.nan, np.nan
    ox_flow_t_start, ox_flow_t_end = np.nan, np.nan
    if fuel_weight_col and fuel_weight_col in df.columns:
        fuel_flow_t_start, fuel_flow_t_end = get_burn_window_from_weight(
            df, X_COL, fuel_weight_col, threshold_fraction=0.1
        )
    if ox_weight_col and ox_weight_col in df.columns:
        ox_flow_t_start, ox_flow_t_end = get_burn_window_from_weight(
            df, X_COL, ox_weight_col, threshold_fraction=0.1
        )
    # Combined flow window used only for reference in store.
    flow_starts = [x for x in [fuel_flow_t_start, ox_flow_t_start] if np.isfinite(x)]
    flow_ends = [x for x in [fuel_flow_t_end, ox_flow_t_end] if np.isfinite(x)]
    flow_t_start = float(np.min(flow_starts)) if flow_starts else np.nan
    flow_t_end = float(np.max(flow_ends)) if flow_ends else np.nan

    # 2) Burn window: from load-cell spike boundaries.
    burn_t_start, burn_t_end = get_burn_window_from_loadcell_spike(df, X_COL, total_thrust)
    if not _valid_window(burn_t_start, burn_t_end):
        # Fallback to existing thrust methods if spike-base detection fails.
        burn_t_start, burn_t_end = get_burn_window(
            df, X_COL, total_thrust, threshold_fraction=0.1, burn_method="peaks",
        )
    if not _valid_window(burn_t_start, burn_t_end):
        burn_t_start, burn_t_end = get_burn_window(
            df, X_COL, total_thrust, threshold_fraction=0.1, burn_method="threshold",
        )
    if detect_flow:
        # Auto mode: slope over detected windows (current behavior).
        slope_fuel, slope_ox = compute_mass_flow_from_tank_weights(
            df, X_COL, fuel_weight_col or "", ox_weight_col or "",
            burn_signal=total_thrust, burn_threshold_fraction=0.1, burn_method="peaks",
            burn_t_start=burn_t_start if _valid_window(burn_t_start, burn_t_end) else None,
            burn_t_end=burn_t_end if _valid_window(burn_t_start, burn_t_end) else None,
        )
        if not (np.isfinite(slope_fuel) and np.isfinite(slope_ox)):
            slope_fuel, slope_ox = compute_mass_flow_from_tank_weights(
                df, X_COL, fuel_weight_col or "", ox_weight_col or "",
                burn_signal=total_thrust, burn_threshold_fraction=0.1, burn_method="threshold",
                burn_t_start=burn_t_start if _valid_window(burn_t_start, burn_t_end) else None,
                burn_t_end=burn_t_end if _valid_window(burn_t_start, burn_t_end) else None,
            )
    else:
        # Manual mode: slope = (W_end_global - W_start_global) / (t_flow_end - t_flow_start)
        # where W_start_global is tank weight at dataset start and W_end_global at dataset end.
        slope_fuel, slope_ox = np.nan, np.nan
        t0 = float(df[X_COL].min()) if X_COL in df.columns else np.nan
        t1 = float(df[X_COL].max()) if X_COL in df.columns else np.nan
        if np.isfinite(t0) and np.isfinite(t1):
            df_sorted = df.sort_values(X_COL)
            if fuel_weight_col and fuel_weight_col in df_sorted.columns and _valid_window(fuel_flow_t_start, fuel_flow_t_end):
                w0_fuel = float(df_sorted[fuel_weight_col].iloc[0])
                w1_fuel = float(df_sorted[fuel_weight_col].iloc[-1])
                dt_fuel = float(fuel_flow_t_end) - float(fuel_flow_t_start)
                if np.isfinite(w0_fuel) and np.isfinite(w1_fuel) and dt_fuel > 0:
                    slope_fuel = (w1_fuel - w0_fuel) / dt_fuel
            if ox_weight_col and ox_weight_col in df_sorted.columns and _valid_window(ox_flow_t_start, ox_flow_t_end):
                w0_ox = float(df_sorted[ox_weight_col].iloc[0])
                w1_ox = float(df_sorted[ox_weight_col].iloc[-1])
                dt_ox = float(ox_flow_t_end) - float(ox_flow_t_start)
                if np.isfinite(w0_ox) and np.isfinite(w1_ox) and dt_ox > 0:
                    slope_ox = (w1_ox - w0_ox) / dt_ox
    # Use absolute flow magnitudes so displayed/derived flow rates are not negative.
    slope_fuel_abs = abs(float(slope_fuel)) if np.isfinite(slope_fuel) else np.nan
    slope_ox_abs = abs(float(slope_ox)) if np.isfinite(slope_ox) else np.nan
    # Convert absolute slopes to kg/s for performance equations.
    m_dot_fuel_kg_s = (slope_fuel_abs / G0_FT_S2) * LBM_TO_KG if np.isfinite(slope_fuel_abs) else 0.0
    m_dot_ox_kg_s = (slope_ox_abs / G0_FT_S2) * LBM_TO_KG if np.isfinite(slope_ox_abs) else 0.0
    try:
        A_star_val = float(A_star) if (A_star is not None and A_star != "") else 0.0
    except (TypeError, ValueError):
        A_star_val = 0.0
    perf = compute_performance_series(
        df, X_COL, total_thrust, chamber_pressure_col or "", A_star_val,
        m_dot_fuel_kg_s,
        m_dot_ox_kg_s,
    )

    def _float_param(v):
        try:
            if v is None or v == "":
                return np.nan
            return float(v)
        except (TypeError, ValueError):
            return np.nan

    use_venturi_isp = "use" in (venturi_use_for_perf or [])
    # Inlet + throat only: ΔP = |P_inlet − P_throat| (psi → Pa inside).
    s_fuel_vent = compute_venturi_mass_flow_series_kg_s(
        df,
        "p1p2_psi",
        None,
        venturi_fuel_inlet,
        venturi_fuel_throat,
        venturi_fuel_rho_const,
        _float_param(venturi_fuel_cda),
        _float_param(venturi_fuel_beta),
    )
    s_ox_vent = compute_venturi_mass_flow_series_kg_s(
        df,
        "p1p2_psi",
        None,
        venturi_ox_inlet,
        venturi_ox_throat,
        venturi_ox_rho_const,
        _float_param(venturi_ox_cda),
        _float_param(venturi_ox_beta),
    )
    perf["Venturi fuel mdot (kg/s)"] = s_fuel_vent.reindex(perf.index).astype(float)
    perf["Venturi ox mdot (kg/s)"] = s_ox_vent.reindex(perf.index).astype(float)

    def _mean_venturi_mdot_burn_kg_s(time_col_series, mdot_series, bt0, bt1):
        if not _valid_window(bt0, bt1):
            return np.nan
        t0, t1 = float(bt0), float(bt1)
        t = time_col_series.reindex(mdot_series.index).astype(float)
        m = mdot_series.astype(float)
        mask = (t >= t0 - 1e-9) & (t <= t1 + 1e-9)
        arr = np.asarray(m[mask], dtype=float)
        arr = arr[np.isfinite(arr)]
        if arr.size == 0:
            return np.nan
        return float(np.mean(arr))

    t_for_vent = df[X_COL]
    # total_thrust: sum of user-selected thrust columns (see compute_total_thrust).
    avg_thrust_burn = _mean_venturi_mdot_burn_kg_s(t_for_vent, total_thrust, burn_t_start, burn_t_end)
    if chamber_pressure_col and chamber_pressure_col in df.columns:
        avg_chamber_psi_burn = _mean_venturi_mdot_burn_kg_s(
            t_for_vent, df[chamber_pressure_col], burn_t_start, burn_t_end
        )
    else:
        avg_chamber_psi_burn = np.nan
    avg_vent_fuel_burn = _mean_venturi_mdot_burn_kg_s(t_for_vent, s_fuel_vent, burn_t_start, burn_t_end)
    avg_vent_ox_burn = _mean_venturi_mdot_burn_kg_s(t_for_vent, s_ox_vent, burn_t_start, burn_t_end)

    if use_venturi_isp:

        def _blend_vent_to_mdot(vent_series, scalar_kg_s, idx):
            v = vent_series.reindex(idx)
            if not v.notna().any():
                return pd.Series(float(scalar_kg_s) if np.isfinite(scalar_kg_s) else np.nan, index=idx)
            if np.isfinite(scalar_kg_s):
                return v.fillna(float(scalar_kg_s))
            return v

        mf = _blend_vent_to_mdot(s_fuel_vent, m_dot_fuel_kg_s, perf.index)
        mo = _blend_vent_to_mdot(s_ox_vent, m_dot_ox_kg_s, perf.index)
        m_dot_total_series = mf.astype(float) + mo.astype(float)
        pc_series = None
        if chamber_pressure_col and chamber_pressure_col in df.columns:
            pc_series = df[chamber_pressure_col].reindex(perf.index)
        perf = recompute_isp_cstar_with_mdot_total_series(
            perf, total_thrust, pc_series, A_star_val, m_dot_total_series
        )

    return {
        "perf_json": perf.to_json(orient="split", date_format="iso"),
        "X_COL": X_COL,
        "m_dot_fuel": slope_fuel_abs if np.isfinite(slope_fuel_abs) else None,
        "m_dot_ox": slope_ox_abs if np.isfinite(slope_ox_abs) else None,
        "flow_t_start": float(flow_t_start) if np.isfinite(flow_t_start) else None,
        "flow_t_end": float(flow_t_end) if np.isfinite(flow_t_end) else None,
        "fuel_flow_t_start": float(fuel_flow_t_start) if np.isfinite(fuel_flow_t_start) else None,
        "fuel_flow_t_end": float(fuel_flow_t_end) if np.isfinite(fuel_flow_t_end) else None,
        "ox_flow_t_start": float(ox_flow_t_start) if np.isfinite(ox_flow_t_start) else None,
        "ox_flow_t_end": float(ox_flow_t_end) if np.isfinite(ox_flow_t_end) else None,
        "burn_t_start": float(burn_t_start) if np.isfinite(burn_t_start) else None,
        "burn_t_end": float(burn_t_end) if np.isfinite(burn_t_end) else None,
        "avg_thrust_lbf_burn": float(avg_thrust_burn) if np.isfinite(avg_thrust_burn) else None,
        "avg_chamber_psi_burn": float(avg_chamber_psi_burn) if np.isfinite(avg_chamber_psi_burn) else None,
        "avg_venturi_fuel_mdot_burn": float(avg_vent_fuel_burn) if np.isfinite(avg_vent_fuel_burn) else None,
        "avg_venturi_ox_mdot_burn": float(avg_vent_ox_burn) if np.isfinite(avg_vent_ox_burn) else None,
    }


# Graph callback: use pre-filtered store when available (fast path when only checklist changes).
def _parse_filtered_store(data):
    if not data or "df_json" not in data:
        return None, None
    try:
        js = data["df_json"]
        df = pd.read_json(io.StringIO(js) if isinstance(js, str) else js, orient="split")
        return df, data.get("X_COL", "Time (s)")
    except Exception:
        return None, None


def _find_tank_weight_column(df):
    """Return first column name that contains 'tank' or 'weight' (case-insensitive), or None."""
    if df is None or df.empty:
        return None
    for col in df.columns:
        if col is None:
            continue
        c = str(col).lower()
        if "tank" in c or "weight" in c:
            return col
    return None


@callback(
    Output('data-graph', 'figure'),
    Output('data-graph-figure-store', 'data'),
    Output('timeseries-burn-time-message', 'children'),
    Input('filtered-df-store', 'data'),
    Input('dataset-store', 'data'),
    Input('data-checklist', 'value'),
    Input('time-range-slider', 'value'),
    Input('reset-button', 'n_clicks'),
    Input('analysis-checklist', 'value'),
)
def update_data_graph(filtered_store, store_data, selected_data, time_range, n_clicks,
                      analysis_options):
    # Prefer pre-filtered df (avoids parsing full dataset when only checklist changes)
    df_filtered, X_COL = _parse_filtered_store(filtered_store)
    if df_filtered is None:
        df, T_MIN, T_MAX, X_COL, _ = _get_dataset(store_data)
        _, df_filtered, _, _ = get_time_filtered_df(time_range, None, None, T_MIN, T_MAX, df, X_COL)
    data_options = [c for c in df_filtered.columns if c != X_COL and c != "seconds"]
    color_map = {col: COLOR_MAP_DEFAULT.get(col, px.colors.qualitative.Plotly[i % 10]) for i, col in enumerate(data_options)}

    show_regression = 'Regression' in (analysis_options or [])
    show_burn_time_timeseries = BURN_TIME_TIMESERIES_VALUE in (analysis_options or [])

    selected_data = [c for c in (selected_data or []) if c != "__upload__"]
    burn_msg = ""
    if not selected_data:
        fig = go.Figure()
        title = "Upload data" if (store_data and store_data.get("filenames") == [DEFAULT_FILE]) else "Select channels in the checklist"
        fig.update_layout(title=title, showlegend=True)
        return fig, fig.to_dict() if hasattr(fig, 'to_dict') else None, burn_msg

    # Downsample for faster rendering when many points
    n = len(df_filtered)
    if n > MAX_POINTS_DISPLAY:
        idx = np.linspace(0, n - 1, MAX_POINTS_DISPLAY, dtype=int)
        df_plot = df_filtered.iloc[idx]
    else:
        df_plot = df_filtered

    graph_title = ", ".join(selected_data)
    y_title = y_axis_label(selected_data)
    x_vals = df_plot[X_COL].astype(float).values

    fig = go.Figure()
    for col in selected_data:
        if col not in df_plot.columns:
            continue
        y_vals = df_plot[col].values
        mask = np.isfinite(y_vals)
        fig.add_trace(
            go.Scatter(
                x=x_vals,
                y=y_vals,
                name=col,
                mode="lines",
                line=dict(color=color_map.get(col), width=2),
                legendgroup=col,
            )
        )
        if show_regression and mask.sum() >= 2:
            x_fit = x_vals[mask]
            y_fit = y_vals[mask]
            coefs = np.polyfit(x_fit, y_fit, 1)
            y_trend = np.polyval(coefs, x_fit)
            fig.add_trace(
                go.Scatter(
                    x=x_fit,
                    y=y_trend,
                    name=f"{col} (fit)",
                    mode="lines",
                    line=dict(color="red", dash="dash", width=1.5),
                    legendgroup=col,
                )
            )
    # Burn time on timeseries: detect from tank/weight column (weight decreases during burn)
    if show_burn_time_timeseries:
        weight_col = _find_tank_weight_column(df_filtered)
        if weight_col and X_COL in df_filtered.columns:
            burn_t_start, burn_t_end = get_burn_window_from_weight(
                df_filtered, X_COL, weight_col, threshold_fraction=0.1
            )
            if np.isfinite(burn_t_start) and np.isfinite(burn_t_end) and burn_t_end > burn_t_start:
                t_start = float(burn_t_start)
                t_end = float(burn_t_end)
                fig.add_shape(
                    type="rect",
                    x0=t_start,
                    x1=t_end,
                    y0=0,
                    y1=1,
                    yref="paper",
                    fillcolor="rgba(100, 149, 237, 0.25)",
                    line=dict(width=0),
                    layer="below",
                )
                fig.add_vline(x=t_start, line_dash="dash", line_color="steelblue", line_width=1.5, annotation_text="Burn Time")
                fig.add_vline(x=t_end, line_dash="dash", line_color="steelblue", line_width=1.5)
            else:
                burn_msg = html.Span("Burn time cannot be detected.", style={"color": "red", "fontWeight": "600"})
        else:
            burn_msg = html.Span("Burn time cannot be detected.", style={"color": "red", "fontWeight": "600"})
    fig.update_layout(
        title=graph_title,
        xaxis_title="Time (s)",
        yaxis_title=y_title,
        legend_title="Channels",
        showlegend=True,
        xaxis=dict(tickformat=".3f", type="linear"),
    )
    return fig, fig.to_dict(), burn_msg


# Mass flow rate displays above performance graph (from tank weight slopes over burn time)
@callback(
    Output("analysis-mdot-fuel-display", "children"),
    Output("analysis-mdot-ox-display", "children"),
    Output("analysis-burn-time-display", "children"),
    Output("analysis-avg-thrust-burn-display", "children"),
    Output("analysis-avg-chamber-p-burn-display", "children"),
    Output("analysis-ox-flow-time-display", "children"),
    Output("analysis-fuel-flow-time-display", "children"),
    Input("analysis-perf-store", "data"),
)
def update_mass_flow_displays(perf_store):
    if not perf_store:
        return "—", "—", "—", "—", "—", "—", "—"
    m_fuel = perf_store.get("m_dot_fuel")
    m_ox = perf_store.get("m_dot_ox")
    burn_t_start = perf_store.get("burn_t_start")
    burn_t_end = perf_store.get("burn_t_end")
    fuel_str = f"{m_fuel:.4f}" if m_fuel is not None and np.isfinite(m_fuel) else "—"
    ox_str = f"{m_ox:.4f}" if m_ox is not None and np.isfinite(m_ox) else "—"
    if (
        burn_t_start is not None and burn_t_end is not None
        and np.isfinite(burn_t_start) and np.isfinite(burn_t_end)
        and float(burn_t_end) > float(burn_t_start)
    ):
        burn_time_str = f"{float(burn_t_end) - float(burn_t_start):.3f}"
    else:
        burn_time_str = "—"

    avg_t = perf_store.get("avg_thrust_lbf_burn")
    if avg_t is not None and np.isfinite(avg_t):
        avg_thrust_str = f"{float(avg_t):.2f}"
    else:
        avg_thrust_str = "—"

    avg_pc = perf_store.get("avg_chamber_psi_burn")
    if avg_pc is not None and np.isfinite(avg_pc):
        avg_chamber_str = f"{float(avg_pc):.2f}"
    else:
        avg_chamber_str = "—"

    def _fmt_avg_vent_mdot(v):
        if v is not None and np.isfinite(v):
            if abs(v) > 0 and abs(v) < 0.0001:
                return f"{v:.3e}"
            return f"{v:.4f}"
        return "—"

    avg_ox = perf_store.get("avg_venturi_ox_mdot_burn")
    avg_fuel = perf_store.get("avg_venturi_fuel_mdot_burn")
    ox_vent_burn_str = _fmt_avg_vent_mdot(avg_ox)
    fuel_vent_burn_str = _fmt_avg_vent_mdot(avg_fuel)
    return fuel_str, ox_str, burn_time_str, avg_thrust_str, avg_chamber_str, ox_vent_burn_str, fuel_vent_burn_str


# Analysis graph: reads cached perf from store, filters by slider, downsamples for speed (no recompute on slider drag)
@callback(
    Output("analysis-graph", "figure"),
    Output("analysis-graph-figure-store", "data"),
    Input("analysis-perf-store", "data"),
    Input("analysis-time-range-slider", "value"),
    Input("analysis-metrics-checklist", "value"),
)
def update_analysis_graph(perf_store, analysis_time_range, metrics_to_plot):
    if not perf_store or "perf_json" not in perf_store:
        fig = go.Figure()
        fig.update_layout(
            title="Click Calculate (in Inputs tab) to compute performance metrics",
            xaxis_title="Time (s)",
            showlegend=True,
        )
        return fig, None
    try:
        perf = pd.read_json(
            io.StringIO(perf_store["perf_json"]) if isinstance(perf_store["perf_json"], str) else perf_store["perf_json"],
            orient="split",
        )
    except Exception:
        fig = go.Figure()
        fig.update_layout(title="Error loading performance data", xaxis_title="Time (s)", showlegend=True)
        return fig, None
    X_COL = perf_store.get("X_COL", "Time (s)")
    if X_COL not in perf.columns or perf.empty:
        fig = go.Figure()
        fig.update_layout(title="No performance data", xaxis_title="Time (s)", showlegend=True)
        return fig, None
    if analysis_time_range is not None and len(analysis_time_range) == 2:
        try:
            t_lo = float(analysis_time_range[0])
            t_hi = float(analysis_time_range[1])
            if t_lo > t_hi:
                t_lo, t_hi = t_hi, t_lo
            perf = perf[(perf[X_COL] >= t_lo) & (perf[X_COL] <= t_hi)]
        except (TypeError, ValueError):
            pass
    metrics_to_plot = metrics_to_plot or []
    show_burn_time = "Burn time" in metrics_to_plot

    # Resolve checklist metric → perf column (venturi: ASCII keys; tolerate Unicode ṁ / stale JSON).
    _OLD_VENTURI_LABEL = {
        "Venturi fuel ṁ (kg/s)": "Venturi fuel mdot (kg/s)",
        "Venturi ox ṁ (kg/s)": "Venturi ox mdot (kg/s)",
    }
    _NEW_TO_OLD_VENTURI_COL = {v: k for k, v in _OLD_VENTURI_LABEL.items()}

    def _perf_col_for_metric(m):
        if not isinstance(m, str) or m == "Burn time":
            return None
        if m in perf.columns:
            return m
        # Cached checklist (Unicode) vs new perf columns (ASCII)
        new_name = _OLD_VENTURI_LABEL.get(m)
        if new_name and new_name in perf.columns:
            return new_name
        # New checklist vs stale perf JSON (still has Unicode column names)
        old_col = _NEW_TO_OLD_VENTURI_COL.get(m)
        if old_col and old_col in perf.columns:
            return old_col
        m_nfc = unicodedata.normalize("NFC", m)
        for c in perf.columns:
            if isinstance(c, str) and unicodedata.normalize("NFC", c) == m_nfc:
                return c
        return None

    valid_metrics = []
    _seen = set()
    for m in metrics_to_plot:
        col = _perf_col_for_metric(m)
        if col is not None and col not in _seen:
            valid_metrics.append(col)
            _seen.add(col)
    if not valid_metrics and not show_burn_time:
        fig = go.Figure()
        fig.update_layout(title="Select metrics to plot (Plot tab)", xaxis_title="Time (s)", showlegend=True)
        return fig, None
    if perf.empty and not show_burn_time:
        fig = go.Figure()
        fig.update_layout(
            title="No performance data in selected time range",
            xaxis_title="Time (s)",
            showlegend=True,
        )
        return fig, None
    # Downsample for faster rendering when many points
    n = len(perf)
    if n > MAX_POINTS_DISPLAY:
        idx = np.linspace(0, n - 1, MAX_POINTS_DISPLAY, dtype=int)
        perf = perf.iloc[idx]
    def metric_color(i):
        return ANALYSIS_METRIC_COLORS[i % len(ANALYSIS_METRIC_COLORS)]

    if valid_metrics:
        fig = px.line(perf, x=X_COL, y=valid_metrics[0], title=", ".join(valid_metrics))
        fig.update_traces(mode="lines", name=valid_metrics[0], line=dict(color=metric_color(0)))
        for i, col in enumerate(valid_metrics[1:]):
            if col in perf.columns:
                fig.add_scatter(
                    x=perf[X_COL],
                    y=perf[col],
                    mode="lines",
                    name=col,
                    line=dict(color=metric_color(i + 1)),
                )
        yaxis_title = ", ".join(valid_metrics)
        t_min_plot = float(perf[X_COL].min())
        t_max_plot = float(perf[X_COL].max())
    else:
        # Only "Burn time" selected: no y-series line; invisible trace sets x range for the shaded region.
        fig = go.Figure()
        t_min_plot = float(perf[X_COL].min()) if not perf.empty else 0.0
        t_max_plot = float(perf[X_COL].max()) if not perf.empty else 1.0
        if analysis_time_range is not None and len(analysis_time_range) == 2:
            try:
                t_lo = float(analysis_time_range[0])
                t_hi = float(analysis_time_range[1])
                if t_lo > t_hi:
                    t_lo, t_hi = t_hi, t_lo
                t_min_plot, t_max_plot = t_lo, t_hi
            except (TypeError, ValueError):
                pass
        fig.add_trace(
            go.Scatter(
                x=[t_min_plot, t_max_plot],
                y=[0, 0],
                mode="lines",
                line=dict(width=0, color="rgba(0,0,0,0)"),
                showlegend=False,
                hoverinfo="skip",
            )
        )
        yaxis_title = " "
        fig.update_layout(
            title="Burn time (shaded region)",
            xaxis=dict(range=[t_min_plot, t_max_plot], title="Time (s)", tickformat=".3f", type="linear"),
            yaxis=dict(visible=False),
        )

    # Shaded burn window only (no "Burn time" y(t) line — perf value is a scalar duration).
    burn_t_start = perf_store.get("burn_t_start")
    burn_t_end = perf_store.get("burn_t_end")
    if show_burn_time and burn_t_start is not None and burn_t_end is not None:
        t_start = float(burn_t_start)
        t_end = float(burn_t_end)
        fig.add_shape(
            type="rect",
            x0=t_start,
            x1=t_end,
            y0=0,
            y1=1,
            yref="paper",
            fillcolor="rgba(100, 149, 237, 0.25)",
            line=dict(width=0),
            layer="below",
        )

    _xaxis = dict(tickformat=".3f", type="linear")
    if not valid_metrics and show_burn_time:
        fig.update_layout(
            xaxis_title="Time (s)",
            yaxis=dict(visible=False, title=""),
            showlegend=False,
            xaxis={**_xaxis, "range": [t_min_plot, t_max_plot]},
        )
    else:
        fig.update_layout(
            xaxis_title="Time (s)",
            yaxis_title=yaxis_title,
            legend_title="Metric",
            showlegend=True,
            xaxis=_xaxis,
        )
    return fig, fig.to_dict()


def _export_figure_to_download(fig_dict, title, format_key, filename=None):
    """Build figure from dict, apply title, export to image bytes; return (content_dict, _) for dcc.Download.
    title: used as figure title if non-empty; otherwise figure keeps existing title.
    filename: optional file name for download (no extension); if empty, derived from title.
    """
    if not fig_dict:
        return no_update, no_update
    fig = go.Figure(fig_dict)
    if title and str(title).strip():
        fig.update_layout(title=str(title).strip())
    ext = format_key if format_key in ("png", "jpeg", "webp", "svg") else "png"
    try:
        img_bytes = pio.to_image(fig, format=ext, scale=2)
    except Exception:
        img_bytes = pio.to_image(fig, format="png", scale=2)
        ext = "png"
    if filename is not None and str(filename).strip():
        base_name = re.sub(r'[<>:"/\\|?*]', "_", str(filename).strip())
    else:
        base_name = (re.sub(r'[<>:"/\\|?*]', "_", str(title).strip()) if title else "") or "graph"
    out_filename = base_name + "." + ext
    content = base64.b64encode(img_bytes).decode() if isinstance(img_bytes, bytes) else img_bytes
    return {"content": content, "filename": out_filename, "base64": True}, False


# ----- Save modals: open on Save, close on Cancel or Download -----
@callback(
    Output("data-graph-save-modal", "is_open"),
    Input("data-graph-save-btn", "n_clicks"),
    Input("data-graph-save-cancel", "n_clicks"),
    Input("data-graph-save-download", "n_clicks"),
    prevent_initial_call=True,
)
def toggle_data_graph_save_modal(open_clicks, cancel_clicks, download_clicks):
    tid = ctx.triggered_id
    if tid == "data-graph-save-btn":
        return True
    return False


@callback(
    Output("analysis-graph-save-modal", "is_open"),
    Input("analysis-graph-save-btn", "n_clicks"),
    Input("analysis-graph-save-cancel", "n_clicks"),
    Input("analysis-graph-save-download", "n_clicks"),
    prevent_initial_call=True,
)
def toggle_analysis_graph_save_modal(open_clicks, cancel_clicks, download_clicks):
    tid = ctx.triggered_id
    if tid == "analysis-graph-save-btn":
        return True
    return False


# ----- Save: trigger download (modal is closed by toggle callback when Download is clicked) -----
@callback(
    Output("download-data-graph", "data"),
    Input("data-graph-save-download", "n_clicks"),
    State("data-graph-save-title", "value"),
    State("data-graph-save-filename", "value"),
    State("data-graph-save-format", "value"),
    State("data-graph-figure-store", "data"),
    prevent_initial_call=True,
)
def download_data_graph(n_clicks, title, filename, format_val, fig_store):
    if not n_clicks or not fig_store:
        return no_update
    content_fn, _ = _export_figure_to_download(
        fig_store, title or "", format_val or "png",
        filename=(filename if filename and str(filename).strip() else "timeseries"),
    )
    return content_fn


@callback(
    Output("download-analysis-graph", "data"),
    Input("analysis-graph-save-download", "n_clicks"),
    State("analysis-graph-save-title", "value"),
    State("analysis-graph-save-filename", "value"),
    State("analysis-graph-save-format", "value"),
    State("analysis-graph-figure-store", "data"),
    prevent_initial_call=True,
)
def download_analysis_graph(n_clicks, title, filename, format_val, fig_store):
    if not n_clicks or not fig_store:
        return no_update
    content_fn, _ = _export_figure_to_download(
        fig_store, title or "", format_val or "png",
        filename=(filename if filename and str(filename).strip() else "performance_analysis"),
    )
    return content_fn


