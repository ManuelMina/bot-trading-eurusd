"""
Calcula el nivel de apertura magneto 07:30 NY para cada dia operativo.

El magneto de 00:00 NY fue descartado — solo el de 07:30 NY es operativamente
relevante. La apertura de las 07:30 NY coincide con el pre-mercado de NY y
concentra liquidez institucional antes de la apertura oficial a las 09:30 NY.

Logica de sesgo:
    precio actual < nivel  ->  sesgo alcista  (compra)
    precio actual > nivel  ->  sesgo bajista  (venta)

NYC cambia de horario en marzo/noviembre; usar ZoneInfo para manejar DST.

Uso:
    from analysis.opening_magnets import compute, get_bias

    magnets = compute(m1_df)            # DataFrame con todos los dias
    bias = get_bias(magnets, date, close_price)
"""

from datetime import date, datetime, timezone

import pandas as pd

from config import MAGNET_2_NY, TZ_NEW_YORK

def _hm(s: str) -> tuple[int, int]:
    h, m = s.split(":")
    return int(h), int(m)


_M2_HOUR, _M2_MIN = _hm(MAGNET_2_NY)  # 07:30 NY


def _get_close_at_ny_time(
    df: pd.DataFrame,
    trade_date: date,
    ny_hour: int,
    ny_min: int,
) -> float | None:
    """
    Devuelve el precio de cierre (close) de la vela M1 que abre exactamente
    en ny_hour:ny_min hora New York del dia trade_date (en NY).
    """
    dt_ny = datetime(
        trade_date.year, trade_date.month, trade_date.day,
        ny_hour, ny_min, 0,
        tzinfo=TZ_NEW_YORK,
    )
    dt_utc = dt_ny.astimezone(timezone.utc)
    dt_utc = pd.Timestamp(dt_utc).tz_convert("UTC")

    row = df[df["datetime"] == dt_utc]
    if row.empty:
        return None
    return float(row.iloc[0]["close"])


def compute(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calcula el nivel de apertura magneto 07:30 NY para cada dia en df.

    Parameters
    ----------
    df : DataFrame M1 con columnas datetime (UTC tz-aware), close.

    Returns
    -------
    DataFrame con columnas:
        date        - fecha del dia operativo
        magnet_2    - precio de cierre vela en 07:30 NY  (None si no hay datos)
    """
    trade_dates = sorted(df["datetime"].dt.date.unique())
    rows = []
    for d in trade_dates:
        m2 = _get_close_at_ny_time(df, d, _M2_HOUR, _M2_MIN)
        rows.append({"date": d, "magnet_2": m2})

    return pd.DataFrame(rows)


def get_bias(magnets_df: pd.DataFrame, trade_date: date, current_price: float) -> dict:
    """
    Calcula el sesgo del magneto 07:30 NY para un precio dado.

    Returns
    -------
    {
        "magnet_2": "bullish" | "bearish" | None,
        "agreement": True si el magneto esta disponible,
        "bias": "bullish" | "bearish" | "neutral"
    }
    """
    row = magnets_df[magnets_df["date"] == trade_date]
    if row.empty:
        return {"magnet_2": None, "agreement": False, "bias": "neutral"}

    r = row.iloc[0]
    level = r.get("magnet_2")

    if level is None or pd.isna(level):
        return {"magnet_2": None, "agreement": False, "bias": "neutral"}

    bias = "bullish" if current_price < float(level) else "bearish"
    return {"magnet_2": bias, "agreement": True, "bias": bias}
