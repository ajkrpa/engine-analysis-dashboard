# Rocket performance analysis: total thrust, mass flow, Isp, Cf, C*
# Expected input units (converted internally as below):
#   Thrust channels: lbf → N for Isp   |   Chamber pressure: psi → Pa for Cf, C*
#   Tank weights: lbf (slope → mass flow in kg/s)   |   A*: m²
# Outputs: Total thrust (lbf), Isp (s), Cf (dimensionless), C* (m/s)
from typing import Optional

import numpy as np
import pandas as pd
from scipy.signal import find_peaks

# Unit conversions (imperial → SI)
LBF_TO_N = 4.44822
PSI_TO_PA = 6894.76  # pressure must be in psi; converted to Pa for calculations
LBM_TO_KG = 0.453592
G0_FT_S2 = 32.174  # lbf/lbm for mass flow from weight slope
G0_M_S2 = 9.80665  # Isp definition


def mass_flow_venturi_incompressible_kg_s(
    delta_p_pa: np.ndarray,
    rho_kg_m3: np.ndarray,
    cda_m2: float,
    beta: float,
) -> np.ndarray:
    """
    Incompressible venturi mass flow (kg/s):

        m_dot = (C_d A) * sqrt( 2 * (P1 - P2) * rho / (1 - beta^4) )

    delta_p_pa: |P1 - P2| in Pa (same length as rho).
    rho_kg_m3: fluid density in kg/m^3.
    cda_m2: effective area C_d * A_2 (m^2). beta = d2/D1 for the (1 - beta^4) term.
    """
    delta_p_pa = np.asarray(delta_p_pa, dtype=float)
    rho_kg_m3 = np.asarray(rho_kg_m3, dtype=float)
    n = len(delta_p_pa)
    out = np.full(n, np.nan, dtype=float)
    if n == 0 or len(rho_kg_m3) != n:
        return out
    try:
        cda = float(cda_m2)
        b = float(beta)
    except (TypeError, ValueError):
        return out
    if not (np.isfinite(cda) and np.isfinite(b)):
        return out
    if cda <= 0 or b <= 0 or b >= 1.0:
        return out
    denom = 1.0 - b**4
    if denom <= 0:
        return out
    dp = np.maximum(delta_p_pa, 0.0)
    rho = np.maximum(rho_kg_m3, 0.0)
    inner = 2.0 * dp * rho / denom
    inner = np.maximum(inner, 0.0)
    mask = np.isfinite(inner) & (inner > 0) & np.isfinite(rho) & (rho > 0)
    out[mask] = cda * np.sqrt(inner[mask])
    return out


def compute_venturi_mass_flow_series_kg_s(
    df: pd.DataFrame,
    mode: str,
    col_dp: Optional[str],
    col_p1: Optional[str],
    col_p2: Optional[str],
    rho_const_kg_m3: Optional[float],
    cda_m2: float,
    beta: float,
) -> pd.Series:
    """
    Per-row venturi mass flow (kg/s) from CSV columns.
    mode: 'dp_psi' — one channel already ΔP (psi); col_dp required.
    mode: 'p1p2_psi' — col_p1 = inlet static, col_p2 = throat static (psi); ΔP = |P_inlet − P_throat|.
    rho_const_kg_m3: constant density (kg/m^3) for this propellant.
    cda_m2: C_d * A_2 (m^2). beta: d2/D1.
    """
    idx = df.index
    n = len(df)
    if n == 0:
        return pd.Series(dtype=float)
    delta_pa = np.full(n, np.nan, dtype=float)
    if mode == "dp_psi" and col_dp and col_dp in df.columns:
        dp_psi = df[col_dp].astype(float).values
        delta_pa = np.abs(dp_psi) * PSI_TO_PA
    elif mode == "p1p2_psi" and col_p1 and col_p2 and col_p1 in df.columns and col_p2 in df.columns:
        p1 = df[col_p1].astype(float).values
        p2 = df[col_p2].astype(float).values
        delta_pa = np.abs(p1 - p2) * PSI_TO_PA
    else:
        return pd.Series(np.nan, index=idx)

    try:
        rc = float(rho_const_kg_m3) if rho_const_kg_m3 is not None and rho_const_kg_m3 != "" else np.nan
    except (TypeError, ValueError):
        rc = np.nan
    if not np.isfinite(rc) or rc <= 0:
        return pd.Series(np.nan, index=idx)
    rho = np.full(n, rc, dtype=float)

    mdot = mass_flow_venturi_incompressible_kg_s(delta_pa, rho, cda_m2, beta)
    return pd.Series(mdot, index=idx)


