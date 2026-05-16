"""
Implementa la Teoria de Cuartos para detectar inducciones.

Definicion (segun la estrategia):
    El dia se divide en 4 bloques de 6 horas (hora New York):
        Q1: 00:00 - 05:59 NY
        Q2: 06:00 - 11:59 NY
        Q3: 12:00 - 17:59 NY
        Q4: 18:00 - 23:59 NY

    Confirmacion de induccion:
        Si el cuarto ACTUAL supera el MAXIMO del cuarto ANTERIOR
            → induccion confirmada hacia ABAJO (el precio sube para atrapar compradores)
        Si el cuarto ACTUAL supera el MINIMO del cuarto ANTERIOR
            → induccion confirmada hacia ARRIBA (el precio baja para atrapar vendedores)

    El cuarto actual es el que contiene la vela de analisis.
    El cuarto anterior es el bloque de 6h inmediatamente precedente.

Nota DST:
    Q1 empieza a las 00:00 NY. Durante EDT (verano) 00:00 NY = 04:00 UTC.
    Durante EST (invierno) 00:00 NY = 05:00 UTC.
    Se usa ZoneInfo("America/New_York") para el calculo correcto.

Uso:
    from analysis.quarters_theory import get_quarter_info, check_signal

    qi = get_quarter_info(current_bar_datetime, m5_df)
    signal = check_signal(qi)
    if signal["signal"]:
        print(signal["direction"])
"""

from datetime import datetime, timezone

import pandas as pd

from config import TZ_NEW_YORK

# Limites de los cuartos en horas NY
_QUARTER_STARTS = [0, 6, 12, 18]  # hora de inicio de cada cuarto (hora NY)


def _quarter_index(ny_hour: int) -> int:
    """Devuelve el indice del cuarto (0-3) dado la hora NY."""
    for i in range(len(_QUARTER_STARTS) - 1, -1, -1):
        if ny_hour >= _QUARTER_STARTS[i]:
            return i
    return 0


def get_quarter_bounds(dt_utc: pd.Timestamp) -> tuple[pd.Timestamp, pd.Timestamp]:
    """
    Devuelve (inicio, fin) del cuarto al que pertenece dt_utc, en UTC.
    """
    dt_ny = dt_utc.astimezone(TZ_NEW_YORK)
    q_idx = _quarter_index(dt_ny.hour)
    q_start_hour = _QUARTER_STARTS[q_idx]

    q_start_ny = dt_ny.replace(hour=q_start_hour, minute=0, second=0, microsecond=0)
    q_end_ny   = q_start_ny.replace(hour=q_start_hour + 5, minute=59, second=59)

    q_start_utc = pd.Timestamp(q_start_ny).tz_convert("UTC")
    q_end_utc   = pd.Timestamp(q_end_ny).tz_convert("UTC")
    return q_start_utc, q_end_utc


def get_prev_quarter_bounds(dt_utc: pd.Timestamp) -> tuple[pd.Timestamp, pd.Timestamp]:
    """
    Devuelve (inicio, fin) del cuarto ANTERIOR al que contiene dt_utc, en UTC.
    """
    dt_ny = dt_utc.astimezone(TZ_NEW_YORK)
    q_idx = _quarter_index(dt_ny.hour)
    prev_q_idx = (q_idx - 1) % 4

    prev_start_hour = _QUARTER_STARTS[prev_q_idx]

    # Si el cuarto anterior es Q4 y el actual es Q1, retrocedemos un dia
    day_offset = -1 if prev_q_idx > q_idx else 0
    base_date  = dt_ny.date()
    if day_offset:
        from datetime import timedelta
        base_date = base_date + timedelta(days=day_offset)

    from datetime import date as dt_date
    prev_start_ny = datetime(
        base_date.year, base_date.month, base_date.day,
        prev_start_hour, 0, 0,
        tzinfo=TZ_NEW_YORK,
    )
    prev_end_ny = prev_start_ny.replace(hour=prev_start_hour + 5, minute=59, second=59)

    prev_start_utc = pd.Timestamp(prev_start_ny).tz_convert("UTC")
    prev_end_utc   = pd.Timestamp(prev_end_ny).tz_convert("UTC")
    return prev_start_utc, prev_end_utc


