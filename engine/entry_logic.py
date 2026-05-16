"""
Logica de entrada: combina todas las confirmaciones y genera senales de trade.

Flujo para cada vela M1 dentro de la ventana operativa (07:00-10:00 Colombia):
    1. Verificar que el ciclo del dia esta identificado (no Unknown)
    2. Contar confirmaciones activas (divergencia, cuartos, magnetos)
    3. Si hay >= MIN_CONFIRMATIONS: buscar induccion en M1
    4. Si hay induccion valida: buscar vela de fuerza (trigger)
    5. Si hay vela de fuerza: generar senal con SL/TP calculados

Caso especial Sierra:
    Solo se generan senales en sweeps de los extremos del rango errático (>= SIERRA_SWEEP_PIPS)
    seguidos de vela de fuerza en direccion contraria.

Resultado: TradeSignal o None
"""

from dataclasses import dataclass, field
from datetime import date, time, datetime
from typing import Literal

import pandas as pd

from config import (
    EXCELLENCE_BODY_LOOKBACK,
    EXCELLENCE_BODY_MULT,
    MIN_CONFIRMATIONS,
    RISK_REWARD,
    SIERRA_SWEEP_PIPS,
    TRADING_END_COL,
    TRADING_START_COL,
    TRADING_T3_CUTOFF,
    TZ_COLOMBIA,
    TZ_NEW_YORK,
)

_PIP          = 0.0001
_COLOMBIA_UTC = -5   # offset fijo Colombia → UTC


@dataclass
class TradeSignal:
    """Senal de trade generada por el motor de entrada."""
    direction:     str          # "long" o "short"
    entry_price:   float
    sl_price:      float
    tp_price:      float
    sl_pips:       float
    signal_time:   pd.Timestamp  # UTC timestamp de la vela de trigger
    cycle:         str
    confirmations: list[str]     # nombres de confirmaciones activas
    induction_price: float
    force_body:    float         # tamano del cuerpo de la vela de fuerza
    avg_body:      float         # promedio de cuerpos para referencia
    excellence:    bool = False  # True si cumple condiciones de excelencia (T3)


def _colombia_to_utc_hour(col_hour: int) -> int:
    return col_hour + abs(_COLOMBIA_UTC)   # Colombia es UTC-5 → + 5


def _parse_col_time(hhmm: str) -> tuple[int, int]:
    h, m = hhmm.split(":")
    return int(h), int(m)


def _bar_in_trading_window(dt_utc: pd.Timestamp) -> bool:
    """True si la barra UTC esta dentro de 07:00-10:00 Colombia."""
    start_h, start_m = _parse_col_time(TRADING_START_COL)
    end_h,   end_m   = _parse_col_time(TRADING_END_COL)
    utc_start_h = start_h + abs(_COLOMBIA_UTC)
    utc_end_h   = end_h   + abs(_COLOMBIA_UTC)
    utc_start_m = start_m
    utc_end_m   = end_m

    bar_h = dt_utc.hour
    bar_m = dt_utc.minute

    after_start = (bar_h > utc_start_h) or (bar_h == utc_start_h and bar_m >= utc_start_m)
    before_end  = (bar_h < utc_end_h)   or (bar_h == utc_end_h   and bar_m <  utc_end_m)
    return after_start and before_end


def _bar_before_t3_cutoff(dt_utc: pd.Timestamp) -> bool:
    """True si la barra esta antes de la hora limite para T3 (09:30 Colombia)."""
    cut_h, cut_m = _parse_col_time(TRADING_T3_CUTOFF)
    utc_cut_h = cut_h + abs(_COLOMBIA_UTC)
    bar_h, bar_m = dt_utc.hour, dt_utc.minute
    return (bar_h < utc_cut_h) or (bar_h == utc_cut_h and bar_m < cut_m)