def recompute_isp_cstar_with_mdot_total_series(
    perf: pd.DataFrame,
    total_thrust: pd.Series,
    chamber_pressure_psi: Optional[pd.Series],
    A_star_m2: float,
    m_dot_total_kg_s: pd.Series,
) -> pd.DataFrame:
    """Overwrite Isp and C* using time-varying total mass flow (kg/s), aligned to perf.index."""
    perf = perf.copy()
    mdot = m_dot_total_kg_s.reindex(perf.index).astype(float)
    F_N = total_thrust.reindex(perf.index).astype(float) * LBF_TO_N
    perf["Isp (s)"] = np.where(mdot > 0, F_N / (mdot * G0_M_S2), np.nan)
    if (
        chamber_pressure_psi is not None
        and len(chamber_pressure_psi) > 0
        and A_star_m2
        and float(A_star_m2) > 0
    ):
        Pc_psi = chamber_pressure_psi.reindex(perf.index).astype(float)
        Pc_Pa = Pc_psi * PSI_TO_PA
        perf["C* (m/s)"] = np.where(mdot > 0, (Pc_Pa * float(A_star_m2)) / mdot, np.nan)
    else:
        perf["C* (m/s)"] = np.nan
    return perf


def _moving_average(signal_vals: np.ndarray, window: int) -> np.ndarray:
    """Simple centered moving average with odd window size."""
    signal_vals = np.asarray(signal_vals, dtype=float)
    n = len(signal_vals)
    if n == 0:
        return signal_vals
    w = int(max(1, window))
    if w % 2 == 0:
        w += 1
    w = min(w, n if n % 2 == 1 else max(1, n - 1))
    if w <= 1:
        return signal_vals
    kernel = np.ones(w, dtype=float) / float(w)
    return np.convolve(signal_vals, kernel, mode="same")


def detect_burn_window_peak_bases(
    time_vals: np.ndarray,
    signal_vals: np.ndarray,
    prominence_fraction: float = 0.12,
    height_fraction: float = 0.05,
) -> tuple[float, float]:
    """
    Detect burn window from dominant peak bases (not peak centers).
    This is better for broad/flat burn-rate humps where peak timestamps
    under-estimate true start and end.
    """
    time_vals = np.asarray(time_vals, dtype=float)
    signal_vals = np.asarray(signal_vals, dtype=float)
    if len(time_vals) == 0 or len(signal_vals) == 0 or len(time_vals) != len(signal_vals):
        return np.nan, np.nan
    sig_min, sig_max = np.nanmin(signal_vals), np.nanmax(signal_vals)
    sig_span = sig_max - sig_min
    if not np.isfinite(sig_max) or sig_span <= 0:
        return np.nan, np.nan
    try:
        peaks, props = find_peaks(
            signal_vals,
            prominence=sig_span * prominence_fraction,
            height=sig_min + sig_span * height_fraction,
        )
    except (ValueError, TypeError):
        return np.nan, np.nan
    if len(peaks) == 0:
        return np.nan, np.nan
    prominences = props.get("prominences", np.empty(0))
    left_bases = props.get("left_bases", np.empty(0, dtype=int))
    right_bases = props.get("right_bases", np.empty(0, dtype=int))
    if len(prominences) != len(peaks) or len(left_bases) != len(peaks) or len(right_bases) != len(peaks):
        return np.nan, np.nan

    # Use the most prominent feature to represent the burn event.
    i = int(np.argmax(prominences))
    left_i = int(left_bases[i])
    right_i = int(right_bases[i])
    if right_i <= left_i:
        return np.nan, np.nan
    return float(time_vals[left_i]), float(time_vals[right_i])


