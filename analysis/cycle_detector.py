"""
Clasifica el ciclo diario del mercado en relacion al rango Asia.

Ciclos definidos por la estrategia:
    Normal       - Precio saca liquidez por AMBOS lados del rango Asia
    Knockout     - Precio saca UN solo lado y sigue en esa direccion (no regresa)
    RetailHeaven - Tendencia clara sin barrer ninguno de los dos lados del rango Asia
    Sierra       - Movimiento erratico en ambas direcciones sin estructura clara

Ventana de deteccion: 07:00-15:00 UTC = 02:00-10:00 Colombia
(incluye sesion Londres y ventana operativa NY)

Uso:
    from analysis.cycle_detector import classify_day, compute

    cycle = classify_day(session_bars, asia_dict)
    cycles_df = compute(m5_df, asia_df)
"""

from typing import Literal

import pandas as pd

from config import SYMBOL_MAIN, TZ_COLOMBIA

CycleType = Literal["Normal", "Knockout", "RetailHeaven", "Sierra", "Unknown"]

# 07:00 UTC = 02:00 Colombia (apertura Londres aprox.)
# 15:00 UTC = 10:00 Colombia (fin ventana operativa)
_DETECT_UTC_START = 7
_DETECT_UTC_END   = 15

_PIP = 0.0001  # para EURUSD / GBPUSD (5 decimales, 1 pip = 0.0001)

# Minimo de velas M5 requeridas para clasificar (30 min de datos = 6 velas M5)
_MIN_BARS = 6

# Umbral de choppiness: si mas del 62% de velas consecutivas invierten direccion
# se considera movimiento erratico (Sierra)
_CHOPPINESS_THRESHOLD = 0.62


def classify_day(session_bars: pd.DataFrame, asia: dict | None) -> CycleType:
    """
    Clasifica el ciclo de un dia dado.

    Parameters
    ----------
    session_bars : DataFrame M5 con columnas [datetime, open, high, low, close]
                   filtrado a la ventana de deteccion (07:00-15:00 UTC) del dia.
    asia         : dict con keys asia_high, asia_low, asia_mid del mismo dia.
                   None si no hay datos del rango Asia.

    Returns
    -------
    CycleType string literal.
    """
    if session_bars is None or len(session_bars) < _MIN_BARS or asia is None:
        return "Unknown"

    asia_high = asia["asia_high"]
    asia_low  = asia["asia_low"]
    asia_mid  = asia["asia_mid"]

    h_max = session_bars["high"].max()
    l_min = session_bars["low"].min()

    swept_high = h_max > asia_high + _PIP
    swept_low  = l_min < asia_low  - _PIP

    if swept_high and swept_low:
        return "Normal"

    close_last = session_bars["close"].iloc[-1]

    if swept_high and not swept_low:
        # Precio barrio arriba: Knockout (sigue alcista) vs Sierra (regreso erratico)
        return "Knockout" if close_last > asia_mid else "Sierra"

    if swept_low and not swept_high:
        # Precio barrio abajo: Knockout (sigue bajista) vs Sierra (regreso erratico)
        return "Knockout" if close_last < asia_mid else "Sierra"

    # Ninguno de los dos lados fue barrido
    # Retail Heaven = tendencia clara sin tocar extremos del Asia
    # Sierra = movimiento erratico sin romper el rango
    choppiness = _compute_choppiness(session_bars["close"])
    return "RetailHeaven" if choppiness <= _CHOPPINESS_THRESHOLD else "Sierra"


def _compute_choppiness(close_series: pd.Series) -> float:
    """
    Fraccion de velas consecutivas que invierten la direccion del precio.
    Valor 0 = tendencia perfecta, valor 1 = maxima oscilacion.
    """
    diff = close_series.diff().dropna()
    if len(diff) < 2:
        return 0.0
    reversals = (diff * diff.shift(1) < 0).sum()
    return float(reversals) / (len(diff) - 1)


def compute(
    m5_df: pd.DataFrame,
    asia_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Clasifica el ciclo para cada dia presente en m5_df.

    Parameters
    ----------
    m5_df   : DataFrame M5 completo (todo el ano) con datetime UTC tz-aware.
    asia_df : DataFrame devuelto por analysis.asia_range.compute().

    Returns
    -------
    DataFrame con columnas: date, cycle, swept_high, swept_low, session_range_pips
    """
    from analysis.asia_range import get_for_date

    trade_dates = sorted(m5_df["datetime"].dt.date.unique())
    rows = []

    for d in trade_dates:
        day_mask = (
            (m5_df["datetime"].dt.date == d) &
            (m5_df["datetime"].dt.hour >= _DETECT_UTC_START) &
            (m5_df["datetime"].dt.hour <  _DETECT_UTC_END)
        )
        session_bars = m5_df[day_mask].copy()
        asia = get_for_date(asia_df, d)

        cycle = classify_day(session_bars, asia)

        swept_high = False
        swept_low  = False
        session_range_pips = 0.0

        if asia and len(session_bars) >= _MIN_BARS:
            swept_high = session_bars["high"].max() > asia["asia_high"] + _PIP
            swept_low  = session_bars["low"].min()  < asia["asia_low"]  - _PIP
            session_range_pips = (
                session_bars["high"].max() - session_bars["low"].min()
            ) / _PIP

        rows.append({
            "date":               d,
            "cycle":              cycle,
            "swept_high":         swept_high,
            "swept_low":          swept_low,
            "session_range_pips": round(session_range_pips, 1),
        })

    return pd.DataFrame(rows)


def cycle_summary(cycles_df: pd.DataFrame) -> None:
    """Imprime distribucion de ciclos en el DataFrame dado."""
    counts = cycles_df["cycle"].value_counts()
    total  = len(cycles_df)
    print("\n-- Distribucion de ciclos -----------------------------------------")
    for cycle, count in counts.items():
        pct = 100 * count / total
        print(f"  {cycle:<14} {count:>4} dias  ({pct:5.1f}%)")
    print(f"  {'TOTAL':<14} {total:>4} dias")
    print("-------------------------------------------------------------------\n")
