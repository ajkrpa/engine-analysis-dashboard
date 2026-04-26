# Rocket hot-fire dashboard

This repository includes two ways to explore your CSV telemetry and run the same performance math:

1. **Web dashboard (HTML + JavaScript)** — no Python needed to *view* it; runs in the browser with Plotly, Papa Parse, and noUiSlider. Form settings are stored in **local storage** for the same browser.

2. **Dash app (Python)** — the original Plotly Dash UI in `dataApp.py`, sharing **core** analysis and data helpers with the same physical models.

## Quick start — webapp (recommended for a quick look)

From the `webapp` folder, start a static file server (browsers can block `file://` fetches, so a local server avoids that):

```bash
cd webapp
python -m http.server 8080
```

Open [http://localhost:8080](http://localhost:8080).

**Features:** multi-file CSV upload (merged on time), timeseries and performance plots, venturi-optional mass flow, save plots as images, and persisted UI settings in the browser.

## Quick start — Dash

Use a virtual environment, install dependencies, and run the app from the project root:

```bash
pip install -r requirements.txt
python app.py
```

Then open the URL shown in the terminal (by default with `debug=True`, often `http://127.0.0.1:8050`).

The Dash app loads a default dataset from `data/1047_pt.csv` on startup until you upload your own file.

## Project layout

| Path | Purpose |
|------|---------|
| `webapp/index.html`, `app.js`, `style.css` | Standalone browser dashboard |
| `app.py` | Dash entry: layout from `dataApp` |
| `dataApp.py` | Dash layout and callbacks (large) |
| `core/data.py` | CSV load, time column, merge |
| `core/analysis.py` | Thrust, mdot, venturi, Isp, C*, etc. |
| `core/utils.py` | Time filtering, axis labels |
| `assets/` | Dash extra CSS (theme and dropdown fixes) |
| `data/1047_pt.csv` | Default dataset for the Dash app |

## Requirements (Dash only)

See `requirements.txt` (Dash, Plotly, pandas, numpy, scipy, kaleido, dash-bootstrap-components).

## Render

**Recommended:** create a **Static Site**, publish the **`webapp`** folder (no build, or `true`). You can use the root **`render.yaml`** in this repo (Blueprint) or in the dashboard set **Build command** to empty or `true` and **Publish directory** to `webapp`.

**If you use a Web Service (Python / Dash) instead of static:** a bare `python app.py` often exits with **status 1** on Render because the app must listen on **`0.0.0.0`** and the **`PORT`** environment variable. This repo’s `app.py` does that in `if __name__ == "__main__"`. A more typical production start is gunicorn (Linux):

```bash
pip install gunicorn
gunicorn app:server --bind 0.0.0.0:$PORT
```

Set **Start command** in Render to that (after a build that runs `pip install -r requirements.txt` and `pip install gunicorn`). The **“Exited with status 1”** line in the log is the outcome; the **real** error is usually a few lines **above** (import error, `Address already in use`, or `gunicorn: command not found`).

## GitHub

Create an empty repository on GitHub, then from this folder:

```bash
git init
git add -A
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/<you>/<repo>.git
git push -u origin main
```

Use a [personal access token](https://github.com/settings/tokens) or SSH for authentication.