def detect_burn_window(
    time_vals: np.ndarray,
    signal_vals: np.ndarray,
    threshold_fraction: float = 0.1,
) -> tuple[float, float]:
    """
    Detect burn start and end from a thrust or pressure signal.
    Burn is assumed when signal is above threshold_fraction * max(signal).
    Returns (t_start, t_end) in same units as time_vals, or (np.nan, np.nan) if no burn.
    """
    time_vals = np.asarray(time_vals, dtype=float)
    signal_vals = np.asarray(signal_vals, dtype=float)
    if len(time_vals) == 0 or len(signal_vals) == 0 or len(time_vals) != len(signal_vals):
        return np.nan, np.nan
    sig_max = np.nanmax(signal_vals)
    if not np.isfinite(sig_max) or sig_max <= 0:
        return np.nan, np.nan
    threshold = threshold_fraction * sig_max
    above = np.where(np.isfinite(signal_vals) & (signal_vals >= threshold))[0]
    if len(above) == 0:
        return np.nan, np.nan
    t_start = float(np.nanmin(time_vals[above]))
    t_end = float(np.nanmax(time_vals[above]))
    return t_start, t_end


def detect_burn_window_two_spikes(
    time_vals: np.ndarray,
    signal_vals: np.ndarray,
    window_frac: float = 0.05,
    min_peaks: int = 2,
) -> tuple[float, float]:
    """
    Detect burn window as the time between the two largest spikes (by y-axis value).
    Finds all peaks, selects the two with the largest signal value, and returns
    (earliest time, latest time) as the burn window.
    Returns (t_start, t_end) or (np.nan, np.nan) if fewer than two peaks.
    """
    time_vals = np.asarray(time_vals, dtype=float)
    signal_vals = np.asarray(signal_vals, dtype=float)
    n = len(signal_vals)
    if len(time_vals) != n or n < 3:
        return np.nan, np.nan
    sig_min, sig_max = np.nanmin(signal_vals), np.nanmax(signal_vals)
    if not np.isfinite(sig_max) or (sig_max - sig_min) <= 0:
        return np.nan, np.nan
    try:
        peaks, _ = find_peaks(
            signal_vals,
            prominence=(sig_max - sig_min) * 0.03,
            height=sig_min + (sig_max - sig_min) * 0.02,
        )
    except (ValueError, TypeError):
        return np.nan, np.nan
    if len(peaks) < min_peaks:
        return np.nan, np.nan
    # Sort by y-axis value (signal at peak) descending; take the two largest spikes
    sorted_idx = np.argsort(signal_vals[peaks])[::-1]
    top_two_peaks = peaks[sorted_idx[:min_peaks]]
    peak_times = time_vals[top_two_peaks]
    t_start = float(np.min(peak_times))
    t_end = float(np.max(peak_times))
    return t_start, t_end


def detect_burn_window_peaks(
    time_vals: np.ndarray,
    signal_vals: np.ndarray,
    prominence_fraction: float = 0.15,
    min_peaks: int = 2,
) -> tuple[float, float]:
    """
    Detect burn start and end from startup/shutdown spikes (two major peaks).
    Finds peaks in the signal, selects the two with largest prominence, and
    returns (time of first peak, time of second peak) as the burn window.
    Returns (np.nan, np.nan) if fewer than two peaks found.
    """
    time_vals = np.asarray(time_vals, dtype=float)
    signal_vals = np.asarray(signal_vals, dtype=float)
    if len(time_vals) == 0 or len(signal_vals) == 0 or len(time_vals) != len(signal_vals):
        return np.nan, np.nan
    sig_min, sig_max = np.nanmin(signal_vals), np.nanmax(signal_vals)
    if not np.isfinite(sig_max) or (sig_max - sig_min) <= 0:
        return np.nan, np.nan
    prominence_min = (sig_max - sig_min) * prominence_fraction
    try:
        peaks, properties = find_peaks(
            signal_vals,
            prominence=prominence_min,
            height=sig_min + (sig_max - sig_min) * 0.05,
        )
    except (ValueError, TypeError):
        return np.nan, np.nan
    if len(peaks) < min_peaks:
        return np.nan, np.nan
    prominences = properties.get("prominences", np.empty(0))
    if len(prominences) != len(peaks):
        return np.nan, np.nan
    # Take the two peaks with largest prominence (startup and shutdown spikes)
    top_two_idx = np.argsort(prominences)[-min_peaks:]
    peak_indices = peaks[top_two_idx]
    peak_times = time_vals[peak_indices]
    t_start = float(np.min(peak_times))
    t_end = float(np.max(peak_times))
    return t_start, t_end


