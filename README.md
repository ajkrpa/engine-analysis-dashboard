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

## Main Dashboard Sections

### 1. Timeseries Plot

- **Channels:** Check the signals you want on the **timeseries** plot. Use **Clear channels** to uncheck all.
- **Analysis (regression / burn):** Optional overlays on the timeseries as described on the card.
- **Time controls:** After data is loaded, use the **slider** or **Start / End** boxes to focus on part of the run. **Reset** sets the window back to the full time range. **Save timeseries image** downloads a PNG of the current plot.

### 2. Performance Analysis Plot

At the top you will see summary numbers (detected **burn** time, and **fuel/ox venturi active** times derived from the venturi mass-flow series) **after you run Calculate** (below).

- **Analysis time range:** Same idea as timeseries — slider and start/end times limit which part of the run is used for the **performance** plot and metrics.
- **Inputs**
  - **A\*** — Throat area in **m²** (used for `C*` and related terms).
  - **Thrust channels (lbf):** Open the list and check one or more load channels; their values are **added** to form total thrust.
  - **Chamber pressure (psi)** and **fuel / oxidizer tank weight (lbf)** — choose the matching columns from your data.
  - **`Isp` and `C*`:** Total mass flow is **fuel venturi ṁ + oxidizer venturi ṁ** (kg/s) on each time row. Configure both lines under **Venturi** (or one side only; the other counts as 0 if that row’s venturi ṁ is missing).
- **Venturi** (optional): For each propellant line, enter fluid **density**, pick **inlet** and **throat** pressure channels, and enter **C<sub>d</sub>A** and **β** (throat-to-inlet diameter ratio) as needed. Fuel and ox are **independent**. Tank weight columns are still used for **O/F** when venturi data is missing for a side.
- **Plot Metrics:** Check which curves you want on the performance plot (`Isp`, `C*`, venturi mass flow, `O/F`, burn time, etc.).
- Click **Calculate** to refresh the performance plot and the summary numbers. If something is wrong with inputs, a short hint may appear under the button.
- **Save analysis image** downloads a PNG of the performance plot.

---

## How calculations work (inputs -> equations -> outputs)

### Venturi mass flow rate

**Equation**

$$
\dot{m} = C_d A \sqrt{\frac{2\,\Delta P\,\rho}{1-\beta^4}}
$$

**Variables**

- $\dot{m}$: mass flow rate, in $\mathrm{kg/s}$
- $C_dA$: effective discharge-area term, in $\mathrm{m^2}$
- $\Delta P$: pressure drop between venturi inlet and throat, in $\mathrm{Pa}$
- $\rho$: fluid density, in $\mathrm{kg/m^3}$
- $\beta$: venturi diameter ratio, $\beta = d_{\mathrm{throat}}/d_{\mathrm{inlet}}$ (dimensionless)

**User input**

1. Upload CSV file(s)
2. Select venturi inlet and throat pressure channels for fuel and/or oxidizer
3. Enter `rho`, `C_d A`, and `beta` for each line

**Output**

1. `Venturi fuel mdot (kg/s)` and `Venturi ox mdot (kg/s)` are calculated
2. These mass-flow rates can be plotted in the analysis graph
3. These mass-flow rates are used to calculate `Isp`, `C*`, and `O/F`

### Tank-weight-derived mass flow rate

**Equation**

$$
\text{slope} = \frac{dW}{dt}
$$

$$
\dot{m}_{\mathrm{kg/s}} = \left|\frac{\text{slope}}{g_{0,\mathrm{ft/s^2}}}\right| \cdot \mathrm{lbm\_to\_kg}
$$

**Variables**

- $W$: tank weight, in $\mathrm{lbf}$
- $\dfrac{dW}{dt}$: tank-weight slope, in $\mathrm{lbf/s}$
- $g_{0,\mathrm{ft/s^2}}$: standard gravity conversion constant, $32.174\ \mathrm{ft/s^2}$
- $\mathrm{lbm\_to\_kg}$: pound-mass to kilogram conversion factor, $0.453592$
- $\dot{m}_{\mathrm{kg/s}}$: mass flow rate, in $\mathrm{kg/s}$

**User input**

1. Upload CSV file(s)
2. Select fuel and oxidizer tank weight channels

**Output**

