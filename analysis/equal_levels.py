"""
Detección de Equal Highs (EQH) y Equal Lows (EQL) en datos M5.

Concepto:
    Cuando el precio toca un mismo nivel de high (o low) dos o más veces
    sin cruzarlo (el cierre nunca lo superó), esa zona acumula liquidez
    pendiente (stops de retail). Es un candidato fuerte para el próximo barrido.

Reglas de detección:
    1. Encontrar swing highs/lows en M5 de los últimos N días.
    2. Agrupar los que estén dentro de pip_tolerance entre sí.
    3. Mantener solo los grupos con >= min_touches toques.
    4. Descartar niveles donde alguna vela ya CERRÓ más allá del nivel
       (si el cierre no cruzó pero el wick sí → sigue intacto, es un toque más).
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from analysis.levels import Level

_PIP       = 0.0001
_SWING_W   = 3   # velas a cada lado para confirmar un swing


def _swing_highs(df: pd.DataFrame) -> list[tuple]:
    """Lista de (datetime, price) para cada swing high en df."""
    result = []
    w = _SWING_W
    highs = df["high"].values
    for i in range(w, len(df) - w):
        if all(highs[i] >= highs[i + k] for k in range(-w, w + 1) if k != 0):
            result.append((df["datetime"].iloc[i], float(highs[i])))
    return result


def _swing_lows(df: pd.DataFrame) -> list[tuple]:
    """Lista de (datetime, price) para cada swing low en df."""
    result = []
    w = _SWING_W
    lows = df["low"].values
    for i in range(w, len(df) - w):
        if all(lows[i] <= lows[i + k] for k in range(-w, w + 1) if k != 0):
            result.append((df["datetime"].iloc[i], float(lows[i])))
    return result


def _group_intact(swings: list[tuple], df_check: pd.DataFrame,
                  side: str, tolerance: float, min_touches: int) -> list[Level]:
    """
    Agrupa swings dentro de tolerance; descarta los que alguna vela cerró más allá.
    side='high' → EQH → descarta si close > nivel + tolerance
    side='low'  → EQL → descarta si close < nivel - tolerance
    """
    levels = []
    used   = set()

    for i, (t1, p1) in enumerate(swings):
        if i in used:
            continue
        group = [(t1, p1)]
        for j, (t2, p2) in enumerate(swings[i + 1:], i + 1):
            if j not in used and abs(p1 - p2) <= tolerance:
                group.append((t2, p2))
                used.add(j)
        used.add(i)

        if len(group) < min_touches:
            continue

        avg_price = sum(p for _, p in group) / len(group)
        last_time = max(t for t, _ in group)

        # Verificar que el nivel sigue intacto en los datos posteriores
        future = df_check[df_check["datetime"] > last_time]
        if side == "high":
            broken = not future.empty and (future["close"] > avg_price + tolerance).any()
        else:
            broken = not future.empty and (future["close"] < avg_price - tolerance).any()

        if not broken:
            levels.append(Level(
                price  = round(avg_price, 5),
                weight = 2,
                name   = f"eq_{side}",
                side   = side,
            ))

    return levels


def find_equal_levels(
    m5_df:        pd.DataFrame,
    trade_date:   date,
    lookback_days: int   = 7,
    pip_tolerance: float = 2.0,
    min_touches:   int   = 2,
) -> list[Level]:
    """
    Detecta EQH y EQL en M5 de los últimos lookback_days días previos a trade_date.

    Parameters
    ----------
    m5_df        : DataFrame M5 con columnas datetime (UTC tz-aware), high, low, close.
    trade_date   : Fecha del día de trading.
    lookback_days: Días de historia a escanear.
    pip_tolerance: Pips de tolerancia para agrupar swings como "iguales".
    min_touches  : Toques mínimos para considerar el nivel relevante.

    Returns
    -------
    Lista de Level con name='eq_high' (EQH) o 'eq_low' (EQL), side='high'/'low', weight=2.
    """
    tol = pip_tolerance * _PIP

    cutoff     = pd.Timestamp(trade_date - timedelta(days=lookback_days), tz="UTC")
    today_utc  = pd.Timestamp(trade_date, tz="UTC")
    window_utc = today_utc + pd.Timedelta(hours=12)  # antes de nuestra ventana operativa

    hist  = m5_df[(m5_df["datetime"] >= cutoff) & (m5_df["datetime"] < today_utc)].reset_index(drop=True)
    check = m5_df[(m5_df["datetime"] >= today_utc) & (m5_df["datetime"] < window_utc)].reset_index(drop=True)

    if len(hist) < _SWING_W * 2 + 1:
        return []

    highs = _swing_highs(hist)
    lows  = _swing_lows(hist)

    eqh = _group_intact(highs, check, "high", tol, min_touches)
    eql = _group_intact(lows,  check, "low",  tol, min_touches)

    return eqh + eql