def get_quarter_info(
    current_dt_utc: pd.Timestamp,
    bars_df: pd.DataFrame,
) -> dict:
    """
    Calcula el High/Low del cuarto actual y del cuarto anterior.

    Parameters
    ----------
    current_dt_utc : Timestamp UTC del momento de analisis (tz-aware).
    bars_df        : DataFrame M5 con datetime (UTC tz-aware), high, low.

    Returns
    -------
    {
        "current_q":    indice del cuarto actual (0-3)
        "current_high": maximo del cuarto actual hasta current_dt_utc
        "current_low":  minimo del cuarto actual hasta current_dt_utc
        "prev_high":    maximo del cuarto anterior (completo)
        "prev_low":     minimo del cuarto anterior (completo)
        "prev_q":       indice del cuarto anterior
        "enough_data":  bool - True si hay suficientes velas en ambos cuartos
    }
    """
    curr_start, curr_end = get_quarter_bounds(current_dt_utc)
    prev_start, prev_end = get_prev_quarter_bounds(current_dt_utc)

    curr_bars = bars_df[
        (bars_df["datetime"] >= curr_start) &
        (bars_df["datetime"] <= current_dt_utc)
    ]
    prev_bars = bars_df[
        (bars_df["datetime"] >= prev_start) &
        (bars_df["datetime"] <= prev_end)
    ]

    dt_ny = current_dt_utc.astimezone(TZ_NEW_YORK)
    q_idx = _quarter_index(dt_ny.hour)

    enough = len(curr_bars) >= 3 and len(prev_bars) >= 12

    return {
        "current_q":    q_idx,
        "current_high": float(curr_bars["high"].max()) if not curr_bars.empty else None,
        "current_low":  float(curr_bars["low"].min())  if not curr_bars.empty else None,
        "prev_high":    float(prev_bars["high"].max()) if not prev_bars.empty else None,
        "prev_low":     float(prev_bars["low"].min())  if not prev_bars.empty else None,
        "prev_q":       (q_idx - 1) % 4,
        "enough_data":  enough,
    }


def precompute(m5_df: pd.DataFrame) -> pd.DataFrame:
    """
    Calcula senales de teoria de cuartos para TODAS las velas M5 (vectorizado).

    Mucho mas rapido que llamar get_quarter_info() barra a barra.
    Ordenar m5_df por datetime antes de llamar esta funcion.

    Returns
    -------
    DataFrame con columnas: datetime, q_signal (bool), q_direction ('long'|'short'|None)
    """
    df = m5_df[["datetime", "high", "low"]].copy().sort_values("datetime").reset_index(drop=True)

    ny_dt = df["datetime"].dt.tz_convert(TZ_NEW_YORK)
    df["_ny_date"] = ny_dt.dt.date
    df["_q"]       = ny_dt.dt.hour.map(_quarter_index)

    # Tabla de high/low completos por cuarto (ny_date, q)
    qstats = (
        df.groupby(["_ny_date", "_q"], sort=True)
        .agg(q_hi=("high", "max"), q_lo=("low", "min"))
        .reset_index()
        .sort_values(["_ny_date", "_q"])
        .reset_index(drop=True)
    )
    # shift(1) en la secuencia cronologica → cuarto anterior
    # Funciona correctamente para Q4→Q1 porque el orden es dia1-Q0, Q1, Q2, Q3, dia2-Q0...
    qstats["prev_q_hi"] = qstats["q_hi"].shift(1)
    qstats["prev_q_lo"] = qstats["q_lo"].shift(1)

    # Unir de vuelta al nivel de barra
    df = df.merge(qstats[["_ny_date", "_q", "prev_q_hi", "prev_q_lo"]], on=["_ny_date", "_q"], how="left")

    # Acumulado del high/low DENTRO del cuarto hasta cada barra
    df["_cum_hi"] = df.groupby(["_ny_date", "_q"])["high"].cummax()
    df["_cum_lo"] = df.groupby(["_ny_date", "_q"])["low"].cummin()

    has_prev    = df["prev_q_hi"].notna()
    swept_high  = df["_cum_hi"] > df["prev_q_hi"]
    swept_low   = df["_cum_lo"] < df["prev_q_lo"]

    df["q_signal"]    = False
    df["q_direction"] = None

    short_mask = has_prev & swept_high & ~swept_low
    long_mask  = has_prev & swept_low  & ~swept_high

    df.loc[short_mask, "q_signal"]    = True
    df.loc[short_mask, "q_direction"] = "short"
    df.loc[long_mask,  "q_signal"]    = True
    df.loc[long_mask,  "q_direction"] = "long"

    return df[["datetime", "q_signal", "q_direction"]].copy()


def check_signal(qi: dict) -> dict:
    """
    Evalua si el cuarto actual ya saco el maximo o minimo del cuarto anterior.

    Returns
    -------
    {
        "signal":    bool
        "direction": "long" | "short" | None
        "note":      str
    }
    """
    result = {"signal": False, "direction": None, "note": "sin datos suficientes"}

    if not qi.get("enough_data"):
        return result
    if qi["current_high"] is None or qi["prev_high"] is None:
        return result

    swept_high = qi["current_high"] > qi["prev_high"]
    swept_low  = qi["current_low"]  < qi["prev_low"]

    if swept_high and not swept_low:
        result["signal"]    = True
        result["direction"] = "short"
        result["note"]      = f"Cuarto actual supero maximo del cuarto anterior ({qi['prev_high']:.5f}) -> induccion SHORT"
    elif swept_low and not swept_high:
        result["signal"]    = True
        result["direction"] = "long"
        result["note"]      = f"Cuarto actual supero minimo del cuarto anterior ({qi['prev_low']:.5f}) -> induccion LONG"
    elif swept_high and swept_low:
        result["note"] = "cuarto actual saco ambos lados del anterior (Sierra o Normal)"
    else:
        result["note"] = "cuarto actual aun no ha sacado ninguno de los extremos del anterior"

    return result
