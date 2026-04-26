# HTML + JavaScript Dashboard

This folder contains a pure `HTML/CSS/JavaScript` version of the Dash app.

## Run

Because browsers block local-file requests in some environments, run a tiny local server from this folder:

```bash
python -m http.server 8080
```

Then open [http://localhost:8080](http://localhost:8080).

## Included functionality

- Multi-file CSV upload and merge on `Time (s)`
- Timeseries channel checklist with clear/reset
- Regression overlay and burn-time overlay on timeseries plot
- Performance analysis inputs and calculate flow
- Venturi-based `mdot` support and optional use for `Isp/C*`
- Analysis metric plotting with burn-time overlay
- Save/download both figures as images