def _force_candle_direction(
    candle: pd.Series,
    prev_candle: pd.Series,
) -> str | None:
    """
    Devuelve "long" si la vela es alcista con cuerpo > cuerpo anterior,
    "short" si es bajista con cuerpo > cuerpo anterior, None si no cumple.
    """
    body      = abs(candle["close"] - candle["open"])
    prev_body = abs(prev_candle["close"] - prev_candle["open"])
    if body <= prev_body:
        return None
    if candle["close"] > candle["open"]:
        return "long"
    if candle["close"] < candle["open"]:
        return "short"
    return None


def _avg_body(bars: pd.DataFrame, lookback: int) -> float:
    """Promedio del tamano del cuerpo de las ultimas 'lookback' velas."""
    recent = bars.iloc[-lookback:]
    return float((recent["close"] - recent["open"]).abs().mean())


def _is_excellence(
    signal: "TradeSignal",
    cycle: str,
    confirmations: list[str],
    signal_time: pd.Timestamp,
) -> bool:
    """Verifica si el setup cumple todas las condiciones de excelencia para T3."""
    if cycle in ("Unknown", "Sierra"):
        return False
    if len(confirmations) < 3:
        return False
    if not _bar_before_t3_cutoff(signal_time):
        return False
    if signal.force_body < EXCELLENCE_BODY_MULT * signal.avg_body:
        return False
    return True


def _count_confirmations(
    divergence_result: dict | None,
    quarters_signal: dict | None,
    magnet_bias: dict | None,
    direction: str,
) -> list[str]:
    """
    Cuenta las confirmaciones que estan alineadas con la direccion dada.
    Retorna lista de nombres de confirmaciones activas.
    """
    active = []

    if divergence_result and divergence_result.get("divergence"):
        if divergence_result.get("direction") == direction:
            active.append("divergence")

    if quarters_signal and quarters_signal.get("signal"):
        if quarters_signal.get("direction") == direction:
            active.append("quarters")

    if magnet_bias:
        bias = magnet_bias.get("bias")
        if bias == direction or (
            direction == "long"  and bias == "bullish" or
            direction == "short" and bias == "bearish"
        ):
            active.append("magnets")

    return active


def evaluate_bar(
    bar_idx: int,
    m1_bars: pd.DataFrame,
    trade_date: date,
    cycle: str,
    asia: dict | None,
    divergence_result: dict | None,
    quarters_signal: dict | None,
    magnet_bias: dict | None,
    trades_today: int,
) -> TradeSignal | None:
    """
    Evalua si la barra en bar_idx genera una senal de trade.

    Parameters
    ----------
    bar_idx         : indice de la barra actual en m1_bars.
    m1_bars         : DataFrame M1 completo (o ventana del dia).
    trade_date      : fecha Colombia del dia de trading.
    cycle           : CycleType del dia.
    asia            : dict del rango Asia del dia.
    divergence_result: resultado de analysis.divergence.check().
    quarters_signal : resultado de analysis.quarters_theory.check_signal().
    magnet_bias     : resultado de analysis.opening_magnets.get_bias().
    trades_today    : cuantos trades ya se cerraron hoy (0, 1 o 2).

    Returns
    -------
    TradeSignal o None.
    """
    if cycle == "Unknown":
        return None
    if trades_today >= 3:
        return None
    if bar_idx < EXCELLENCE_BODY_LOOKBACK + 2:
        return None

    candle      = m1_bars.iloc[bar_idx]
    prev_candle = m1_bars.iloc[bar_idx - 1]
    dt_utc      = candle["datetime"]

    if not _bar_in_trading_window(dt_utc):
        return None

    # Detectar direccion de la vela de fuerza
    direction = _force_candle_direction(candle, prev_candle)
    if direction is None:
        return None

    # Caso Sierra: solo senales de sweep
    if cycle == "Sierra":
        signal = _evaluate_sierra_sweep(
            bar_idx, m1_bars, asia, direction, candle, prev_candle,
            divergence_result, quarters_signal, magnet_bias, trades_today,
        )
        return signal

    # Confirmaciones alineadas con la direccion de la vela de fuerza
    confirmations = _count_confirmations(
        divergence_result, quarters_signal, magnet_bias, direction
    )
    if len(confirmations) < MIN_CONFIRMATIONS:
        return None

    # Buscar induccion reciente en M1
    from analysis.induction_detector import find_induction
    window = m1_bars.iloc[max(0, bar_idx - 25): bar_idx + 1]
    induction = find_induction(window, direction)
    if induction is None:
        return None

    # Construir senal
    entry_price = float(candle["close"])
    sl_price    = induction["sl_price"]
    sl_pips     = abs(entry_price - sl_price) / _PIP

    if sl_pips < 1.0:
        return None  # SL demasiado cercano (probable ruido)

    from engine.position_sizer import tp_price
    tp = tp_price(entry_price, sl_price, direction, RISK_REWARD)

    force_body = abs(float(candle["close"]) - float(candle["open"]))
    avg        = _avg_body(m1_bars.iloc[:bar_idx], EXCELLENCE_BODY_LOOKBACK)

    signal = TradeSignal(
        direction       = direction,
        entry_price     = entry_price,
        sl_price        = sl_price,
        tp_price        = tp,
        sl_pips         = round(sl_pips, 1),
        signal_time     = dt_utc,
        cycle           = cycle,
        confirmations   = confirmations,
        induction_price = induction["induction_price"],
        force_body      = force_body,
        avg_body        = avg,
    )
    signal.excellence = _is_excellence(signal, cycle, confirmations, dt_utc)
    return signal


