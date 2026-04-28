# Functions for manipulating GUI
import pandas as pd
from dash import ctx


def get_time_filtered_df(time_range, start_val, end_val, T_MIN, T_MAX, df, X_COL):
    '''
    Gets the time filtered dataframe based on the last triggered time element.
    '''
    trigger = ctx.triggered_id

    t_start, t_end = T_MIN, T_MAX

    if trigger == 'reset-button':
        df_filtered = df.copy()
    elif trigger == 'time-range-slider' and time_range is not None:
        t_start, t_end = time_range
        df_filtered = df[(df[X_COL] >= t_start) & (df[X_COL] <= t_end)]
    else:
        if time_range is not None and len(time_range) == 2:
            t_start, t_end = time_range
        elif start_val is not None or end_val is not None:
            t_start = start_val if start_val is not None else T_MIN
            t_end = end_val if end_val is not None else T_MAX
        df_filtered = df[(df[X_COL] >= t_start) & (df[X_COL] <= t_end)]

    return trigger, df_filtered, t_start, t_end

def y_axis_label(selected_data):
    if not selected_data:
        return "Value"

    # Explicit override requested for specific uploaded channel naming conventions.
    selected_names = " ".join(str(c).lower() for c in selected_data)
    if "deg [unit" in selected_names or "deg f" in selected_names:
        return "Temperature (deg [unit])"

    pressure_keywords = ['pt', 'psi', 'pressure', 'pa', 'bar']
    load_keywords = ['lc', 'load', 'cell', 'thrust', 'weight', 'lbf']
    temp_keywords = ['tc', 'temp', 'thermocouple']
    temp_unit_indicators = ['c', 'f', 'k']  # °C, °F, K or _C, _F, etc.

    def is_pressure_column(col):
        return any(kw in col.lower() for kw in pressure_keywords)

    def is_load_column(col):
        return any(kw in col.lower() for kw in load_keywords)

    def is_temperature_column(col):
        col_lower = col.lower()
        has_temp = any(kw in col_lower for kw in temp_keywords)
        has_unit = any(u in col_lower for u in temp_unit_indicators)
        return has_temp and has_unit

    def pressure_unit(cols):
        """Return unit string for pressure (psi, Pa, or bar) from column names."""
        cols_lower = " ".join(c.lower() for c in cols)
        if "psi" in cols_lower:
            return "psi"
        if "pa" in cols_lower:
            return "Pa"
        if "bar" in cols_lower:
            return "bar"
        return "psi"

    def temperature_unit(cols):
        cols_lower = " ".join(c.lower() for c in cols)
        if "f" in cols_lower or "°f" in cols_lower:
            return "°F"
        if "k" in cols_lower:
            return "K"
        return "°C"

    has_pressure = any(is_pressure_column(c) for c in selected_data)
    has_load = any(is_load_column(c) for c in selected_data)
    has_temperature = any(is_temperature_column(c) for c in selected_data)
    types_present = sum([has_pressure, has_load, has_temperature])

    # Single type: keep existing labels
    if types_present == 1:
        if has_pressure:
            return f"Pressure ({pressure_unit(selected_data)})"
        if has_load:
            return "Weight (lbf)"
        if has_temperature:
            return f"Temperature ({temperature_unit(selected_data)})"
        return ", ".join(selected_data)

    # Multiple types: list each with unit in order Pressure, Temperature, Weight
    labels = []
    if has_pressure:
        labels.append(f"Pressure ({pressure_unit(selected_data)})")
    if has_temperature:
        labels.append(f"Temperature ({temperature_unit(selected_data)})")
    if has_load:
        labels.append("Weight (lbf)")
    if labels:
        return ", ".join(labels)

    # Fallback: not clearly pressure/load/temperature
    all_pressure = all(is_pressure_column(c) for c in selected_data)
    all_load = all(is_load_column(c) for c in selected_data)
    all_temperature = all(is_temperature_column(c) for c in selected_data)
    if all_pressure:
        return f"Pressure ({pressure_unit(selected_data)})"
    if all_load:
        return "Weight (lbf)"
    if all_temperature:
        return f"Temperature ({temperature_unit(selected_data)})"
    return ", ".join(selected_data)


