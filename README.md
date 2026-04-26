# Hot-fire engine analysis dashboard — user guide

This app helps you review **CSV test data** from a rocket or engine hot fire: plot **time series** (pressures, loads, etc.), then compute **performance metrics** (thrust-based specific impulse `Isp`, characteristic velocity `C*`, mixture ratio `O/F`, venturi mass flow, burn time) from your channels.

The main version runs **in your web browser**. You do **not** need to install anything to try the [hosted site](#opening-the-dashboard) if your team provides a link; for use on your own computer, see [Run it on your machine](#run-it-on-your-machine-optional).

---

## Opening the dashboard

- **If your team shared a URL** (for example on Render or another host), open that link in **Chrome, Edge, or Firefox**. The page is a normal website; your data is processed in the browser (see [Privacy](#privacy-and-your-data)).
- **If there is no hosted site**, you can run the files locally with a tiny built-in web server — see [Run it on your machine](#run-it-on-your-machine-optional).

---

## Your data (CSV files)

- Use **comma-separated (`.csv`)** files.
- The tool looks for a **time** column. It recognizes common names (e.g. containing “time”) or uses the first column, and builds a single timeline in **seconds**.
- You can upload **more than one file** at once. Rows are **merged on time** so channels from different files line up on the same clock.
- After upload, pick which **numeric columns** to plot from the **Channels** list.

**Tip:** Avoid stray text in numeric cells if you can. The parser is flexible with commas and decimals, but completely non-numeric columns may not appear as plottable channels.

---

## Main areas of the screen

### 1. Timeseries (first big plot)

- **Channels:** Check the signals you want on the **timeseries** plot. Use **Clear channels** to uncheck all.
- **Analysis (regression / burn):** Optional overlays on the timeseries as described on the card.
- **Time controls:** After data is loaded, use the **slider** or **Start / End** boxes to focus on part of the run. **Reset** sets the window back to the full time range. **Save timeseries image** downloads a PNG of the current plot.

### 2. Performance analysis (second section)

At the top you will see summary numbers (for example tank weight slopes, burn time, fuel/ox flow times) **after you run Calculate** (below).

- **Analysis time range:** Same idea as timeseries — slider and start/end times limit which part of the run is used for the **performance** plot and metrics.
- **Inputs**
  - **A\*** — Throat area in **m²** (used for `C*` and related terms).
  - **Thrust channels (lbf):** Open the list and check one or more load channels; their values are **added** to form total thrust.
  - **Chamber pressure (psi)** and **fuel / oxidizer tank weight (lbf)** — choose the matching columns from your data.
  - **Use venturis to compute mass flow rate (`Isp`, `C*`):** When **off**, mass flow for `Isp` / `C*` comes from **tank weight slopes** (fuel and ox lines). When **on**, the tool prefers **venturi** mass flow when those points are valid, and falls back to the tank slope for a stream if needed.  
  - Fuel and oxidizer **flow time windows** for the tank-weight method are **detected automatically** from the weight channels you selected.
- **Venturi** (optional): For each propellant line, enter fluid **density**, pick **inlet** and **throat** pressure channels, and enter **C<sub>d</sub>A** and **β** (throat-to-inlet diameter ratio) as needed. Fuel and ox are **independent**.
- **Plot Metrics:** Check which curves you want on the performance plot (`Isp`, `C*`, venturi mass flow, `O/F`, burn time, etc.).
- Click **Calculate** to refresh the performance plot and the summary numbers. If something is missing (channels, area, pressure), hints or diagnostics may appear under the button.
- **Save analysis image** downloads a PNG of the performance plot.

---

## Saved settings

Numbers, checkboxes, channel selections, and similar choices are saved in **this browser only** (local storage on your device). They come back when you open the same dashboard again in that browser. They are **not** uploaded to a server by this app.

If you use a **different computer, browser, or private/incognito window**, saved settings will not carry over unless you use the same browser profile as before.

---

## Privacy and your data

For the **browser-based dashboard**, your CSV files are read **in the page** for plotting and calculations. They are **not** sent to this project’s servers by default (there is no upload API in the static app). Keep using your organization’s rules for sensitive data and shared links.

---

## Troubleshooting

| Issue | What to try |
|--------|-------------|
| No plot after upload | Select at least one channel under **Channels** for the timeseries. |
| Performance is all “—” or NaN | Pick thrust, chamber pressure if needed for `C*` and `A*`, and valid weight/venturi inputs; click **Calculate**. Read any message under **Calculate**. |
| Wrong time range | Use **Reset** on the timeseries or analysis time card, or drag the slider to the full span. |
| Columns missing in dropdowns | Confirm the column has numeric data in the CSV; check spelling and units in the file. |

---

## Run it on your machine (optional)

If you have **Python** installed:

```bash
cd webapp
python -m http.server 8080
```

Then open **http://localhost:8080** in your browser.

---

## For developers

This repository also contains a **Plotly Dash** version of the UI (`app.py`, `dataApp.py`) and shared Python modules under `core/`. To run Dash locally:

```bash
pip install -r requirements.txt
python app.py
```

**Deploying the browser dashboard on Render (static):**

1. Create a **Static Site** (not a Web **Service** with Python).
2. Connect this repo, branch (e.g. `main`), **root directory = empty** (repository root).
3. **Build command: `true`** — type the three letters `true` and nothing else, **or** clear the build field.  
   **Do not use** `pip install -r requirements.txt` for the static `webapp`; that command is for the **Dash** app at the repo root, not the HTML/JS site.
4. **Publish directory** (or “static publish path”): **`webapp`**.

If your service already has `pip install -r requirements.txt` in **Build command**, open **Settings → Build & deploy**, change **Build command** to `true`, save, and **Clear build cache + deploy** (or **Manual deploy**). If the UI does not let you (wrong service type), create a new **Static Site** with the settings above, or use **Blueprint** and connect `render.yaml` from this repo.

**Repository layout (short):** `webapp/` — static dashboard; `app.py` / `dataApp.py` — Dash; `core/` — data and analysis logic; `data/` — sample CSV for Dash default load.

---

*Questions about your test program or data quality should go to your test lead or data owner; this file only documents how to use the dashboard software.*
