"""
Calcula los niveles de apertura magneto para cada dia operativo.

Dos aperturas clave (hora New York):
    - Magnet 1: 00:00 NY  (medianoche NY = apertura del dia NY)
    - Magnet 2: 07:30 NY  (pre-mercado NY)

Logica de sesgo:
    precio actual < nivel  →  sesgo alcista  (compra)
    precio actual > nivel  →  sesgo bajista  (venta)

NYC cambia de horario en marzo/noviembre; usar ZoneInfo para manejar DST.
Colombia siempre UTC-5; por eso usamos NY explicitamente para los magnetos.

Uso:
    from analysis.opening_magnets import compute, get_bias

    magnets = compute(m1_df)            # DataFrame con todos los dias
    bias = get_bias(magnets, date, close_price)
"""

from datetime import date, datetime, timezone

import pandas as pd

from config import MAGNET_1_NY, MAGNET_2_NY, TZ_NEW_YORK

# Convertir "HH:MM" a (hour, minute)
def _hm(s: str) -> tuple[int, int]:
    h, m = s.split(":")
    return int(h), int(m)


_M1_HOUR, _M1_MIN = _hm(MAGNET_1_NY)  # 00:00 NY
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
    # Construir el timestamp NY exacto y convertir a UTC para buscar en df
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
    Calcula los niveles de apertura magneto para cada dia en df.

    Parameters
    ----------
    df : DataFrame M1 con columnas datetime (UTC tz-aware), close.
         Debe cubrir al menos todos los dias de trading de interes.

    Returns
    -------
    DataFrame con columnas:
        date        - fecha Colombia (= fecha UTC en horario operativo)
        magnet_1    - precio de cierre vela en 00:00 NY  (None si no hay datos)
        magnet_2    - precio de cierre vela en 07:30 NY  (None si no hay datos)
    """
    trade_dates = sorted(df["datetime"].dt.date.unique())
    rows = []
    for d in trade_dates:
        m1 = _get_close_at_ny_time(df, d, _M1_HOUR, _M1_MIN)
        m2 = _get_close_at_ny_time(df, d, _M2_HOUR, _M2_MIN)
        rows.append({"date": d, "magnet_1": m1, "magnet_2": m2})

    return pd.DataFrame(rows)


def get_bias(magnets_df: pd.DataFrame, trade_date: date, current_price: float) -> dict:
    """
    Calcula el sesgo de cada magneto para un precio dado.

    Returns
    -------
    {
        "magnet_1": "bullish" | "bearish" | None,
        "magnet_2": "bullish" | "bearish" | None,
        "agreement": True si ambos magnetos disponibles coinciden en sesgo,
        "bias": "bullish" | "bearish" | "neutral" | "conflict"
    }
    """
    row = magnets_df[magnets_df["date"] == trade_date]
    if row.empty:
        return {"magnet_1": None, "magnet_2": None, "agreement": False, "bias": "neutral"}

    r = row.iloc[0]

    def _side(level) -> str | None:
        if level is None or pd.isna(level):
            return None
        return "bullish" if current_price < level else "bearish"

    b1 = _side(r["magnet_1"])
    b2 = _side(r["magnet_2"])

    available = [b for b in (b1, b2) if b is not None]
    if not available:
        bias = "neutral"
        agreement = False
    elif len(available) == 1:
        bias = available[0]
        agreement = True
    else:
        agreement = b1 == b2
        bias = b1 if agreement else "conflict"

    return {"magnet_1": b1, "magnet_2": b2, "agreement": agreement, "bias": bias}
