"""
Catalogo de niveles clave por dia, con pesos segun antiguedad.

Pesos:
    1 — Magnetos de apertura (00:00 NY y 07:30 NY)
    2 — Asia High/Low (00:00-05:00 UTC del dia)
    3 — High/Low del dia anterior
    4 — High/Low de la semana anterior (ISO)

Un barrido de un nivel de mayor peso tiene mayor potencial de reversion.
"""

from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd


@dataclass(frozen=True)
class Level:
    price:  float
    weight: int
    name:   str
    side:   str = "both"  # "high" -> solo sweep SHORT | "low" -> solo sweep LONG | "both"


def precompute_daily_hl(m1_df: pd.DataFrame) -> pd.DataFrame:
    """Calcula High/Low de cada dia calendario de la serie M1."""
    df = m1_df.copy()
    df["_date"] = df["datetime"].dt.date
    result = (
        df.groupby("_date")
        .agg(daily_high=("high", "max"), daily_low=("low", "min"))
        .reset_index()
        .rename(columns={"_date": "date"})
    )
    return result


def precompute_weekly_hl(m1_df: pd.DataFrame) -> pd.DataFrame:
    """Calcula High/Low de cada semana ISO de la serie M1."""
    df = m1_df.copy()
    iso = df["datetime"].dt.isocalendar()
    df["_yr"] = iso["year"].values.astype(int)
    df["_wk"] = iso["week"].values.astype(int)
    result = (
        df.groupby(["_yr", "_wk"])
        .agg(weekly_high=("high", "max"), weekly_low=("low", "min"))
        .reset_index()
        .rename(columns={"_yr": "iso_year", "_wk": "iso_week"})
    )
    return result


def _prev_day_row(daily_hl: pd.DataFrame, trade_date: date):
    """Fila OHLC del dia de trading anterior (retrocede hasta 7 dias si hay festivos)."""
    prev = trade_date - timedelta(days=1)
    for _ in range(7):
        rows = daily_hl[daily_hl["date"] == prev]
        if not rows.empty:
            return rows.iloc[0]
        prev -= timedelta(days=1)
    return None


def _prev_week_row(weekly_hl: pd.DataFrame, trade_date: date):
    """Fila OHLC de la semana ISO anterior a trade_date."""
    iso = trade_date.isocalendar()
    yr, wk = int(iso.year), int(iso.week) - 1
    if wk == 0:
        yr -= 1
        wk = int(date(yr, 12, 28).isocalendar().week)
    rows = weekly_hl[(weekly_hl["iso_year"] == yr) & (weekly_hl["iso_week"] == wk)]
    return rows.iloc[0] if not rows.empty else None


def build_day_levels(
    trade_date: date,
    asia: dict | None,
    magnet_1: float | None,
    magnet_2: float | None,
    daily_hl: pd.DataFrame,
    weekly_hl: pd.DataFrame,
    extra_levels: list[Level] | None = None,
    min_weight: int = 1,
    max_weight: int = 99,
) -> list[Level]:
    """
    Construye el catalogo de niveles clave para un dia de trading.

    Retorna lista ordenada: mayor peso primero, luego precio ascendente.
    """
    levels: list[Level] = []

    def _valid(v):
        return v is not None and not (isinstance(v, float) and pd.isna(v))

    # Peso 1: magnetos (ambas direcciones — no son niveles H/L sino precios de referencia temporal)
    if _valid(magnet_1):
        levels.append(Level(price=float(magnet_1), weight=1, name="magnet_1", side="both"))
    if _valid(magnet_2):
        levels.append(Level(price=float(magnet_2), weight=1, name="magnet_2", side="both"))

    # Peso 2: Asia — HIGH solo genera SHORT (fake breakout), LOW solo genera LONG (fake breakdown)
    if asia:
        levels.append(Level(price=float(asia["asia_high"]), weight=2, name="asia_high", side="high"))
        levels.append(Level(price=float(asia["asia_low"]),  weight=2, name="asia_low",  side="low"))

    # Peso 3: dia anterior
    pd_row = _prev_day_row(daily_hl, trade_date)
    if pd_row is not None:
        levels.append(Level(price=float(pd_row["daily_high"]), weight=3, name="prev_day_high", side="high"))
        levels.append(Level(price=float(pd_row["daily_low"]),  weight=3, name="prev_day_low",  side="low"))

    # Peso 4: semana anterior
    pw_row = _prev_week_row(weekly_hl, trade_date)
    if pw_row is not None:
        levels.append(Level(price=float(pw_row["weekly_high"]), weight=4, name="prev_week_high", side="high"))
        levels.append(Level(price=float(pw_row["weekly_low"]),  weight=4, name="prev_week_low",  side="low"))

    if extra_levels:
        levels.extend(extra_levels)

    levels = [lv for lv in levels if min_weight <= lv.weight <= max_weight]
    return sorted(levels, key=lambda x: (-x.weight, x.price))