def _evaluate_sierra_sweep(
    bar_idx: int,
    m1_bars: pd.DataFrame,
    asia: dict | None,
    direction: str,
    candle: pd.Series,
    prev_candle: pd.Series,
    divergence_result: dict | None,
    quarters_signal: dict | None,
    magnet_bias: dict | None,
    trades_today: int,
) -> TradeSignal | None:
    """
    Logica especifica para ciclo Sierra:
    Solo opera cuando el precio barre el High o Low del rango errático
    y la vela de fuerza confirma el regreso en direccion contraria.
    """
    if asia is None:
        return None

    dt_utc = candle["datetime"]
    bar_high = float(candle["high"])
    bar_low  = float(candle["low"])

    sierra_high = asia["asia_high"]
    sierra_low  = asia["asia_low"]
    min_sweep   = SIERRA_SWEEP_PIPS * _PIP

    swept_high = bar_high > sierra_high + min_sweep and direction == "short"
    swept_low  = bar_low  < sierra_low  - min_sweep and direction == "long"

    if not swept_high and not swept_low:
        return None

    # En Sierra solo necesitamos 1 confirmacion (el sweep es la señal principal)
    confirmations = _count_confirmations(
        divergence_result, quarters_signal, magnet_bias, direction
    )
    # Incluso sin confirmaciones externas el sweep en Sierra es accionable,
    # pero priorizamos si hay al menos 1
    confirmation_list = confirmations if confirmations else ["sierra_sweep"]

    entry_price = float(candle["close"])
    sl_price    = (sierra_high + SIERRA_SWEEP_PIPS * _PIP) if direction == "short" \
                  else (sierra_low  - SIERRA_SWEEP_PIPS * _PIP)
    sl_pips     = abs(entry_price - sl_price) / _PIP

    if sl_pips < 1.0:
        return None

    from engine.position_sizer import tp_price
    target = sierra_low if direction == "short" else sierra_high
    # TP es el lado opuesto del rango Sierra (no ratio fijo)
    tp = target

    force_body = abs(float(candle["close"]) - float(candle["open"]))
    avg        = _avg_body(m1_bars.iloc[:bar_idx], EXCELLENCE_BODY_LOOKBACK)

    signal = TradeSignal(
        direction       = direction,
        entry_price     = entry_price,
        sl_price        = sl_price,
        tp_price        = tp,
        sl_pips         = round(sl_pips, 1),
        signal_time     = dt_utc,
        cycle           = "Sierra",
        confirmations   = confirmation_list,
        induction_price = entry_price,
        force_body      = force_body,
        avg_body        = avg,
        excellence      = False,
    )
    return signal
