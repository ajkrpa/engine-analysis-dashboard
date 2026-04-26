from dash import Dash
import dataApp  
import plotly.io as pio
import dash_bootstrap_components as dbc

pio.templates.default = "plotly_dark"

app = Dash(__name__, external_stylesheets=[dbc.themes.CYBORG])

app.layout = dataApp.layout

if __name__ == "__main__":
    app.run(debug=True)   