def get_burn_window(
    df: pd.DataFrame,
    time_col: str,
    burn_signal: pd.Series,
    threshold_fraction: float = 0.1,
    burn_method: str = "peaks",
) -> tuple[float, float]:
    """
    Get burn start and end times from a thrust (or pressure) signal.
    Uses same logic as mass-flow burn window: peaks then threshold fallback.
    Returns (t_start, t_end) in same units as time_col, or (np.nan, np.nan) if no burn.
    """
    if time_col not in df.columns or burn_signal is None or len(burn_signal) == 0:
        return np.nan, np.nan
    time_vals = df[time_col].values.astype(float)
    if burn_signal.index.equals(df.index):
        sig_vals = burn_signal.values.astype(float)
    else:
        sig_vals = np.asarray(burn_signal.reindex(df.index).values, dtype=float)
    if burn_method == "peaks":
        t_start, t_end = detect_burn_window_peaks(time_vals, sig_vals)
        if not (np.isfinite(t_start) and np.isfinite(t_end)):
            t_start, t_end = detect_burn_window(
                time_vals, sig_vals, threshold_fraction=threshold_fraction
            )
    else:
        t_start, t_end = detect_burn_window(
            time_vals, sig_vals, threshold_fraction=threshold_fraction
        )
    return t_start, t_end


def get_burn_window_from_spike_signal(
    df: pd.DataFrame,
    time_col: str,
    signal_col: str,
    window_frac: float = 0.05,
) -> tuple[float, float]:
    """
    Get burn window as time between the two largest spikes in the signal.
    'Largest' = spike value minus average of surrounding points.
    signal_col: column name (e.g. thrust, pressure) that has two massive spikes.
    """
    if time_col not in df.columns or signal_col not in df.columns:
        return np.nan, np.nan
    time_vals = df[time_col].values.astype(float)
    sig_vals = df[signal_col].values.astype(float)
    return detect_burn_window_two_spikes(time_vals, sig_vals, window_frac=window_frac, min_peaks=2)


def get_burn_window_from_weight(
    df: pd.DataFrame,
    time_col: str,
    weight_col: str,
    threshold_fraction: float = 0.1,
) -> tuple[float, float]:
    """
    Get burn start and end times from a tank weight column (weight decreases during burn).
    Uses negative derivative (-dW/dt) as burn-rate signal: tries peak detection (two peaks
    for start/end of drop), then threshold fallback where rate > threshold * max(rate).
    Returns (t_start, t_end) or (np.nan, np.nan) if detection fails.
    """
    if time_col not in df.columns or weight_col not in df.columns:
        return np.nan, np.nan
    time_vals = np.asarray(df[time_col].values, dtype=float)
    weight_vals = np.asarray(df[weight_col].values, dtype=float)
    n = len(time_vals)
    if n < 3:
        return np.nan, np.nan
    dt = np.diff(time_vals)
    dw = np.diff(weight_vals)
    # Avoid div by zero; burn rate = -dW/dt (positive when weight decreases)
    with np.errstate(divide="ignore", invalid="ignore"):
        rate = np.where(dt > 0, -dw / dt, 0.0)
    rate = np.asarray(rate, dtype=float)
    t_mid = 0.5 * (time_vals[:-1] + time_vals[1:])
    rate_max = np.nanmax(rate)
    if not np.isfinite(rate_max) or rate_max <= 0:
        return np.nan, np.nan
    # Smooth rate to suppress high-frequency noise before peak/boundary detection.
    smooth_window = max(5, int(n * 0.01))
    rate_smooth = _moving_average(rate, smooth_window)

    # Preferred: detect dominant burn-rate feature and use its left/right bases.
    t_start, t_end = detect_burn_window_peak_bases(
        t_mid, rate_smooth, prominence_fraction=0.12, height_fraction=0.05
    )
    if np.isfinite(t_start) and np.isfinite(t_end) and t_end > t_start:
        return t_start, t_end

    # Fallback: threshold on smoothed rate
    rate_smooth_max = np.nanmax(rate_smooth)
    if not np.isfinite(rate_smooth_max) or rate_smooth_max <= 0:
        return np.nan, np.nan
    threshold = threshold_fraction * rate_smooth_max
    above = np.where(np.isfinite(rate_smooth) & (rate_smooth >= threshold))[0]
    if len(above) == 0:
        return np.nan, np.nan
    t_start = float(np.nanmin(t_mid[above]))
    t_end = float(np.nanmax(t_mid[above]))
    return t_start, t_end