1. Tank-based fuel/ox mass flow estimates are calculated
2. They are used as fallback/support flow information (especially for `O/F`)

### Total thrust

**Equation**

$$
F_{\mathrm{total,lbf}}(t)=\sum_i F_{i,\mathrm{lbf}}(t)
$$

**Variables**

- $F_{i,\mathrm{lbf}}$: thrust from the $i$th selected channel, in $\mathrm{lbf}$
- $F_{\mathrm{total,lbf}}$: summed total thrust at each time sample, in $\mathrm{lbf}$

**User input**

1. Upload CSV file(s)
2. Select one or more thrust channels

**Output**

1. `Total thrust (lbf)` is calculated as a time series
2. Total thrust can be plotted
3. Total thrust is used in `Isp` and `Cf` calculations

### Performance metrics (`Isp`, `C*`, `Cf`, `O/F`)

**Equations**

$$
F_{N}=F_{\mathrm{lbf}}\cdot 4.44822
$$

$$
P_{c,\mathrm{Pa}}=P_{c,\mathrm{psi}}\cdot 6894.76
$$

$$
I_{sp}=\frac{F_N}{\dot{m}_{\mathrm{total}}\,g_{0,\mathrm{m/s^2}}}
$$

$$
C^*=\frac{P_{c,\mathrm{Pa}}\,A^*}{\dot{m}_{\mathrm{total}}}
$$

$$
C_f=\frac{F_N}{P_{c,\mathrm{Pa}}\,A^*}
$$

$$
\frac{O}{F}=\frac{\dot{m}_{\mathrm{ox}}}{\dot{m}_{\mathrm{fuel}}}
$$

**Variables**

- $F_{\mathrm{lbf}}$: thrust in pounds-force ($\mathrm{lbf}$)
- $F_N$: thrust in Newtons ($\mathrm{N}$)
- $P_{c,\mathrm{psi}}$: chamber pressure in $\mathrm{psi}$
- $P_{c,\mathrm{Pa}}$: chamber pressure in $\mathrm{Pa}$
- $A^*$: nozzle throat area, in $\mathrm{m^2}$
- $\dot{m}_{\mathrm{total}}$: total mass flow rate, in $\mathrm{kg/s}$
- $g_{0,\mathrm{m/s^2}}$: standard gravity, $9.80665\ \mathrm{m/s^2}$
- $\dot{m}_{\mathrm{ox}}$, $\dot{m}_{\mathrm{fuel}}$: oxidizer and fuel mass flow rates, in $\mathrm{kg/s}$

**User input**

1. Upload CSV file(s)
2. Select thrust channel(s), chamber pressure channel, and flow source inputs
3. Enter throat area `A*`

**Output**

1. `Isp`, `C*`, `Cf`, and `O/F` are calculated
2. Metrics are available in Plot Metrics for graphing
3. Burn-time summaries and burn-window averages are shown above the analysis plot

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

This repository also contains a **Plotly Dash** version of the UI under `python_template/` (`python_template/app.py`, `python_template/dataApp.py`) and shared Python modules under `python_template/core/`. To run Dash locally:

```bash
pip install -r requirements.txt
cd python_template
python app.py
```

**Deploying the browser dashboard on Render (static):**

1. Create a **Static Site** (not a Web **Service** with Python).
2. Connect this repo, branch (e.g. `main`), **root directory = empty** (repository root).
3. **Build command: `true`** — type the three letters `true` and nothing else, **or** clear the build field.  
   **Do not use** `pip install -r requirements.txt` for the static `webapp`; that command is for the **Dash** app at the repo root, not the HTML/JS site.
4. **Publish directory** (or “static publish path”): **`webapp`**.

If your service already has `pip install -r requirements.txt` in **Build command**, open **Settings → Build & deploy**, change **Build command** to `true`, save, and **Clear build cache + deploy** (or **Manual deploy**). If the UI does not let you (wrong service type), create a new **Static Site** with the settings above, or use **Blueprint** and connect `render.yaml` from this repo.

**Repository layout (short):** `webapp/` — static dashboard; `python_template/` — Dash app and Python analysis modules; `data/` — sample CSV for Dash default load.

---

*Questions about your test program or data quality should go to your test lead or data owner; this file only documents how to use the dashboard software.*
