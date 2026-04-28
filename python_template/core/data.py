# Data processing functions
import io
import base64
import pandas as pd


def is_iso8601_series(series):
    sample = series.dropna().astype(str).str.strip()
    pattern = r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?([+-]\d{2}:\d{2}|Z)?$'
    return sample.str.match(pattern, na=False).all()


def _time_column_is_seconds(series: pd.Series) -> bool:
    """
    Detect if the time column is already in seconds (numeric) or datetime-like.
    Returns True if values are numeric (int/float), False if datetime/strings that need conversion.
    """
    if pd.api.types.is_numeric_dtype(series):
        return True
    # Try coercing to numeric; if most values convert, treat as seconds
    numeric = pd.to_numeric(series, errors="coerce")
    if numeric.notna().sum() >= max(1, len(series) * 0.9):
        return True
    return False


def _build_time_seconds_column(df: pd.DataFrame, time_col: str, x_col: str) -> None:
    """
    Set df[x_col] to elapsed time in seconds. Modifies df in place.
    - If time_col is already in seconds (numeric): use as-is.
    - If datetime-like: convert to elapsed seconds from first row.
    """
    if _time_column_is_seconds(df[time_col]):
        df[x_col] = pd.to_numeric(df[time_col], errors="coerce").astype(float)
    else:
        df[time_col] = pd.to_datetime(df[time_col])
        t0 = df[time_col].iloc[0]
        df[x_col] = (df[time_col] - t0).dt.total_seconds()


def process_file(file_name: str):
    df = pd.read_csv(file_name)
    X_COL = "Time (s)"

    TIME_COLS = [
        col for col in df.columns
        if any(keyword.lower() in col.lower()
               for keyword in ['time', 'timestamp'])
    ]

    iso_cols = [col for col in df.columns if is_iso8601_series(df[col])]

    if TIME_COLS:
        if iso_cols:
            TIME_COL = iso_cols[0]
        else:
            TIME_COL = TIME_COLS[0]

        _build_time_seconds_column(df, TIME_COL, X_COL)
        T_MIN = float(df[X_COL].min())
        T_MAX = float(df[X_COL].max())
    else:
        # Fallback if no time column found
        TIME_COL = df.columns[0]
        df[X_COL] = df.index.astype(float)
        T_MIN = float(df[X_COL].min())
        T_MAX = float(df[X_COL].max())

    return df, TIME_COL, T_MIN, T_MAX, X_COL


def process_file_content(content: str, filename: str):
    """
    Process CSV from uploaded file content (base64 string from dcc.Upload).
    Returns same as process_file: (df, TIME_COL, T_MIN, T_MAX, X_COL).
    """
    if content is None:
        raise ValueError("File content is empty")
    if isinstance(content, str) and content.startswith("data:"):
        content = content.split(",", 1)[-1]
    if not content or (isinstance(content, str) and not content.strip()):
        raise ValueError("File content is empty")

    # Decode: try base64 first (dcc.Upload usually sends base64), then raw bytes/string
    try:
        decoded = base64.b64decode(content)
    except Exception:
        decoded = content.encode("utf-8") if isinstance(content, str) else content
    if not decoded:
        raise ValueError("File content is empty")

    # Try encodings: UTF-8 first, then Windows-1252/Latin-1 (common for CSVs with ° etc.)
    for encoding in ("utf-8", "cp1252", "latin-1"):
        try:
            df = pd.read_csv(io.BytesIO(decoded), encoding=encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError("Could not decode file as UTF-8, CP1252, or Latin-1")

    if df.empty or len(df.columns) == 0:
        raise ValueError("CSV has no data or no columns")

    X_COL = "Time (s)"
    TIME_COLS = [
        col for col in df.columns
        if any(keyword.lower() in col.lower() for keyword in ["time", "timestamp"])
    ]
    iso_cols = [col for col in df.columns if is_iso8601_series(df[col])]
    if TIME_COLS:
        if iso_cols:
            TIME_COL = iso_cols[0]
        else:
            TIME_COL = TIME_COLS[0]
        _build_time_seconds_column(df, TIME_COL, X_COL)
        T_MIN = float(df[X_COL].min())
        T_MAX = float(df[X_COL].max())
    else:
        TIME_COL = df.columns[0]
        df[X_COL] = df.index.astype(float)
        T_MIN = float(df[X_COL].min())
        T_MAX = float(df[X_COL].max())
    return df, TIME_COL, T_MIN, T_MAX, X_COL


def merge_dataframes_on_time(list_of_tuples):
    """
    list_of_tuples: [(df, TIME_COL, T_MIN, T_MAX, X_COL), ...]
    Merge on X_COL (outer). Duplicate column names get suffixed with _1, _2, ...
    Returns (merged_df, X_COL, T_MIN, T_MAX).
    """
    X_COL = "Time (s)"
    if not list_of_tuples:
        return pd.DataFrame(), X_COL, 0.0, 0.0
    if len(list_of_tuples) == 1:
        df, _, T_MIN, T_MAX, _ = list_of_tuples[0]
        return df.copy(), X_COL, T_MIN, T_MAX

    merged = None
    t_min_all, t_max_all = float("inf"), float("-inf")
    for i, (df, _time_col, T_MIN, T_MAX, _xcol) in enumerate(list_of_tuples):
        t_min_all = min(t_min_all, T_MIN)
        t_max_all = max(t_max_all, T_MAX)
        if merged is None:
            merged = df.copy()
            continue
        other_cols = [c for c in df.columns if c != X_COL]
        rename = {}
        for c in other_cols:
            if c in merged.columns:
                rename[c] = f"{c}_{i}"
        right = df.rename(columns=rename)
        merged = pd.merge_ordered(merged, right[[X_COL] + list(right.columns.difference([X_COL]))], on=X_COL, how="outer")
    merged = merged.sort_values(X_COL).reset_index(drop=True)

    # Interpolate NaNs at merged time points so both files' signals have values at every time
    # (pressure and load cell often have different sampling times, so outer merge leaves gaps)
    if len(merged) > 0:
        merged = merged.set_index(X_COL)
        for col in merged.columns:
            if pd.api.types.is_numeric_dtype(merged[col]) and merged[col].isna().any():
                merged[col] = merged[col].interpolate(method="index", limit_direction="both")
        merged = merged.reset_index()

    return merged, X_COL, t_min_all, t_max_all