def get_flow_window_from_tank_weights(
    df: pd.DataFrame,
    time_col: str,
    fuel_weight_col: str,
    ox_weight_col: str,
    threshold_fraction: float = 0.1,
) -> tuple[float, float]:
    """
    Detect propellant flow window from tank-weight channels.
    Uses weight-derived windows (from -dW/dt features) and combines both tanks:
    - start = earliest valid start among fuel/ox
    - end = latest valid end among fuel/ox
    """
    windows = []
    for col in (fuel_weight_col, ox_weight_col):
        if col and col in df.columns:
            t_s, t_e = get_burn_window_from_weight(
                df, time_col, col, threshold_fraction=threshold_fraction
            )
            if np.isfinite(t_s) and np.isfinite(t_e) and t_e > t_s:
                windows.append((float(t_s), float(t_e)))
    if not windows:
        return np.nan, np.nan
    starts = [w[0] for w in windows]
    ends = [w[1] for w in windows]
    return float(np.min(starts)), float(np.max(ends))


def get_burn_window_from_loadcell_spike(
    df: pd.DataFrame,
    time_col: str,
    load_signal: pd.Series,
    smooth_fraction: float = 0.01,
) -> tuple[float, float]:
    """
    Detect burn window from the high-thrust region around the maximum load-cell peak.
    Method:
    - Smooth signal
    - Find global maximum peak
    - Define a "high" threshold near the peak level
    - Start/end are the first/last samples in the contiguous high region containing the peak
    """
    if time_col not in df.columns or load_signal is None or len(load_signal) == 0:
        return np.nan, np.nan
    time_vals = np.asarray(df[time_col].values, dtype=float)
    if load_signal.index.equals(df.index):
        sig_vals = np.asarray(load_signal.values, dtype=float)
    else:
        sig_vals = np.asarray(load_signal.reindex(df.index).values, dtype=float)
    if len(time_vals) != len(sig_vals) or len(sig_vals) < 3:
        return np.nan, np.nan
    n = len(sig_vals)
    smooth_window = max(5, int(n * max(0.0, smooth_fraction)))
    sig_smooth = _moving_average(sig_vals, smooth_window)
    valid = np.isfinite(sig_smooth)
    if not np.any(valid):
        return np.nan, np.nan

    # Peak-centered high-level window to avoid low-force tails being detected as burn.
    peak_idx = int(np.nanargmax(sig_smooth))
    peak_val = float(sig_smooth[peak_idx])
    if not np.isfinite(peak_val):
        return np.nan, np.nan
    baseline = float(np.nanpercentile(sig_smooth[valid], 5))
    span = peak_val - baseline
    if not np.isfinite(span) or span <= 0:
        return np.nan, np.nan

    # Use asymmetric thresholds to avoid overly small windows:
    # - start threshold closer to peak (captures ignition near maximum)
    # - end threshold looser (captures trailing high-thrust region before decay)
    start_fraction = 0.90
    end_fraction = 0.75
    start_threshold = baseline + start_fraction * span
    end_threshold = baseline + end_fraction * span
    start_mask = np.isfinite(sig_smooth) & (sig_smooth >= start_threshold)
    end_mask = np.isfinite(sig_smooth) & (sig_smooth >= end_threshold)
    if not end_mask[peak_idx]:
        return np.nan, np.nan

    start_idx = peak_idx
    while start_idx > 0 and start_mask[start_idx - 1]:
        start_idx -= 1
    end_idx = peak_idx
    while end_idx < (n - 1) and end_mask[end_idx + 1]:
        end_idx += 1

    t_start = float(time_vals[start_idx])
    t_end = float(time_vals[end_idx])
    if np.isfinite(t_start) and np.isfinite(t_end) and t_end > t_start:
        return t_start, t_end

    # Fallback if the high-region method is too narrow on noisy datasets.
    return detect_burn_window(time_vals, sig_smooth, threshold_fraction=0.1)


