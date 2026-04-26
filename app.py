import os
from dash import Dash
import dataApp
import plotly.io as pio
import dash_bootstrap_components as dbc

pio.templates.default = "plotly_dark"

app = Dash(__name__, external_stylesheets=[dbc.themes.CYBORG])
app.layout = dataApp.layout
server = app.server  # gunicorn:  gunicorn app:server --bind 0.0.0.0:$PORT

if __name__ == "__main__":
    # Local dev; on Render, use host/port or gunicorn (see README).
    port = int(os.environ.get("PORT", 8050))
    app.run(host="0.0.0.0", port=port, debug=True)