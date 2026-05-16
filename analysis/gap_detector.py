"""
Detecta gaps semanales (viernes cierre vs lunes apertura) en datos M1.

Un gap semanal ocurre cuando el lunes abre en un precio diferente al cierre del viernes.
El gap tiende a llenarse: el precio vuelve al nivel del cierre del viernes.

Sesgo direccional del gap:
    Gap alcista (Monday open > Friday close) -> el precio debe bajar a llenar -> sesgo SHORT
    Gap bajista (Monday open < Friday close) -> el precio debe subir a llenar -> sesgo LONG

El gap actua como 4a confirmacion: si el sesgo coincide con la direccion del trade,
suma una confirmacion adicional.
"""

from datetime import date

import pandas as pd

_PIP = 0.0001


def detect_weekly_gaps(m1_df: pd.DataFrame, min_pips: float = 5.0) -> pd.DataFrame:
    """
    Detecta todos los gaps semanales en la serie M1.

    Returns DataFrame con columnas:
        gap_date      — lunes en que aparece el gap
        gap_price     — precio de cierre del viernes (nivel a "llenar")
        gap_direction — "up" (Monday > Friday) o "down"
        gap_size_pips — tamano del gap en pips
    """
    df = m1_df.copy()
    df["_date"] = df["datetime"].dt.date

    daily_close = df.groupby("_date")["close"].last().reset_index()
    daily_close.columns = ["date", "close"]
    daily_close["date"] = pd.to_datetime(daily_close["date"]).dt.date

    daily_open = df.groupby("_date")["open"].first().reset_index()
    daily_open.columns = ["date", "open"]
    daily_open["date"] = pd.to_datetime(daily_open["date"]).dt.date

    daily = daily_close.merge(daily_open, on="date")
    daily["weekday"] = [d.weekday() for d in daily["date"]]
    daily_list = daily.to_dict("records")

    gaps = []
    for i in range(1, len(daily_list)):
        prev = daily_list[i - 1]
        curr = daily_list[i]

        if curr["weekday"] != 0:
            continue

        gap_size = abs(curr["open"] - prev["close"]) / _PIP
        if gap_size < min_pips:
            continue

        gaps.append({
            "gap_date":      curr["date"],
            "gap_price":     float(prev["close"]),
            "gap_direction": "up" if curr["open"] > prev["close"] else "down",
            "gap_size_pips": round(gap_size, 1),
        })

    if not gaps:
        return pd.DataFrame(
            columns=["gap_date", "gap_price", "gap_direction", "gap_size_pips"]
        )
    return pd.DataFrame(gaps)


def get_gap_bias(gaps_df: pd.DataFrame, trade_date: date) -> str | None:
    """
    Retorna el sesgo del gap semanal mas reciente vigente en trade_date.

    Returns "long", "short", o None si no hay gaps activos.
    """
    if gaps_df.empty:
        return None
    active = gaps_df[gaps_df["gap_date"] <= trade_date]
    if active.empty:
        return None
    latest = active.iloc[-1]
    # gap "up" -> precio tiene que bajar a llenarlo -> SHORT
    # gap "down" -> precio tiene que subir a llenarlo -> LONG
    return "short" if latest["gap_direction"] == "up" else "long"