def compute_total_thrust(df: pd.DataFrame, thrust_columns: list) -> pd.Series:
    """
    Sum selected thrust channel columns to get total thrust.
    Assumes each column is in lbf; result is in lbf.
    """
    if not thrust_columns:
        return pd.Series(dtype=float)
    valid = [c for c in thrust_columns if c in df.columns]
    if not valid:
        return pd.Series(dtype=float)
    return df[valid].sum(axis=1)


def compute_mass_flow_from_tank_weights(
    df: pd.DataFrame,
    time_col: str,
    fuel_weight_col: str,
    ox_weight_col: str,
    burn_signal: Optional[pd.Series] = None,
    burn_threshold_fraction: float = 0.1,
    burn_method: str = "peaks",
    burn_t_start: Optional[float] = None,
    burn_t_end: Optional[float] = None,
) -> tuple[float, float]:
    """
    Linear regression of tank weight vs time over the burn window; returns
    the raw slopes dW/dt for fuel and oxidizer in lbf/s.

    If burn_signal is provided (e.g. total thrust), only the period when the signal
    indicates burn is used for the regression (so slope = mass flow during hot fire only).
    burn_method: "peaks" = two main spikes (startup/shutdown), "threshold" = signal above
    fraction of max. Returns (slope_fuel_lbf_s, slope_ox_lbf_s).
    """
    if time_col not in df.columns or not fuel_weight_col or not ox_weight_col:
        return np.nan, np.nan
    if fuel_weight_col not in df.columns or ox_weight_col not in df.columns:
        return np.nan, np.nan

    MIN_BURN_POINTS = 10  # need enough points for a stable regression; else use threshold window
    explicit_window_valid = (
        burn_t_start is not None and burn_t_end is not None
        and np.isfinite(burn_t_start) and np.isfinite(burn_t_end)
        and float(burn_t_end) > float(burn_t_start)
    )
    if explicit_window_valid:
        time_vals = df[time_col].values.astype(float)
        mask = (time_vals >= float(burn_t_start)) & (time_vals <= float(burn_t_end))
        n_burn = np.sum(mask)
        if n_burn >= 2:
            df = df.iloc[np.where(mask)[0]]
    elif burn_signal is not None and len(burn_signal) > 0:
        # Restrict to burn window so regression is only over actual firing
        time_vals = df[time_col].values.astype(float)
        if burn_signal.index.equals(df.index):
            sig_vals = burn_signal.values.astype(float)
        else:
            sig_vals = np.asarray(burn_signal.reindex(df.index).values, dtype=float)
        t_start, t_end = np.nan, np.nan
        if burn_method == "peaks":
            t_start, t_end = detect_burn_window_peaks(time_vals, sig_vals)
            if np.isfinite(t_start) and np.isfinite(t_end):
                # If peak window has too few points, regression is unreliable; use threshold
                mask_peaks = (time_vals >= t_start) & (time_vals <= t_end)
                if np.sum(mask_peaks) < MIN_BURN_POINTS:
                    t_start, t_end = np.nan, np.nan
            if not (np.isfinite(t_start) and np.isfinite(t_end)):
                t_start, t_end = detect_burn_window(
                    time_vals, sig_vals, threshold_fraction=burn_threshold_fraction
                )
        else:
            t_start, t_end = detect_burn_window(
                time_vals, sig_vals, threshold_fraction=burn_threshold_fraction
            )
        if not (np.isfinite(t_start) and np.isfinite(t_end)):
            t_start, t_end = detect_burn_window(
                time_vals, sig_vals, threshold_fraction=burn_threshold_fraction
            )
        if np.isfinite(t_start) and np.isfinite(t_end) and t_end > t_start:
            mask = (time_vals >= t_start) & (time_vals <= t_end)
            n_burn = np.sum(mask)
            if n_burn >= max(2, MIN_BURN_POINTS):
                df = df.iloc[np.where(mask)[0]]
            elif n_burn >= 2:
                # use narrow window only if threshold didn't give one
                df = df.iloc[np.where(mask)[0]]
        # else: fall back to full df (e.g. no clear burn detected)
    t = df[time_col].values.astype(float)
    w_fuel = df[fuel_weight_col].values.astype(float)
    w_ox = df[ox_weight_col].values.astype(float)
    # Drop rows where weight is NaN so regression is valid
    valid = np.isfinite(t) & np.isfinite(w_fuel) & np.isfinite(w_ox)
    if np.sum(valid) < 2:
        return np.nan, np.nan
    t, w_fuel, w_ox = t[valid], w_fuel[valid], w_ox[valid]

    # Linear regression: weight = slope * t + intercept
    # slope in lbf/s (weight decreasing → negative slope)
    def slope_lbf_per_s(x, y):
        if len(x) < 2:
            return np.nan
        coeffs = np.polyfit(x, y, 1)
        return coeffs[0]

    slope_fuel = slope_lbf_per_s(t, w_fuel)  # lbf/s
    slope_ox = slope_lbf_per_s(t, w_ox)      # lbf/s
    return float(slope_fuel), float(slope_ox)


