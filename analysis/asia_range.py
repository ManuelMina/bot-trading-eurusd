"""
Calcula el rango Asia diario (High/Low) para cada dia operativo.

Rango Asia definido por la estrategia:
    19:00 - 00:00 hora Colombia (UTC-5, sin DST)
    = 00:00 - 05:00 UTC del mismo dia calendario UTC

Para un dia de trading D (Colombia), el rango Asia se forma con las velas
M1 entre 00:00 UTC y 04:59 UTC de la fecha D.

Uso:
    from data.fetcher import load
    from analysis.asia_range import compute, get_for_date

    m1 = load("EURUSD", "M1", 2024)
    asia = compute(m1)
    row = get_for_date(asia, date(2024, 3, 15))
"""

from datetime import date

import pandas as pd

# 00:00 UTC = 19:00 Colombia (inicio rango Asia)
# 05:00 UTC = 00:00 Colombia (fin rango Asia, exclusive)
_ASIA_UTC_START = 0
_ASIA_UTC_END   = 5


def compute(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calcula el rango Asia para cada dia operativo presente en df.

    Parameters
    ----------
    df : DataFrame con columnas datetime (UTC tz-aware), high, low.

    Returns
    -------
    DataFrame con columnas: date (datetime.date), asia_high, asia_low, asia_mid.
    Una fila por dia de trading. Solo incluye dias con datos suficientes (>= 60 velas).
    """
    df = df.copy()
    hour = df["datetime"].dt.hour
    mask = (hour >= _ASIA_UTC_START) & (hour < _ASIA_UTC_END)
    asia_bars = df[mask].copy()

    asia_bars["_date"] = asia_bars["datetime"].dt.date

    grouped = (
        asia_bars.groupby("_date")
        .agg(
            asia_high   = ("high",  "max"),
            asia_low    = ("low",   "min"),
            _bar_count  = ("high",  "count"),
        )
        .reset_index()
        .rename(columns={"_date": "date"})
    )

    # Descartar dias con < 60 velas M1 (sesion Asia incompleta)
    grouped = grouped[grouped["_bar_count"] >= 60].drop(columns="_bar_count")
    grouped["asia_mid"] = (grouped["asia_high"] + grouped["asia_low"]) / 2.0
    grouped = grouped.reset_index(drop=True)
    return grouped


def get_for_date(asia_df: pd.DataFrame, trade_date: date) -> dict | None:
    """
    Devuelve el rango Asia para un dia especifico o None si no existe.
    """
    row = asia_df[asia_df["date"] == trade_date]
    if row.empty:
        return None
    r = row.iloc[0]
    return {
        "date":      r["date"],
        "asia_high": r["asia_high"],
        "asia_low":  r["asia_low"],
        "asia_mid":  r["asia_mid"],
    }


def asia_height_pips(asia_dict: dict, pip_size: float = 0.0001) -> float:
    """Altura del rango Asia en pips."""
    return (asia_dict["asia_high"] - asia_dict["asia_low"]) / pip_size


def price_position(price: float, asia_dict: dict) -> str:
    """
    Retorna 'above', 'below' o 'inside' respecto al rango Asia.
    """
    if price > asia_dict["asia_high"]:
        return "above"
    if price < asia_dict["asia_low"]:
        return "below"
    return "inside"