def compute_performance_series(
    df: pd.DataFrame,
    time_col: str,
    total_thrust: pd.Series,
    chamber_pressure_col: str,
    A_star_m2: float,
    m_dot_fuel_kg_s: float,
    m_dot_ox_kg_s: float,
) -> pd.DataFrame:
    """
    Compute time series of Total thrust (lbf), Isp (s), Cf, C* (m/s).
    Assumes: thrust in lbf, chamber pressure in psi, A* in m², mass flows in kg/s.

    Equations used:
    - Isp (specific impulse, s):  Isp = F / (ṁ_total * g0)
      where F = thrust (N), ṁ_total = total mass flow (kg/s), g0 = 9.80665 m/s².
      Thrust is converted from lbf to N; result is in seconds.

    - C* (characteristic velocity, m/s):  C* = (Pc * A*) / ṁ_total
      where Pc = chamber pressure (Pa), A* = throat area (m²), ṁ_total (kg/s).
      Pc is converted from psi to Pa; C* is in m/s.

    - Cf (thrust coefficient, dimensionless):  Cf = F / (Pc * A*)
      where F = thrust (N), Pc = chamber pressure (Pa), A* = throat area (m²).
      Ratio of thrust to reference force Pc*A*.
    """
    result = pd.DataFrame(index=df.index)
    result[time_col] = df[time_col]

    # Total thrust (keep in lbf for display)
    result["Total thrust (lbf)"] = total_thrust

    m_dot_total_kg_s = m_dot_fuel_kg_s + m_dot_ox_kg_s
    if m_dot_total_kg_s <= 0 or not np.isfinite(m_dot_total_kg_s):
        result["Isp (s)"] = np.nan
        result["C* (m/s)"] = np.nan
    else:
        F_N = total_thrust * LBF_TO_N
        result["Isp (s)"] = F_N / (m_dot_total_kg_s * G0_M_S2)

        if chamber_pressure_col and chamber_pressure_col in df.columns:
            Pc_psi = df[chamber_pressure_col].astype(float)
            Pc_Pa = Pc_psi * PSI_TO_PA
            result["C* (m/s)"] = (Pc_Pa * A_star_m2) / m_dot_total_kg_s
        else:
            result["C* (m/s)"] = np.nan

    if A_star_m2 and A_star_m2 > 0 and chamber_pressure_col and chamber_pressure_col in df.columns:
        Pc_psi = df[chamber_pressure_col].astype(float)
        Pc_Pa = Pc_psi * PSI_TO_PA
        F_N = total_thrust * LBF_TO_N
        F_ref_N = Pc_Pa * A_star_m2
        result["Cf"] = np.where(F_ref_N > 0, F_N / F_ref_N, np.nan)
    else:
        result["Cf"] = np.nan

    return result
