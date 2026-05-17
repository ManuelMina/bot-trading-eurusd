"""
Motor de backtesting walk-forward — Version 2 (sweep-based entry).

Cambios principales respecto a V1:
    - La entrada ya no depende de induccion (pullback generico en los ultimos 25 M1).
    - Se construye un catalogo de niveles clave por dia (Asia H/L, dia anterior,
      semana anterior, magnetos) con pesos segun su antiguedad.
    - La senal se activa cuando el precio BARRE un nivel clave (precio cruza
      el nivel por >= SWEEP_MIN_PIPS desde el lado correcto).
    - La entrada se confirma con una VELA DE FUERZA cuyo cuerpo supera al
      maximo cuerpo de todas las velas desde el barrido.
    - Se agrega el gap semanal como 4a confirmacion opcional.
    - El bucle avanza hasta la barra de resolucion del trade anterior antes
      de buscar el siguiente (corrige solape entre T1 y T2).

Arquitectura de pre-computacion (sin cambios):
    Divergencia, cuartos y magnetos se calculan vectorialmente en M5
    y se unen a M1 con pd.merge_asof antes del bucle principal.

Uso:
    python -m engine.backtester --year 2024
    python -m engine.backtester --year 2025
"""

import argparse
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from config import (
    BACKTEST_YEARS,
    BE_TRIGGER_RR,
    CAPITAL,
    EXCELLENCE_BODY_LOOKBACK,
    EXCELLENCE_BODY_MULT,
    FILTER_KNOCKOUT,
    GAP_MIN_PIPS,
    H1_LOOKBACK_BARS,
    H4_LOOKBACK_DAYS,
    HTF_SWEEP_PIPS,
    MAX_BARS_AFTER_SWEEP,
    MAX_LEVEL_WEIGHT,
    MIN_CONFIRMATIONS,
    MIN_SWEEP_WEIGHT,
    NEWS_BLACKOUTS,
    NY_HOLIDAYS,
    RISK_PCT,
    RISK_REWARD,
    SL_BUFFER_PIPS,
    SWEEP_MIN_PIPS,
    SYMBOL_DIV,
    SYMBOL_MAIN,
    TF_ANALYSIS,
    TF_ENTRY,
    TRADING_T3_CUTOFF,
)

_PIP = 0.0001
_RESULTS_DIR = Path(__file__).parent.parent / "reporting" / "results"
_WINDOW_UTC_START = 12   # 07:00 Colombia / 07:00 NY EST (invierno) — fallback hardcoded
_WINDOW_UTC_END   = 15   # 10:00 Colombia / 10:00 NY EST (invierno)

# ---------------------------------------------------------------------------
# Ventana operativa dinámica — ajusta por horario de verano de NY (DST)
# Colombia no cambia (UTC-5), pero NY cambia EST↔EDT en mar/nov.
# En verano (EDT=UTC-4): 07:00-10:00 NY = 11:00-14:00 UTC
# En invierno (EST=UTC-5): 07:00-10:00 NY = 12:00-15:00 UTC
# ---------------------------------------------------------------------------
from datetime import datetime as _dt, timezone as _tz
from zoneinfo import ZoneInfo as _ZI

_TZ_NY_DYN = _ZI("America/New_York")

def _window_utc(trade_date) -> tuple[int, int]:
    """Devuelve (start_utc_hour, end_utc_hour) para 07:00-10:00 NY con DST correcto."""
    s = _dt(trade_date.year, trade_date.month, trade_date.day, 7, 0, tzinfo=_TZ_NY_DYN)
    e = _dt(trade_date.year, trade_date.month, trade_date.day, 10, 0, tzinfo=_TZ_NY_DYN)
    return s.astimezone(_tz.utc).hour, e.astimezone(_tz.utc).hour


# ---------------------------------------------------------------------------
# Calendario
# ---------------------------------------------------------------------------

def _is_news_blackout(signal_dt: pd.Timestamp, window_min: int = 60) -> bool:
    """True si signal_dt cae dentro de ±window_min minutos de un evento de alto impacto."""
    date_str = signal_dt.strftime("%Y-%m-%d")
    events   = NEWS_BLACKOUTS.get(date_str, [])
    for hhmm in events:
        h, m   = map(int, hhmm.split(":"))
        event  = signal_dt.replace(hour=h, minute=m, second=0, microsecond=0)
        if abs((signal_dt - event).total_seconds()) <= window_min * 60:
            return True
    return False


def _is_trading_day(d: date) -> bool:
    return d.weekday() < 5 and d.isoformat() not in NY_HOLIDAYS


def _trading_days(year: int) -> list[date]:
    d, end, days = date(year, 1, 1), date(year, 12, 31), []
    while d <= end:
        if _is_trading_day(d):
            days.append(d)
        d += timedelta(days=1)
    return days


# ---------------------------------------------------------------------------
# Pre-computacion de senales M5
# ---------------------------------------------------------------------------

def _precompute_signals(m5_eu: pd.DataFrame, m5_gu: pd.DataFrame) -> pd.DataFrame:
    """Calcula divergencia, cuartos y magnetos para todos los timestamps M5."""
    from analysis.divergence import scan as div_scan
    from analysis.opening_magnets import compute as mag_compute
    from analysis.quarters_theory import precompute as q_precompute

    print("  [Pre-calc] Teoria de cuartos...")
    q_df = q_precompute(m5_eu)

    print("  [Pre-calc] Divergencia EURUSD/GBPUSD...")
    div_df = div_scan(m5_eu, m5_gu)
    div_df = div_df[["datetime", "direction"]].rename(columns={"direction": "div_direction"})
    div_df["div_signal"] = True

    print("  [Pre-calc] Aperturas magneto...")
    mag_df = mag_compute(m5_eu)

    sigs = m5_eu[["datetime"]].copy().sort_values("datetime").reset_index(drop=True)
    sigs = sigs.merge(q_df, on="datetime", how="left")
    sigs["_date"] = sigs["datetime"].dt.date

    if not div_df.empty:
        div_df = div_df.copy()
        div_df["_div_date"] = div_df["datetime"].dt.date
        sigs = pd.merge_asof(sigs, div_df.sort_values("datetime"),
                             on="datetime", direction="backward")
        same_day = sigs["_date"] == sigs["_div_date"]
        sigs["div_signal"]    = same_day & sigs["div_signal"].fillna(False)
        sigs["div_direction"] = sigs["div_direction"].where(same_day, other="").fillna("")
        sigs = sigs.drop(columns=["_div_date"], errors="ignore")
    else:
        sigs["div_signal"]    = False
        sigs["div_direction"] = ""

    sigs = sigs.merge(mag_df, left_on="_date", right_on="date", how="left").drop(columns=["date"])
    sigs = sigs.drop(columns=["_date"], errors="ignore")
    return sigs


def _attach_to_m1(m1_df: pd.DataFrame, signals: pd.DataFrame) -> pd.DataFrame:
    return pd.merge_asof(
        m1_df.sort_values("datetime"),
        signals.sort_values("datetime"),
        on="datetime", direction="backward",
    )


# ---------------------------------------------------------------------------
# Simulacion de un trade — retorna tambien el indice de la barra de salida
# ---------------------------------------------------------------------------

def _simulate_trade(
    entry_price: float,
    sl_price:    float,
    tp_price:    float,
    direction:   str,
    entry_bar_idx: int,
    m1_bars: pd.DataFrame,
) -> tuple[str, float, pd.Timestamp | None, int]:
    """
    Simula un trade barra a barra.
    Retorna (result, exit_price, exit_time, exit_bar_idx).
    """
    highs = m1_bars["high"].values
    lows  = m1_bars["low"].values
    times = m1_bars["datetime"].values

    for i in range(entry_bar_idx + 1, len(m1_bars)):
        if direction == "long":
            if lows[i]  <= sl_price: return "loss", sl_price, times[i], i
            if highs[i] >= tp_price: return "win",  tp_price, times[i], i
        else:
            if highs[i] >= sl_price: return "loss", sl_price, times[i], i
            if lows[i]  <= tp_price: return "win",  tp_price, times[i], i

    last = len(m1_bars) - 1
    return "open", entry_price, None, last


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _magnet_bias_from_row(row: pd.Series, price: float) -> dict:
    lvl = row.get("magnet_2")
    if lvl is None or (isinstance(lvl, float) and np.isnan(lvl)):
        return {"magnet_2": None, "agreement": False, "bias": "neutral"}
    bias = "bullish" if price < float(lvl) else "bearish"
    return {"magnet_2": bias, "agreement": True, "bias": bias}


def _count_confirmations_v2(
    div_result: dict,
    q_signal:   dict,
    magnet_bias: dict,
    gap_bias:    str | None,
    direction:   str,
) -> list[str]:
    from engine.entry_logic import _count_confirmations
    active = _count_confirmations(div_result, q_signal, magnet_bias, direction)
    if gap_bias == direction:
        active = active + ["gap"]
    return active


def _avg_body(m1_day: pd.DataFrame, bar_idx: int, lookback: int) -> float:
    start = max(0, bar_idx - lookback)
    recent = m1_day.iloc[start:bar_idx]
    if recent.empty:
        return 0.0
    return float((recent["close"] - recent["open"]).abs().mean())


def _before_t3_cutoff(dt_utc: pd.Timestamp) -> bool:
    """True si la barra UTC esta antes de TRADING_T3_CUTOFF (09:30 Colombia = 14:30 UTC)."""
    h, m = TRADING_T3_CUTOFF.split(":")
    utc_h = int(h) + 5   # Colombia UTC-5
    utc_m = int(m)
    return dt_utc.hour < utc_h or (dt_utc.hour == utc_h and dt_utc.minute < utc_m)


def _tp_path_clear(entry: float, tp: float, direction: str, day_levels: list,
                   pip_buffer: float = 3.0) -> bool:
    """
    True si no hay ningún nivel clave entre entry y TP que pueda bloquear el movimiento.
    Ignora magnetos (weight=1). Usa un buffer de pip_buffer pips para no contar
    niveles que están justo en la entrada o justo en el TP.
    """
    buf = pip_buffer * _PIP
    for lv in day_levels:
        if lv.weight < 2:
            continue
        if lv.name.startswith("eq_"):   # EQH/EQL no bloquean el camino al TP
            continue
        if direction == "long"  and entry + buf < lv.price < tp - buf:
            return False
        if direction == "short" and tp + buf < lv.price < entry - buf:
            return False
    return True


def _market_state_m5(m5_day: pd.DataFrame, before_utc_hour: int) -> str:
    """
    Evalúa el estado del mercado en M5 ANTES de la ventana operativa.
    Retorna: 'consolidation' | 'displacement' | 'ok'

    consolidation : rango de las últimas 15 barras M5 < 8 pips → evitar entrar
    displacement  : últimas 5 barras M5 tienen cuerpos grandes en una sola dirección
                    y esa estructura ya se formó → mercado ya se movió, tarde para entrar
    ok            : mercado en inducción o preparación
    """
    if m5_day is None or m5_day.empty:
        return "ok"

    pre = m5_day[m5_day["datetime"].dt.hour < before_utc_hour].tail(20)
    if len(pre) < 5:
        return "ok"

    rng = float(pre["high"].max() - pre["low"].min()) / _PIP
    if rng < 8:
        return "consolidation"

    last5 = pre.tail(5)
    bodies = (last5["close"] - last5["open"]).values
    if all(b > 0 for b in bodies) or all(b < 0 for b in bodies):
        avg_body = abs(bodies).mean() / _PIP
        if avg_body > 3:
            return "displacement"

    return "ok"


def _tp_price(entry: float, sl: float, direction: str, rr: float) -> float:
    dist = abs(entry - sl)
    return entry + dist * rr if direction == "long" else entry - dist * rr


# ---------------------------------------------------------------------------
# Backtest de un dia — Version 2 (sweep-based)
# ---------------------------------------------------------------------------

def _backtest_day_v2(
    trade_date:       date,
    m1_day:           pd.DataFrame,  # M1 del dia con senales pre-calculadas adjuntas
    day_levels:       list,           # list[Level]
    gap_bias:         str | None,
    cycle:            str,
    capital:          float,
) -> tuple[list[dict], float]:
    """
    Backtest de un dia con logica de barrido (sweep) de niveles clave.

    Flujo por barra M1:
        1. Detectar si el precio barro un nivel clave (cruzo >= SWEEP_MIN_PIPS desde
           el lado correcto segun el cierre anterior).
        2. Si hay un barrido activo y la barra actual es una vela de fuerza
           (cuerpo > maximo cuerpo desde el barrido) con >= MIN_CONFIRMATIONS:
               -> generar senal, simular trade, avanzar al bar de resolucion.
    """
    from engine.position_sizer import calculate

    trades       = []
    trades_today = 0
    daily_done   = False

    # Estado del barrido activo
    sw_active  = False
    sw_dir     = None   # "long" o "short"
    sw_bar     = -1
    sw_extreme = 0.0    # precio extremo del barrido (high para short, low para long)
    sw_name    = ""
    sw_weight  = 0
    sw_body    = 0.0    # cuerpo de la vela del barrido (fijo; la vela de fuerza debe superarlo)

    sweep_pips = SWEEP_MIN_PIPS * _PIP

    for bar_idx in range(len(m1_day)):
        if daily_done:
            break

        row    = m1_day.iloc[bar_idx]
        dt_utc = row["datetime"]

        # Solo dentro de la ventana operativa 07:00-10:00 Colombia (12:00-15:00 UTC)
        if not (_WINDOW_UTC_START <= dt_utc.hour < _WINDOW_UTC_END):
            continue

        if bar_idx == 0:
            continue

        bar_h    = float(row["high"])
        bar_l    = float(row["low"])
        bar_c    = float(row["close"])
        bar_o    = float(row["open"])
        bar_body = abs(bar_c - bar_o)
        prev_c   = float(m1_day.iloc[bar_idx - 1]["close"])

        # ------------------------------------------------------------------
        # 1. Detectar barrido de niveles clave
        # ------------------------------------------------------------------
        # Logica direccional del barrido:
        #   HIGH levels (side="high"): el nivel es resistencia. Barrido = precio sube
        #     sobre el nivel (trampa alcista) y se espera caida -> SHORT.
        #   LOW levels (side="low"): el nivel es soporte. Barrido = precio cae bajo
        #     el nivel (trampa bajista) y se espera subida -> LONG.
        #   "both": magnetos, ambas direcciones posibles.
        best_weight = sw_weight if sw_active else 0
        best_sweep  = None   # (weight, dir, extreme, name)

        for lv in day_levels:
            if lv.weight < MIN_SWEEP_WEIGHT:
                continue

            # Barrido de HIGH -> SHORT (precio cruzó hacia arriba el nivel de resistencia)
            if lv.side in ("high", "both"):
                if prev_c < lv.price and bar_h > lv.price + sweep_pips:
                    if lv.weight > best_weight:
                        best_sweep  = (lv.weight, "short", bar_h, lv.name)
                        best_weight = lv.weight

            # Barrido de LOW -> LONG (precio cruzó hacia abajo el nivel de soporte)
            if lv.side in ("low", "both"):
                if prev_c > lv.price and bar_l < lv.price - sweep_pips:
                    if lv.weight > best_weight:
                        best_sweep  = (lv.weight, "long", bar_l, lv.name)
                        best_weight = lv.weight

        if best_sweep is not None:
            sw_active, sw_weight, sw_dir, sw_extreme, sw_name = (
                True, best_sweep[0], best_sweep[1], best_sweep[2], best_sweep[3]
            )
            sw_bar  = bar_idx
            sw_body = bar_body

        # ------------------------------------------------------------------
        # 2. Verificar vela de fuerza (si hay barrido activo y paso al menos 1 barra)
        #    - La vela de fuerza debe ser >= al cuerpo de la vela del barrido
        #    - Debe aparecer dentro de MAX_BARS_AFTER_SWEEP barras del barrido
        # ------------------------------------------------------------------
        if not sw_active or bar_idx <= sw_bar:
            continue

        # Abandonar barrido si pasaron demasiadas barras sin fuerza
        if bar_idx - sw_bar > MAX_BARS_AFTER_SWEEP:
            sw_active = False
            sw_dir    = None
            sw_bar    = -1
            sw_extreme = 0.0
            sw_name   = ""
            sw_weight  = 0
            sw_body   = 0.0
            continue

        is_force = (
            (sw_dir == "long"  and bar_c > bar_o and bar_body >= sw_body) or
            (sw_dir == "short" and bar_c < bar_o and bar_body >= sw_body)
        )

        if not is_force:
            continue

        # ------------------------------------------------------------------
        # 3. Contar confirmaciones
        # ------------------------------------------------------------------
        div_r  = {"divergence": bool(row.get("div_signal", False)),
                  "direction":  row.get("div_direction", "")}
        q_s    = {"signal":    bool(row.get("q_signal", False)),
                  "direction": row.get("q_direction", None)}
        mb     = _magnet_bias_from_row(row, bar_c)
        confs  = _count_confirmations_v2(div_r, q_s, mb, gap_bias, sw_dir)

        if len(confs) < MIN_CONFIRMATIONS:
            continue

        # ------------------------------------------------------------------
        # 4. Condiciones de excelencia para T3
        # ------------------------------------------------------------------
        avg_b       = _avg_body(m1_day, bar_idx, EXCELLENCE_BODY_LOOKBACK)
        is_excellence = (
            cycle not in ("Unknown", "Sierra") and
            len(confs) >= 3 and
            bar_body >= EXCELLENCE_BODY_MULT * avg_b and
            _before_t3_cutoff(dt_utc)
        )

        if trades_today == 2:
            if not is_excellence:
                continue
            if not all(t["result"] == "win" for t in trades):
                continue

        # ------------------------------------------------------------------
        # 5. Construir senal y simular trade
        # ------------------------------------------------------------------
        entry = bar_c
        sl    = (sw_extreme + SL_BUFFER_PIPS * _PIP) if sw_dir == "short" \
                else (sw_extreme - SL_BUFFER_PIPS * _PIP)
        sl_pips = abs(entry - sl) / _PIP

        # SL debe estar del lado correcto del precio de entrada
        if sw_dir == "long"  and sl >= entry:
            continue
        if sw_dir == "short" and sl <= entry:
            continue
        if sl_pips < 1.0:
            continue

        tp = _tp_price(entry, sl, sw_dir, RISK_REWARD)

        result, exit_p, exit_t, exit_idx = _simulate_trade(
            entry, sl, tp, sw_dir, bar_idx, m1_day
        )
        if result == "open":
            result, exit_p = "loss", sl

        risk_usd = capital * RISK_PCT
        pnl      = risk_usd * RISK_REWARD if result == "win" else -risk_usd
        capital += pnl

        trades.append({
            "date":          trade_date.isoformat(),
            "signal_time":   str(dt_utc),
            "exit_time":     str(exit_t) if exit_t else "",
            "direction":     sw_dir,
            "cycle":         cycle,
            "entry_price":   round(entry, 5),
            "sl_price":      round(sl, 5),
            "tp_price":      round(tp, 5),
            "exit_price":    round(exit_p, 5),
            "sl_pips":       round(sl_pips, 1),
            "lots":          calculate(sl_pips=sl_pips, capital=capital),
            "risk_usd":      round(risk_usd, 2),
            "result":        result,
            "pnl_usd":       round(pnl, 2),
            "capital_after": round(capital, 2),
            "trade_num_day": trades_today + 1,
            "confirmations": "|".join(confs),
            "sweep_level":   sw_name,
            "sweep_weight":  sw_weight,
            "induction_price": round(sw_extreme, 5),   # alias para compatibilidad con report.py
            "excellence":    is_excellence,
        })
        trades_today += 1

        # Resetear estado de barrido
        sw_active  = False
        sw_dir     = None
        sw_bar     = -1
        sw_extreme = 0.0
        sw_name    = ""
        sw_weight  = 0
        sw_body    = 0.0

        if result == "loss" or trades_today >= 3:
            daily_done = True

    return trades, capital


# ---------------------------------------------------------------------------
# Simulacion con Break-Even management (V3)
# ---------------------------------------------------------------------------

def _simulate_trade_be(
    entry_price:   float,
    sl_price:      float,
    tp_price:      float,
    direction:     str,
    entry_bar_idx: int,
    m1_bars:       pd.DataFrame,
    be_rr:         float = BE_TRIGGER_RR,
) -> tuple[str, float, pd.Timestamp | None, int]:
    """
    Simula un trade con gestion de Break-Even.

    Cuando el precio alcanza be_rr x riesgo en positivo, el SL se mueve
    al precio de entrada (break-even). A partir de ese momento el trade
    solo puede terminar en win (TP) o be (SL en entrada = 0 P&L).

    Retorna (result, exit_price, exit_time, exit_bar_idx).
    result: "win" | "loss" | "be" | "open"
    """
    risk      = abs(entry_price - sl_price)
    be_target = (entry_price + be_rr * risk) if direction == "long" \
                else (entry_price - be_rr * risk)

    current_sl   = sl_price
    be_activated = False

    highs = m1_bars["high"].values
    lows  = m1_bars["low"].values
    times = m1_bars["datetime"].values

    for i in range(entry_bar_idx + 1, len(m1_bars)):
        h, l = float(highs[i]), float(lows[i])

        if direction == "long":
            if not be_activated and h >= be_target:
                current_sl   = entry_price
                be_activated = True
            if l <= current_sl:
                return ("be" if be_activated else "loss"), current_sl, times[i], i
            if h >= tp_price:
                return "win", tp_price, times[i], i
        else:
            if not be_activated and l <= be_target:
                current_sl   = entry_price
                be_activated = True
            if h >= current_sl:
                return ("be" if be_activated else "loss"), current_sl, times[i], i
            if l <= tp_price:
                return "win", tp_price, times[i], i

    last = len(m1_bars) - 1
    return "open", entry_price, None, last


# ---------------------------------------------------------------------------
# Backtest de un dia — Version 3 (top-down HTF + induccion V1 + break-even)
# ---------------------------------------------------------------------------

def _backtest_day_v3(
    trade_date: date,
    m1_day:     pd.DataFrame,
    htf_bias:   dict,
    cycle:      str,
    capital:    float,
) -> tuple[list[dict], float]:
    """
    V3: filtro top-down H4/H1 + señal de induccion (logica V1) + break-even.

    Flujo:
        1. Si combined bias != "neutral", solo entrar en esa direccion.
           Si combined == "neutral", no operar ese dia.
        2. Señal: vela de fuerza + >= MIN_CONFIRMATIONS + induccion M1 (25 barras).
        3. Trade: simular con break-even a 1.5× riesgo.
        4. "be" no se cuenta como loss: permite buscar T2.
    """
    from analysis.induction_detector import find_induction
    from engine.entry_logic import _count_confirmations
    from engine.position_sizer import calculate

    combined_bias = htf_bias.get("combined", "neutral")

    # Si no hay sesgo claro en H4/H1, no operar
    if combined_bias == "neutral":
        return [], capital

    trades       = []
    trades_today = 0
    daily_done   = False

    for bar_idx in range(len(m1_day)):
        if daily_done:
            break

        row    = m1_day.iloc[bar_idx]
        dt_utc = row["datetime"]

        if not (_WINDOW_UTC_START <= dt_utc.hour < _WINDOW_UTC_END):
            continue
        if bar_idx < EXCELLENCE_BODY_LOOKBACK + 2:
            continue

        bar_c = float(row["close"]); bar_o = float(row["open"])
        bar_body = abs(bar_c - bar_o)

        if bar_idx == 0:
            continue
        prev = m1_day.iloc[bar_idx - 1]
        prev_body = abs(float(prev["close"]) - float(prev["open"]))

        if bar_body <= prev_body:
            continue

        direction = "long" if bar_c > bar_o else ("short" if bar_c < bar_o else None)
        if direction is None:
            continue

        # Filtro HTF: solo entrar en la direccion del sesgo H4/H1
        if direction != combined_bias:
            continue

        # Confirmaciones (misma logica V1)
        div_r = {"divergence": bool(row.get("div_signal", False)),
                 "direction":  row.get("div_direction", "")}
        q_s   = {"signal":    bool(row.get("q_signal", False)),
                 "direction": row.get("q_direction", None)}
        mb    = _magnet_bias_from_row(row, bar_c)
        confs = _count_confirmations(div_r, q_s, mb, direction)

        if len(confs) < MIN_CONFIRMATIONS:
            continue

        # Induccion en ventana M1 de 25 barras
        window    = m1_day.iloc[max(0, bar_idx - 25): bar_idx + 1]
        induction = find_induction(window, direction)
        if induction is None:
            continue

        entry   = bar_c
        sl      = induction["sl_price"]
        sl_pips = abs(entry - sl) / _PIP

        if sl_pips < 1.0:
            continue
        if direction == "long"  and sl >= entry:
            continue
        if direction == "short" and sl <= entry:
            continue

        tp = _tp_price(entry, sl, direction, RISK_REWARD)

        # Excelencia T3
        avg_b = _avg_body(m1_day, bar_idx, EXCELLENCE_BODY_LOOKBACK)
        is_excellence = (
            cycle not in ("Unknown", "Sierra") and
            len(confs) >= 3 and
            bar_body >= EXCELLENCE_BODY_MULT * avg_b and
            _before_t3_cutoff(dt_utc)
        )

        if trades_today == 2:
            if not is_excellence:
                continue
            if not all(t["result"] in ("win", "be") for t in trades):
                continue

        # Simular con break-even
        result, exit_p, exit_t, exit_idx = _simulate_trade_be(
            entry, sl, tp, direction, bar_idx, m1_day
        )
        if result == "open":
            result, exit_p = "loss", sl

        risk_usd = capital * RISK_PCT
        pnl = (risk_usd * RISK_REWARD if result == "win"
               else 0.0 if result == "be"
               else -risk_usd)
        capital += pnl

        trades.append({
            "date":            trade_date.isoformat(),
            "signal_time":     str(dt_utc),
            "exit_time":       str(exit_t) if exit_t else "",
            "direction":       direction,
            "cycle":           cycle,
            "entry_price":     round(entry,  5),
            "sl_price":        round(sl,     5),
            "tp_price":        round(tp,     5),
            "exit_price":      round(exit_p, 5),
            "sl_pips":         round(sl_pips, 1),
            "lots":            calculate(sl_pips=sl_pips, capital=capital),
            "risk_usd":        round(risk_usd, 2),
            "result":          result,
            "pnl_usd":         round(pnl, 2),
            "capital_after":   round(capital, 2),
            "trade_num_day":   trades_today + 1,
            "confirmations":   "|".join(confs),
            "induction_price": round(induction["induction_price"], 5),
            "excellence":      is_excellence,
            "h4_bias":         htf_bias.get("h4_bias", "neutral"),
            "h1_bias":         htf_bias.get("h1_bias", "neutral"),
            "htf_combined":    combined_bias,
        })
        trades_today += 1

        # BE no es loss → permite buscar T2
        if result == "loss" or trades_today >= 3:
            daily_done = True

    return trades, capital


# ---------------------------------------------------------------------------
# Backtest completo del ano
# ---------------------------------------------------------------------------

def run_v3(year: int, initial_capital: float = CAPITAL) -> pd.DataFrame:
    """Ejecuta el backtest V3 (HTF top-down + induccion V1 + break-even)."""
    print(f"\n[BACKTEST V3] Ano {year} -- capital inicial: ${initial_capital:,.2f}")

    from data.fetcher import load
    from analysis.asia_range import compute as ar_compute, get_for_date
    from analysis.cycle_detector import compute as cd_compute
    from analysis.htf_structure import get_htf_bias
    from analysis.opening_magnets import compute as mag_compute

    print("  Cargando datos...")
    m1_eu = load(SYMBOL_MAIN, TF_ENTRY,    year)
    m5_eu = load(SYMBOL_MAIN, TF_ANALYSIS, year)
    m5_gu = load(SYMBOL_DIV,  TF_ANALYSIS, year)

    print("  Calculando rango Asia y ciclos...")
    asia_df   = ar_compute(m1_eu)
    cycles_df = cd_compute(m5_eu, asia_df)

    print("  Pre-calculando senales M5...")
    sigs         = _precompute_signals(m5_eu, m5_gu)
    m1_with_sigs = _attach_to_m1(m1_eu, sigs)

    trading_days = _trading_days(year)
    print(f"  Dias operativos: {len(trading_days)}")

    all_trades = []
    capital    = initial_capital
    htf_neutral_days = 0

    for i, d in enumerate(trading_days):
        cycle_row = cycles_df[cycles_df["date"] == d]
        cycle     = cycle_row.iloc[0]["cycle"] if not cycle_row.empty else "Unknown"

        if cycle == "Unknown":
            continue
        if FILTER_KNOCKOUT and cycle == "Knockout":
            continue

        asia = get_for_date(asia_df, d)

        # Sesgo H4/H1 del dia (solo barras previas a 12:00 UTC)
        htf_bias = get_htf_bias(
            m1_eu, d,
            sweep_pips=HTF_SWEEP_PIPS,
            h4_lookback_days=H4_LOOKBACK_DAYS,
            h1_lookback_bars=H1_LOOKBACK_BARS,
        )
        if htf_bias["combined"] == "neutral":
            htf_neutral_days += 1
            continue

        day_mask = m1_with_sigs["datetime"].dt.date == d
        m1_day   = m1_with_sigs[day_mask].reset_index(drop=True)
        if m1_day.empty:
            continue

        day_trades, capital = _backtest_day_v3(d, m1_day, htf_bias, cycle, capital)
        all_trades.extend(day_trades)

        if (i + 1) % 50 == 0:
            print(f"  [{i+1}/{len(trading_days)}] {d} | capital: ${capital:,.2f} | trades: {len(all_trades)}")

    print(f"\n  Dias sin sesgo HTF (neutral): {htf_neutral_days}")
    print(f"  Trades totales: {len(all_trades)}")
    print(f"  Capital final:  ${capital:,.2f}")
    print(f"  P&L total:      ${capital - initial_capital:+,.2f}")

    df = pd.DataFrame(all_trades)
    if not df.empty:
        wins  = (df["result"] == "win").sum()
        bes   = (df["result"] == "be").sum()
        total = len(df)
        print(f"  Win rate:       {wins}/{total} = {100*wins/total:.1f}%")
        print(f"  Break-even:     {bes}/{total} = {100*bes/total:.1f}%")

    return df


def run(year: int, initial_capital: float = CAPITAL) -> pd.DataFrame:
    """Ejecuta el backtest completo para un ano. Retorna DataFrame de trades."""
    print(f"\n[BACKTEST V2] Ano {year} -- capital inicial: ${initial_capital:,.2f}")

    from data.fetcher import load
    from analysis.asia_range import compute as ar_compute, get_for_date
    from analysis.cycle_detector import compute as cd_compute
    from analysis.levels import (
        precompute_daily_hl, precompute_weekly_hl, build_day_levels
    )
    from analysis.gap_detector import detect_weekly_gaps, get_gap_bias
    from analysis.opening_magnets import compute as mag_compute

    print("  Cargando datos...")
    m1_eu = load(SYMBOL_MAIN, TF_ENTRY,    year)
    m5_eu = load(SYMBOL_MAIN, TF_ANALYSIS, year)
    m5_gu = load(SYMBOL_DIV,  TF_ANALYSIS, year)

    print("  Calculando rango Asia y ciclos...")
    asia_df   = ar_compute(m1_eu)
    cycles_df = cd_compute(m5_eu, asia_df)

    print("  Pre-calculando senales M5...")
    sigs         = _precompute_signals(m5_eu, m5_gu)
    m1_with_sigs = _attach_to_m1(m1_eu, sigs)

    print("  Pre-calculando niveles (daily/weekly OHLC, gaps)...")
    daily_hl  = precompute_daily_hl(m1_eu)
    weekly_hl = precompute_weekly_hl(m1_eu)
    gaps_df   = detect_weekly_gaps(m1_eu, min_pips=GAP_MIN_PIPS)
    mag_df    = mag_compute(m5_eu)   # date, magnet_2

    trading_days = _trading_days(year)
    print(f"  Dias operativos: {len(trading_days)}")

    all_trades = []
    capital    = initial_capital

    for i, d in enumerate(trading_days):
        asia      = get_for_date(asia_df, d)
        cycle_row = cycles_df[cycles_df["date"] == d]
        cycle     = cycle_row.iloc[0]["cycle"] if not cycle_row.empty else "Unknown"

        if cycle == "Unknown":
            continue
        if FILTER_KNOCKOUT and cycle == "Knockout":
            continue

        # Magneto 07:30 NY
        mag_row = mag_df[mag_df["date"] == d]
        mag2 = float(mag_row.iloc[0]["magnet_2"]) if not mag_row.empty and pd.notna(mag_row.iloc[0]["magnet_2"]) else None

        # Gap semanal como 4a confirmacion
        gap_bias = get_gap_bias(gaps_df, d)

        # Catalogo de niveles del dia
        day_levels = build_day_levels(
            d, asia, None, mag2, daily_hl, weekly_hl,
            min_weight=MIN_SWEEP_WEIGHT, max_weight=MAX_LEVEL_WEIGHT,
        )

        # M1 del dia con senales adjuntas
        day_mask = m1_with_sigs["datetime"].dt.date == d
        m1_day   = m1_with_sigs[day_mask].reset_index(drop=True)
        if m1_day.empty:
            continue

        day_trades, capital = _backtest_day_v2(d, m1_day, day_levels, gap_bias, cycle, capital)
        all_trades.extend(day_trades)

        if (i + 1) % 50 == 0:
            print(f"  [{i+1}/{len(trading_days)}] {d} | capital: ${capital:,.2f} | trades: {len(all_trades)}")

    print(f"\n  Trades totales: {len(all_trades)}")
    print(f"  Capital final:  ${capital:,.2f}")
    print(f"  P&L total:      ${capital - initial_capital:+,.2f}")

    df = pd.DataFrame(all_trades)
    if not df.empty:
        wins = (df["result"] == "win").sum()
        total = len(df)
        print(f"  Win rate:       {wins}/{total} = {100*wins/total:.1f}%")

    return df


# ---------------------------------------------------------------------------
# Backtest de un dia — Version 4 (solo niveles top + HTF veto + break-even)
# ---------------------------------------------------------------------------

# Únicos niveles que demostraron WR > break-even en V2+KO (2024 y 2025)
_V4_VALID_LEVELS = {"asia_high", "prev_day_low"}


def _backtest_day_v4(
    trade_date: date,
    m1_day:     pd.DataFrame,
    day_levels: list,
    gap_bias:   str | None,
    cycle:      str,
    htf_bias:   dict,
    capital:    float,
) -> tuple[list[dict], float]:
    """
    V4: solo asia_high→SHORT y prev_day_low→LONG
        + filtro HTF como veto direccional (no bloquea días enteros)
        + señal de barrido V2 (sweep + vela de fuerza + confirmaciones)
        + break-even al 1.5× riesgo

    Lógica HTF:
        asia_high → SHORT : se ejecuta si htf_combined en {"short", "neutral"}
        prev_day_low → LONG: se ejecuta si htf_combined en {"long",  "neutral"}
        Si htf contradice la dirección del nivel → se descarta ese barrido.
    """
    from engine.position_sizer import calculate

    combined = htf_bias.get("combined", "neutral")

    trades       = []
    trades_today = 0
    daily_done   = False

    sw_active  = False
    sw_dir     = None
    sw_bar     = -1
    sw_extreme = 0.0
    sw_name    = ""
    sw_weight  = 0
    sw_body    = 0.0

    sweep_pips = SWEEP_MIN_PIPS * _PIP

    for bar_idx in range(len(m1_day)):
        if daily_done:
            break

        row    = m1_day.iloc[bar_idx]
        dt_utc = row["datetime"]

        if not (_WINDOW_UTC_START <= dt_utc.hour < _WINDOW_UTC_END):
            continue
        if bar_idx == 0:
            continue

        bar_h    = float(row["high"])
        bar_l    = float(row["low"])
        bar_c    = float(row["close"])
        bar_o    = float(row["open"])
        bar_body = abs(bar_c - bar_o)
        prev_c   = float(m1_day.iloc[bar_idx - 1]["close"])

        # ------------------------------------------------------------------
        # 1. Detectar barrido — solo niveles válidos y alineados con HTF
        # ------------------------------------------------------------------
        best_weight = sw_weight if sw_active else 0
        best_sweep  = None

        for lv in day_levels:
            if lv.name not in _V4_VALID_LEVELS:
                continue
            if lv.weight < MIN_SWEEP_WEIGHT:
                continue

            # asia_high → SHORT
            if lv.side in ("high", "both"):
                if prev_c < lv.price and bar_h > lv.price + sweep_pips:
                    # Veto HTF: solo si HTF dice short o neutral
                    if combined not in ("short", "neutral"):
                        continue
                    if lv.weight > best_weight:
                        best_sweep  = (lv.weight, "short", bar_h, lv.name)
                        best_weight = lv.weight

            # prev_day_low → LONG
            if lv.side in ("low", "both"):
                if prev_c > lv.price and bar_l < lv.price - sweep_pips:
                    # Veto HTF: solo si HTF dice long o neutral
                    if combined not in ("long", "neutral"):
                        continue
                    if lv.weight > best_weight:
                        best_sweep  = (lv.weight, "long", bar_l, lv.name)
                        best_weight = lv.weight

        if best_sweep is not None:
            sw_active, sw_weight, sw_dir, sw_extreme, sw_name = (
                True, best_sweep[0], best_sweep[1], best_sweep[2], best_sweep[3]
            )
            sw_bar  = bar_idx
            sw_body = bar_body

        # ------------------------------------------------------------------
        # 2. Vela de fuerza tras el barrido
        # ------------------------------------------------------------------
        if not sw_active or bar_idx <= sw_bar:
            continue

        if bar_idx - sw_bar > MAX_BARS_AFTER_SWEEP:
            sw_active = False; sw_dir = None; sw_bar = -1
            sw_extreme = 0.0; sw_name = ""; sw_weight = 0; sw_body = 0.0
            continue

        is_force = (
            (sw_dir == "long"  and bar_c > bar_o and bar_body >= sw_body) or
            (sw_dir == "short" and bar_c < bar_o and bar_body >= sw_body)
        )
        if not is_force:
            continue

        # ------------------------------------------------------------------
        # 3. Confirmaciones (igual que V2)
        # ------------------------------------------------------------------
        div_r = {"divergence": bool(row.get("div_signal", False)),
                 "direction":  row.get("div_direction", "")}
        q_s   = {"signal":    bool(row.get("q_signal", False)),
                 "direction": row.get("q_direction", None)}
        mb    = _magnet_bias_from_row(row, bar_c)
        confs = _count_confirmations_v2(div_r, q_s, mb, gap_bias, sw_dir)

        if len(confs) < MIN_CONFIRMATIONS:
            continue

        # ------------------------------------------------------------------
        # 4. Excelencia T3
        # ------------------------------------------------------------------
        avg_b = _avg_body(m1_day, bar_idx, EXCELLENCE_BODY_LOOKBACK)
        is_excellence = (
            cycle not in ("Unknown", "Sierra") and
            len(confs) >= 3 and
            bar_body >= EXCELLENCE_BODY_MULT * avg_b and
            _before_t3_cutoff(dt_utc)
        )

        if trades_today == 2:
            if not is_excellence:
                continue
            if not all(t["result"] in ("win", "be") for t in trades):
                continue

        # ------------------------------------------------------------------
        # 5. Filtro de noticias — saltar si estamos cerca de evento macro
        # ------------------------------------------------------------------
        if _is_news_blackout(dt_utc):
            sw_active = False; sw_dir = None; sw_bar = -1
            sw_extreme = 0.0; sw_name = ""; sw_weight = 0; sw_body = 0.0
            continue

        # ------------------------------------------------------------------
        # 6. Construir señal y simular con break-even
        # ------------------------------------------------------------------
        entry   = bar_c
        sl      = (sw_extreme + SL_BUFFER_PIPS * _PIP) if sw_dir == "short" \
                  else (sw_extreme - SL_BUFFER_PIPS * _PIP)
        sl_pips = abs(entry - sl) / _PIP

        if sw_dir == "long"  and sl >= entry: continue
        if sw_dir == "short" and sl <= entry: continue
        if sl_pips < 1.0: continue

        tp = _tp_price(entry, sl, sw_dir, RISK_REWARD)

        result, exit_p, exit_t, exit_idx = _simulate_trade_be(
            entry, sl, tp, sw_dir, bar_idx, m1_day
        )
        if result == "open":
            result, exit_p = "loss", sl

        risk_usd = capital * RISK_PCT
        pnl = (risk_usd * RISK_REWARD if result == "win"
               else 0.0 if result == "be"
               else -risk_usd)
        capital += pnl

        trades.append({
            "date":          trade_date.isoformat(),
            "signal_time":   str(dt_utc),
            "exit_time":     str(exit_t) if exit_t else "",
            "direction":     sw_dir,
            "cycle":         cycle,
            "entry_price":   round(entry,    5),
            "sl_price":      round(sl,       5),
            "tp_price":      round(tp,       5),
            "exit_price":    round(exit_p,   5),
            "sl_pips":       round(sl_pips,  1),
            "lots":          calculate(sl_pips=sl_pips, capital=capital),
            "risk_usd":      round(risk_usd, 2),
            "result":        result,
            "pnl_usd":       round(pnl,      2),
            "capital_after": round(capital,  2),
            "trade_num_day": trades_today + 1,
            "confirmations": "|".join(confs),
            "sweep_level":   sw_name,
            "sweep_weight":  sw_weight,
            "induction_price": round(sw_extreme, 5),
            "excellence":    is_excellence,
            "h4_bias":       htf_bias.get("h4_bias",  "neutral"),
            "h1_bias":       htf_bias.get("h1_bias",  "neutral"),
            "htf_combined":  combined,
        })
        trades_today += 1

        sw_active = False; sw_dir = None; sw_bar = -1
        sw_extreme = 0.0; sw_name = ""; sw_weight = 0; sw_body = 0.0

        # BE no cuenta como pérdida → permite buscar T2
        if result == "loss" or trades_today >= 3:
            daily_done = True

    return trades, capital


# ---------------------------------------------------------------------------
# Backtest completo del año — Version 4
# ---------------------------------------------------------------------------

def run_v4(year: int, initial_capital: float = CAPITAL) -> pd.DataFrame:
    """
    V4: solo asia_high→SHORT y prev_day_low→LONG
        + veto HTF H4/H1 (no bloquea días, solo veta si hay contradicción)
        + señal de barrido V2 + break-even 1.5:1
        + FILTER_KNOCKOUT activo
    """
    print(f"\n[BACKTEST V4] Ano {year} -- capital inicial: ${initial_capital:,.2f}")

    from data.fetcher import load
    from analysis.asia_range import compute as ar_compute, get_for_date
    from analysis.cycle_detector import compute as cd_compute
    from analysis.levels import precompute_daily_hl, precompute_weekly_hl, build_day_levels
    from analysis.gap_detector import detect_weekly_gaps, get_gap_bias
    from analysis.opening_magnets import compute as mag_compute
    from analysis.htf_structure import get_htf_bias

    print("  Cargando datos...")
    m1_eu = load(SYMBOL_MAIN, TF_ENTRY,    year)
    m5_eu = load(SYMBOL_MAIN, TF_ANALYSIS, year)
    m5_gu = load(SYMBOL_DIV,  TF_ANALYSIS, year)

    print("  Calculando rango Asia y ciclos...")
    asia_df   = ar_compute(m1_eu)
    cycles_df = cd_compute(m5_eu, asia_df)

    print("  Pre-calculando senales M5...")
    sigs         = _precompute_signals(m5_eu, m5_gu)
    m1_with_sigs = _attach_to_m1(m1_eu, sigs)

    print("  Pre-calculando niveles (daily/weekly OHLC, gaps)...")
    daily_hl  = precompute_daily_hl(m1_eu)
    weekly_hl = precompute_weekly_hl(m1_eu)
    gaps_df   = detect_weekly_gaps(m1_eu, min_pips=GAP_MIN_PIPS)
    mag_df    = mag_compute(m5_eu)

    trading_days = _trading_days(year)
    print(f"  Dias operativos: {len(trading_days)}")

    all_trades      = []
    capital         = initial_capital
    htf_veto_days   = 0
    no_level_days   = 0

    for i, d in enumerate(trading_days):
        cycle_row = cycles_df[cycles_df["date"] == d]
        cycle     = cycle_row.iloc[0]["cycle"] if not cycle_row.empty else "Unknown"

        if cycle == "Unknown":
            continue
        if FILTER_KNOCKOUT and cycle == "Knockout":
            continue

        asia    = get_for_date(asia_df, d)
        gap_bias = get_gap_bias(gaps_df, d)

        mag_row = mag_df[mag_df["date"] == d]
        mag2 = float(mag_row.iloc[0]["magnet_2"]) if not mag_row.empty and pd.notna(mag_row.iloc[0]["magnet_2"]) else None

        day_levels = build_day_levels(
            d, asia, None, mag2, daily_hl, weekly_hl,
            min_weight=MIN_SWEEP_WEIGHT, max_weight=MAX_LEVEL_WEIGHT,
        )

        # Filtrar solo los niveles válidos V4
        v4_levels = [lv for lv in day_levels if lv.name in _V4_VALID_LEVELS]
        if not v4_levels:
            no_level_days += 1
            continue

        # Sesgo H4/H1 (veto, no gate total)
        htf_bias = get_htf_bias(
            m1_eu, d,
            sweep_pips=HTF_SWEEP_PIPS,
            h4_lookback_days=H4_LOOKBACK_DAYS,
            h1_lookback_bars=H1_LOOKBACK_BARS,
        )

        day_mask = m1_with_sigs["datetime"].dt.date == d
        m1_day   = m1_with_sigs[day_mask].reset_index(drop=True)
        if m1_day.empty:
            continue

        day_trades, capital = _backtest_day_v4(
            d, m1_day, day_levels, gap_bias, cycle, htf_bias, capital
        )
        all_trades.extend(day_trades)

        if (i + 1) % 50 == 0:
            print(f"  [{i+1}/{len(trading_days)}] {d} | capital: ${capital:,.2f} | trades: {len(all_trades)}")

    print(f"\n  Dias sin nivel V4 disponible: {no_level_days}")
    print(f"  Trades totales: {len(all_trades)}")
    print(f"  Capital final:  ${capital:,.2f}")
    print(f"  P&L total:      ${capital - initial_capital:+,.2f}")

    df = pd.DataFrame(all_trades)
    if not df.empty:
        wins  = (df["result"] == "win").sum()
        bes   = (df["result"] == "be").sum()
        total = len(df)
        print(f"  Win rate:       {wins}/{total} = {100*wins/total:.1f}%")
        print(f"  Break-even:     {bes}/{total} = {100*bes/total:.1f}%")
        if "htf_combined" in df.columns:
            for htf_val, g in df.groupby("htf_combined"):
                w = (g["result"] == "win").sum()
                t = len(g)
                print(f"  HTF {htf_val}: {t} trades, WR={100*w/t:.1f}%")
        if "sweep_level" in df.columns:
            for lvl, g in df.groupby("sweep_level"):
                w = (g["result"] == "win").sum()
                t = len(g)
                p = g["pnl_usd"].sum()
                print(f"  {lvl}: {t} trades, WR={100*w/t:.1f}%, PnL={p:+.2f}")

    return df


# ---------------------------------------------------------------------------
# Backtest de un dia — Version 5 (reescrita)
# Mejoras sobre V4:
#   • Ventana operativa dinámica (DST NY) — win_start/win_end por día
#   • EQH/EQL como niveles adicionales de liquidez (peso 2, side high/low)
#   • 3 categorías de niveles con HTF distinto:
#       Premium (asia_high, prev_day_low): HTF permisivo (neutral OK)
#       EQ (eq_high, eq_low): igual que premium
#       Débiles (asia_low, prev_day_high): HTF debe confirmar (strict)
#   • Magnetos opcionales: no cuentan para MIN_CONFIRMATIONS,
#       pero confidence="high" si confirman (ayudan a excelencia T3)
#   • TP path check: saltar si hay nivel bloqueando el camino al TP
#   • Market state: saltar día si pre-ventana muestra consolidación M5
#   • Break-even 1.5:1 + FILTER_KNOCKOUT + filtro de noticias
# ---------------------------------------------------------------------------

_V5_PREMIUM_LEVELS = {"asia_high", "prev_day_low"}
_V5_EQ_LEVELS      = {"eq_high",   "eq_low"}
_V5_WEAK_LEVELS    = {"asia_low",  "prev_day_high"}


def _backtest_day_v5(
    trade_date: date,
    m1_day:     pd.DataFrame,
    day_levels: list,
    gap_bias:   str | None,
    cycle:      str,
    htf_bias:   dict,
    capital:    float,
    m5_day:     pd.DataFrame | None,
    win_start:  int,
    win_end:    int,
) -> tuple[list[dict], float]:
    """
    V5: barrido en niveles premium + EQH/EQL + débiles
        + ventana dinámica DST + magnetos opcionales + TP path check
        + market state check + break-even 1.5:1 + noticias
    """
    from engine.position_sizer import calculate

    combined  = htf_bias.get("combined", "neutral")
    mkt_state = _market_state_m5(m5_day, win_start)
    if mkt_state == "consolidation":
        return [], capital

    trades       = []
    trades_today = 0
    daily_done   = False

    sw_active  = False
    sw_dir     = None
    sw_bar     = -1
    sw_extreme = 0.0
    sw_name    = ""
    sw_weight  = 0
    sw_body    = 0.0

    sweep_pips  = SWEEP_MIN_PIPS * _PIP
    _neutral_mb = {"magnet_2": None, "agreement": False, "bias": "neutral"}

    for bar_idx in range(len(m1_day)):
        if daily_done:
            break

        row    = m1_day.iloc[bar_idx]
        dt_utc = row["datetime"]

        if not (win_start <= dt_utc.hour < win_end):
            continue
        if bar_idx == 0:
            continue

        bar_h    = float(row["high"])
        bar_l    = float(row["low"])
        bar_c    = float(row["close"])
        bar_o    = float(row["open"])
        bar_body = abs(bar_c - bar_o)
        prev_c   = float(m1_day.iloc[bar_idx - 1]["close"])

        if _is_news_blackout(dt_utc):
            sw_active = False; sw_dir = None; sw_bar = -1
            sw_extreme = 0.0; sw_name = ""; sw_weight = 0; sw_body = 0.0
            continue

        # 1. Detectar barrido
        best_weight = sw_weight if sw_active else 0
        best_sweep  = None

        for lv in day_levels:
            if lv.weight < MIN_SWEEP_WEIGHT:
                continue

            is_premium = lv.name in _V5_PREMIUM_LEVELS
            is_eq      = lv.name in _V5_EQ_LEVELS
            is_weak    = lv.name in _V5_WEAK_LEVELS

            if lv.side in ("high", "both"):
                if prev_c < lv.price and bar_h > lv.price + sweep_pips:
                    if (is_premium or is_eq) and combined == "long":
                        continue
                    if is_weak and combined != "short":
                        continue
                    if lv.weight > best_weight:
                        best_sweep  = (lv.weight, "short", bar_h, lv.name)
                        best_weight = lv.weight

            if lv.side in ("low", "both"):
                if prev_c > lv.price and bar_l < lv.price - sweep_pips:
                    if (is_premium or is_eq) and combined == "short":
                        continue
                    if is_weak and combined != "long":
                        continue
                    if lv.weight > best_weight:
                        best_sweep  = (lv.weight, "long", bar_l, lv.name)
                        best_weight = lv.weight

        if best_sweep is not None:
            sw_active, sw_weight, sw_dir, sw_extreme, sw_name = (
                True, best_sweep[0], best_sweep[1], best_sweep[2], best_sweep[3]
            )
            sw_bar  = bar_idx
            sw_body = bar_body

        # 2. Vela de fuerza
        if not sw_active or bar_idx <= sw_bar:
            continue

        if bar_idx - sw_bar > MAX_BARS_AFTER_SWEEP:
            sw_active = False; sw_dir = None; sw_bar = -1
            sw_extreme = 0.0; sw_name = ""; sw_weight = 0; sw_body = 0.0
            continue

        is_force = (
            (sw_dir == "long"  and bar_c > bar_o and bar_body >= sw_body) or
            (sw_dir == "short" and bar_c < bar_o and bar_body >= sw_body)
        )
        if not is_force:
            continue

        # 3. Confirmaciones (magnetos opcionales — no requeridos para MIN_CONFIRMATIONS)
        div_r = {"divergence": bool(row.get("div_signal", False)),
                 "direction":  row.get("div_direction", "")}
        q_s   = {"signal":    bool(row.get("q_signal", False)),
                 "direction": row.get("q_direction", None)}

        confs_base = _count_confirmations_v2(div_r, q_s, _neutral_mb, gap_bias, sw_dir)

        if len(confs_base) < MIN_CONFIRMATIONS:
            continue

        mb      = _magnet_bias_from_row(row, bar_c)
        mag_dir = "bullish" if sw_dir == "long" else "bearish"
        if mb.get("bias") == mag_dir:
            confs_all  = confs_base + ["magnets"]
            confidence = "high"
        else:
            confs_all  = confs_base
            confidence = "normal"

        # 4. Excelencia T3
        avg_b = _avg_body(m1_day, bar_idx, EXCELLENCE_BODY_LOOKBACK)
        is_excellence = (
            cycle not in ("Unknown", "Sierra") and
            len(confs_all) >= 3 and
            bar_body >= EXCELLENCE_BODY_MULT * avg_b and
            _before_t3_cutoff(dt_utc)
        )

        if trades_today == 2:
            if not is_excellence:
                continue
            if not all(t["result"] in ("win", "be") for t in trades):
                continue

        # 5. Construir señal
        entry   = bar_c
        sl      = (sw_extreme + SL_BUFFER_PIPS * _PIP) if sw_dir == "short" \
                  else (sw_extreme - SL_BUFFER_PIPS * _PIP)
        sl_pips = abs(entry - sl) / _PIP

        if sw_dir == "long"  and sl >= entry: continue
        if sw_dir == "short" and sl <= entry: continue
        if sl_pips < 1.0: continue

        tp = _tp_price(entry, sl, sw_dir, RISK_REWARD)

        # 6. TP path check
        if not _tp_path_clear(entry, tp, sw_dir, day_levels):
            sw_active = False; sw_dir = None; sw_bar = -1
            sw_extreme = 0.0; sw_name = ""; sw_weight = 0; sw_body = 0.0
            continue

        result, exit_p, exit_t, exit_idx = _simulate_trade_be(
            entry, sl, tp, sw_dir, bar_idx, m1_day
        )
        if result == "open":
            result, exit_p = "loss", sl

        risk_usd = capital * RISK_PCT
        pnl = (risk_usd * RISK_REWARD if result == "win"
               else 0.0 if result == "be"
               else -risk_usd)
        capital += pnl

        trades.append({
            "date":            trade_date.isoformat(),
            "signal_time":     str(dt_utc),
            "exit_time":       str(exit_t) if exit_t else "",
            "direction":       sw_dir,
            "cycle":           cycle,
            "entry_price":     round(entry,    5),
            "sl_price":        round(sl,       5),
            "tp_price":        round(tp,       5),
            "exit_price":      round(exit_p,   5),
            "sl_pips":         round(sl_pips,  1),
            "lots":            calculate(sl_pips=sl_pips, capital=capital),
            "risk_usd":        round(risk_usd, 2),
            "result":          result,
            "pnl_usd":         round(pnl,      2),
            "capital_after":   round(capital,  2),
            "trade_num_day":   trades_today + 1,
            "confirmations":   "|".join(confs_all),
            "sweep_level":     sw_name,
            "sweep_weight":    sw_weight,
            "induction_price": round(sw_extreme, 5),
            "excellence":      is_excellence,
            "confidence":      confidence,
            "market_state":    mkt_state,
            "h4_bias":         htf_bias.get("h4_bias",  "neutral"),
            "h1_bias":         htf_bias.get("h1_bias",  "neutral"),
            "htf_combined":    combined,
        })
        trades_today += 1

        sw_active = False; sw_dir = None; sw_bar = -1
        sw_extreme = 0.0; sw_name = ""; sw_weight = 0; sw_body = 0.0

        if result == "loss" or trades_today >= 3:
            daily_done = True

    return trades, capital


# ---------------------------------------------------------------------------
# Backtest completo del año — Version 5
# ---------------------------------------------------------------------------

def run_v5(year: int, initial_capital: float = CAPITAL) -> pd.DataFrame:
    """
    V5: barrido en niveles expandidos (premium + EQH/EQL + débiles)
        + ventana DST dinámica + magnetos opcionales + TP path check
        + market state + break-even 1.5:1 + FILTER_KNOCKOUT + noticias
    """
    print(f"\n[BACKTEST V5] Ano {year} -- capital inicial: ${initial_capital:,.2f}")

    from data.fetcher import load
    from analysis.asia_range import compute as ar_compute, get_for_date
    from analysis.cycle_detector import compute as cd_compute
    from analysis.equal_levels import find_equal_levels
    from analysis.levels import precompute_daily_hl, precompute_weekly_hl, build_day_levels
    from analysis.gap_detector import detect_weekly_gaps, get_gap_bias
    from analysis.opening_magnets import compute as mag_compute
    from analysis.htf_structure import get_htf_bias

    print("  Cargando datos...")
    m1_eu = load(SYMBOL_MAIN, TF_ENTRY,    year)
    m5_eu = load(SYMBOL_MAIN, TF_ANALYSIS, year)
    m5_gu = load(SYMBOL_DIV,  TF_ANALYSIS, year)

    print("  Calculando rango Asia y ciclos...")
    asia_df   = ar_compute(m1_eu)
    cycles_df = cd_compute(m5_eu, asia_df)

    print("  Pre-calculando senales M5...")
    sigs         = _precompute_signals(m5_eu, m5_gu)
    m1_with_sigs = _attach_to_m1(m1_eu, sigs)

    print("  Pre-calculando niveles (daily/weekly OHLC, gaps)...")
    daily_hl  = precompute_daily_hl(m1_eu)
    weekly_hl = precompute_weekly_hl(m1_eu)
    gaps_df   = detect_weekly_gaps(m1_eu, min_pips=GAP_MIN_PIPS)
    mag_df    = mag_compute(m5_eu)

    trading_days = _trading_days(year)
    print(f"  Dias operativos: {len(trading_days)}")

    all_trades = []
    capital    = initial_capital

    for i, d in enumerate(trading_days):
        cycle_row = cycles_df[cycles_df["date"] == d]
        cycle     = cycle_row.iloc[0]["cycle"] if not cycle_row.empty else "Unknown"

        if cycle == "Unknown":
            continue
        if FILTER_KNOCKOUT and cycle == "Knockout":
            continue

        asia     = get_for_date(asia_df, d)
        gap_bias = get_gap_bias(gaps_df, d)

        mag_row = mag_df[mag_df["date"] == d]
        mag2 = float(mag_row.iloc[0]["magnet_2"]) if not mag_row.empty and pd.notna(mag_row.iloc[0]["magnet_2"]) else None

        day_levels = build_day_levels(
            d, asia, None, mag2, daily_hl, weekly_hl,
            min_weight=MIN_SWEEP_WEIGHT, max_weight=MAX_LEVEL_WEIGHT,
        )

        eq_levels  = find_equal_levels(m5_eu, d)
        all_levels = day_levels + eq_levels

        htf_bias = get_htf_bias(
            m1_eu, d,
            sweep_pips=HTF_SWEEP_PIPS,
            h4_lookback_days=H4_LOOKBACK_DAYS,
            h1_lookback_bars=H1_LOOKBACK_BARS,
        )

        win_start, win_end = _window_utc(d)

        m5_day_mask = m5_eu["datetime"].dt.date == d
        m5_day      = m5_eu[m5_day_mask].reset_index(drop=True)

        day_mask = m1_with_sigs["datetime"].dt.date == d
        m1_day   = m1_with_sigs[day_mask].reset_index(drop=True)
        if m1_day.empty:
            continue

        day_trades, capital = _backtest_day_v5(
            d, m1_day, all_levels, gap_bias, cycle, htf_bias, capital,
            m5_day if not m5_day.empty else None, win_start, win_end,
        )
        all_trades.extend(day_trades)

        if (i + 1) % 50 == 0:
            print(f"  [{i+1}/{len(trading_days)}] {d} | capital: ${capital:,.2f} | trades: {len(all_trades)}")

    print(f"\n  Trades totales: {len(all_trades)}")
    print(f"  Capital final:  ${capital:,.2f}")
    print(f"  P&L total:      ${capital - initial_capital:+,.2f}")

    df = pd.DataFrame(all_trades)
    if not df.empty:
        wins  = (df["result"] == "win").sum()
        bes   = (df["result"] == "be").sum()
        total = len(df)
        print(f"  Win rate:       {wins}/{total} = {100*wins/total:.1f}%")
        print(f"  Break-even:     {bes}/{total} = {100*bes/total:.1f}%")
        if "sweep_level" in df.columns:
            for lvl, g in df.groupby("sweep_level"):
                w = (g["result"] == "win").sum()
                t = len(g)
                p = g["pnl_usd"].sum()
                print(f"  {lvl}: {t} trades, WR={100*w/t:.1f}%, PnL={p:+.2f}")
        if "confidence" in df.columns:
            for conf, g in df.groupby("confidence"):
                w = (g["result"] == "win").sum()
                t = len(g)
                p = g["pnl_usd"].sum()
                print(f"  confidence={conf}: {t} trades, WR={100*w/t:.1f}%, PnL={p:+.2f}")
        if "htf_combined" in df.columns:
            for htf_val, g in df.groupby("htf_combined"):
                w = (g["result"] == "win").sum()
                t = len(g)
                print(f"  HTF {htf_val}: {t} trades, WR={100*w/t:.1f}%")

        out_dir = _RESULTS_DIR / "v5"
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"backtest_{year}.csv"
        df.to_csv(path, index=False)
        print(f"  [SAVED] {path}")

    return df


# ---------------------------------------------------------------------------
# Ventana operativa V6 — 09:30-13:00 NY (DST-aware)
# Retorna ((h,m),(h,m)) en UTC para comparacion directa con (dt.hour, dt.minute)
# ---------------------------------------------------------------------------

def _window_v6(trade_date) -> tuple[tuple[int, int], tuple[int, int]]:
    """Ventana 09:30-13:00 NY -> ((start_h, start_m), (end_h, end_m)) en UTC."""
    s  = _dt(trade_date.year, trade_date.month, trade_date.day,  9, 30, tzinfo=_TZ_NY_DYN)
    e  = _dt(trade_date.year, trade_date.month, trade_date.day, 13,  0, tzinfo=_TZ_NY_DYN)
    su = s.astimezone(_tz.utc)
    eu = e.astimezone(_tz.utc)
    return (su.hour, su.minute), (eu.hour, eu.minute)


def _t3_cutoff_v6(trade_date) -> tuple[int, int]:
    """12:30 NY -> (h, m) UTC — cutoff T3 para V6."""
    c  = _dt(trade_date.year, trade_date.month, trade_date.day, 12, 30, tzinfo=_TZ_NY_DYN)
    cu = c.astimezone(_tz.utc)
    return cu.hour, cu.minute


# ---------------------------------------------------------------------------
# Backtest de un dia — Version 6
# V1 (induccion) + HTF permisivo + BE 1.5x + noticias + ventana 09:30-13:00 NY
# ---------------------------------------------------------------------------

def _backtest_day_v6(
    trade_date:   date,
    m1_day:       pd.DataFrame,
    htf_bias:     dict,
    cycle:        str,
    capital:      float,
    win_hm:       tuple,    # ((start_h, start_m), (end_h, end_m)) UTC
    t3_cutoff_hm: tuple,    # (h, m) UTC
) -> tuple[list[dict], float]:
    """
    V6: senal de induccion (logica V1) + HTF como veto permisivo (neutral OK)
        + break-even 1.5x + filtro noticias + ventana DST 09:30-13:00 NY.
    """
    from analysis.induction_detector import find_induction
    from engine.entry_logic import _count_confirmations
    from engine.position_sizer import calculate

    combined  = htf_bias.get("combined", "neutral")
    win_start, win_end = win_hm

    trades       = []
    trades_today = 0
    daily_done   = False

    for bar_idx in range(len(m1_day)):
        if daily_done:
            break

        row    = m1_day.iloc[bar_idx]
        dt_utc = row["datetime"]

        dt_hm = (int(dt_utc.hour), int(dt_utc.minute))
        if not (win_start <= dt_hm < win_end):
            continue
        if bar_idx < EXCELLENCE_BODY_LOOKBACK + 2:
            continue
        if bar_idx == 0:
            continue

        bar_c    = float(row["close"])
        bar_o    = float(row["open"])
        bar_body = abs(bar_c - bar_o)

        prev      = m1_day.iloc[bar_idx - 1]
        prev_body = abs(float(prev["close"]) - float(prev["open"]))

        if bar_body <= prev_body:
            continue

        direction = "long" if bar_c > bar_o else ("short" if bar_c < bar_o else None)
        if direction is None:
            continue

        # HTF permisivo: neutral OK; solo vetar si contradice explicitamente
        if combined not in ("neutral", direction):
            continue

        div_r = {"divergence": bool(row.get("div_signal", False)),
                 "direction":  row.get("div_direction", "")}
        q_s   = {"signal":    bool(row.get("q_signal", False)),
                 "direction": row.get("q_direction", None)}
        mb    = _magnet_bias_from_row(row, bar_c)
        confs = _count_confirmations(div_r, q_s, mb, direction)

        if len(confs) < MIN_CONFIRMATIONS:
            continue

        if _is_news_blackout(dt_utc):
            continue

        # Induccion: pullback al nivel clave en ventana de 25 barras M1
        window    = m1_day.iloc[max(0, bar_idx - 25): bar_idx + 1]
        induction = find_induction(window, direction)
        if induction is None:
            continue

        entry   = bar_c
        sl      = induction["sl_price"]
        sl_pips = abs(entry - sl) / _PIP

        if sl_pips < 1.0:
            continue
        if direction == "long"  and sl >= entry:
            continue
        if direction == "short" and sl <= entry:
            continue

        tp = _tp_price(entry, sl, direction, RISK_REWARD)

        # Excelencia T3 — cutoff 12:30 NY
        avg_b = _avg_body(m1_day, bar_idx, EXCELLENCE_BODY_LOOKBACK)
        is_excellence = (
            cycle not in ("Unknown", "Sierra") and
            len(confs) >= 3 and
            bar_body >= EXCELLENCE_BODY_MULT * avg_b and
            dt_hm < t3_cutoff_hm
        )

        if trades_today == 2:
            if not is_excellence:
                continue
            if not all(t["result"] in ("win", "be") for t in trades):
                continue

        result, exit_p, exit_t, _ = _simulate_trade_be(
            entry, sl, tp, direction, bar_idx, m1_day
        )
        if result == "open":
            result, exit_p = "loss", sl

        risk_usd = capital * RISK_PCT
        pnl = (risk_usd * RISK_REWARD if result == "win"
               else 0.0 if result == "be"
               else -risk_usd)
        capital += pnl

        trades.append({
            "date":            trade_date.isoformat(),
            "signal_time":     str(dt_utc),
            "exit_time":       str(exit_t) if exit_t else "",
            "direction":       direction,
            "cycle":           cycle,
            "entry_price":     round(entry,   5),
            "sl_price":        round(sl,      5),
            "tp_price":        round(tp,      5),
            "exit_price":      round(exit_p,  5),
            "sl_pips":         round(sl_pips, 1),
            "lots":            calculate(sl_pips=sl_pips, capital=capital),
            "risk_usd":        round(risk_usd, 2),
            "result":          result,
            "pnl_usd":         round(pnl,     2),
            "capital_after":   round(capital, 2),
            "trade_num_day":   trades_today + 1,
            "confirmations":   "|".join(confs),
            "induction_price": round(induction["induction_price"], 5),
            "excellence":      is_excellence,
            "h4_bias":         htf_bias.get("h4_bias", "neutral"),
            "h1_bias":         htf_bias.get("h1_bias", "neutral"),
            "htf_combined":    combined,
        })
        trades_today += 1

        if result == "loss" or trades_today >= 3:
            daily_done = True

    return trades, capital


# ---------------------------------------------------------------------------
# Backtest completo del ano — Version 6
# ---------------------------------------------------------------------------

def run_v6(year: int, initial_capital: float = CAPITAL) -> pd.DataFrame:
    """
    V6: induccion V1 + HTF permisivo (neutral OK) + BE 1.5x
        + FILTER_KNOCKOUT + noticias +-60min + ventana 09:30-13:00 NY (DST-aware).
    """
    print(f"\n[BACKTEST V6] Ano {year} -- capital inicial: ${initial_capital:,.2f}")

    from data.fetcher import load
    from analysis.asia_range import compute as ar_compute
    from analysis.cycle_detector import compute as cd_compute
    from analysis.htf_structure import get_htf_bias

    print("  Cargando datos...")
    m1_eu = load(SYMBOL_MAIN, TF_ENTRY,    year)
    m5_eu = load(SYMBOL_MAIN, TF_ANALYSIS, year)
    m5_gu = load(SYMBOL_DIV,  TF_ANALYSIS, year)

    print("  Calculando rango Asia y ciclos...")
    asia_df   = ar_compute(m1_eu)
    cycles_df = cd_compute(m5_eu, asia_df)

    print("  Pre-calculando senales M5...")
    sigs         = _precompute_signals(m5_eu, m5_gu)
    m1_with_sigs = _attach_to_m1(m1_eu, sigs)

    trading_days = _trading_days(year)
    print(f"  Dias operativos: {len(trading_days)}")

    all_trades = []
    capital    = initial_capital

    for i, d in enumerate(trading_days):
        cycle_row = cycles_df[cycles_df["date"] == d]
        cycle     = cycle_row.iloc[0]["cycle"] if not cycle_row.empty else "Unknown"

        if cycle == "Unknown":
            continue
        if FILTER_KNOCKOUT and cycle == "Knockout":
            continue

        htf_bias = get_htf_bias(
            m1_eu, d,
            sweep_pips=HTF_SWEEP_PIPS,
            h4_lookback_days=H4_LOOKBACK_DAYS,
            h1_lookback_bars=H1_LOOKBACK_BARS,
        )

        win_hm       = _window_v6(d)
        t3_cutoff_hm = _t3_cutoff_v6(d)

        day_mask = m1_with_sigs["datetime"].dt.date == d
        m1_day   = m1_with_sigs[day_mask].reset_index(drop=True)
        if m1_day.empty:
            continue

        day_trades, capital = _backtest_day_v6(
            d, m1_day, htf_bias, cycle, capital, win_hm, t3_cutoff_hm
        )
        all_trades.extend(day_trades)

        if (i + 1) % 50 == 0:
            print(f"  [{i+1}/{len(trading_days)}] {d} | capital: ${capital:,.2f} | trades: {len(all_trades)}")

    print(f"\n  Trades totales: {len(all_trades)}")
    print(f"  Capital final:  ${capital:,.2f}")
    print(f"  P&L total:      ${capital - initial_capital:+,.2f}")

    df = pd.DataFrame(all_trades)
    if not df.empty:
        wins  = (df["result"] == "win").sum()
        bes   = (df["result"] == "be").sum()
        total = len(df)
        print(f"  Win rate:       {wins}/{total} = {100*wins/total:.1f}%")
        print(f"  Break-even:     {bes}/{total} = {100*bes/total:.1f}%")
        if "htf_combined" in df.columns:
            for htf_val, g in df.groupby("htf_combined"):
                w = (g["result"] == "win").sum()
                t = len(g)
                print(f"  HTF {htf_val}: {t} trades, WR={100*w/t:.1f}%")

        out_dir = _RESULTS_DIR / "v6"
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"backtest_{year}.csv"
        df.to_csv(path, index=False)
        print(f"  [SAVED] {path}")

    return df


# ---------------------------------------------------------------------------
# Ventana operativa V7 — 08:00-10:00 NY (DST-aware)
# ---------------------------------------------------------------------------

def _window_v7(trade_date) -> tuple[tuple[int, int], tuple[int, int]]:
    """Ventana 08:00-10:00 NY -> ((start_h, start_m), (end_h, end_m)) en UTC."""
    s  = _dt(trade_date.year, trade_date.month, trade_date.day,  8,  0, tzinfo=_TZ_NY_DYN)
    e  = _dt(trade_date.year, trade_date.month, trade_date.day, 10,  0, tzinfo=_TZ_NY_DYN)
    su = s.astimezone(_tz.utc)
    eu = e.astimezone(_tz.utc)
    return (su.hour, su.minute), (eu.hour, eu.minute)


# ---------------------------------------------------------------------------
# Backtest de un dia — Version 7
# quarters AND magnets obligatorios + 08:00-10:00 NY + T2 siempre
# + T3 por resultado + H4 estricto + BE 1.5x + sin filtro noticias
# ---------------------------------------------------------------------------

def _backtest_day_v7(
    trade_date: date,
    m1_day:     pd.DataFrame,
    htf_bias:   dict,
    cycle:      str,
    capital:    float,
    win_hm:     tuple,  # ((start_h, start_m), (end_h, end_m)) UTC
) -> tuple[list[dict], float]:
    """
    V7: quarters AND magnets obligatorios + ventana 08:00-10:00 NY
        + T2 siempre independiente de resultado T1
        + T3 requiere que T2 haya ganado; si T1 perdio, ademas divergencia presente
        + HTF H4 estricto (bloquea si H4 contradice, neutral OK)
        + BE 1.5x + sin filtro de noticias.

    T3 gating:
        T2 win + T1 win/BE  -> T3 con señal estandar (quarters+magnets)
        T2 win + T1 loss    -> T3 solo si divergencia presente en la señal
        T2 loss/BE          -> dia terminado, sin T3
    """
    from analysis.induction_detector import find_induction
    from engine.entry_logic import _count_confirmations
    from engine.position_sizer import calculate

    h4_bias              = htf_bias.get("h4_bias", "neutral")
    win_start, win_end   = win_hm

    trades       = []
    trades_today = 0
    daily_done   = False
    t1_result    = None

    for bar_idx in range(len(m1_day)):
        if daily_done:
            break

        row    = m1_day.iloc[bar_idx]
        dt_utc = row["datetime"]

        dt_hm = (int(dt_utc.hour), int(dt_utc.minute))
        if not (win_start <= dt_hm < win_end):
            continue
        if bar_idx < EXCELLENCE_BODY_LOOKBACK + 2:
            continue
        if bar_idx == 0:
            continue

        bar_c    = float(row["close"])
        bar_o    = float(row["open"])
        bar_body = abs(bar_c - bar_o)

        prev      = m1_day.iloc[bar_idx - 1]
        prev_body = abs(float(prev["close"]) - float(prev["open"]))

        if bar_body <= prev_body:
            continue

        direction = "long" if bar_c > bar_o else ("short" if bar_c < bar_o else None)
        if direction is None:
            continue

        # HTF H4 estricto: bloquear si H4 contradice la direccion
        if h4_bias not in ("neutral", direction):
            continue

        div_r = {"divergence": bool(row.get("div_signal", False)),
                 "direction":  row.get("div_direction", "")}
        q_s   = {"signal":    bool(row.get("q_signal", False)),
                 "direction": row.get("q_direction", None)}
        mb    = _magnet_bias_from_row(row, bar_c)
        confs = _count_confirmations(div_r, q_s, mb, direction)

        # V7: requerir quarters AND magnets obligatoriamente
        if "quarters" not in confs or "magnets" not in confs:
            continue

        # Induccion: pullback al nivel clave en ventana de 25 barras M1
        window    = m1_day.iloc[max(0, bar_idx - 25): bar_idx + 1]
        induction = find_induction(window, direction)
        if induction is None:
            continue

        entry   = bar_c
        sl      = induction["sl_price"]
        sl_pips = abs(entry - sl) / _PIP

        if sl_pips < 1.0:
            continue
        if direction == "long"  and sl >= entry:
            continue
        if direction == "short" and sl <= entry:
            continue

        tp = _tp_price(entry, sl, direction, RISK_REWARD)

        # T3 gating
        if trades_today == 2:
            t2_result = trades[1]["result"]
            if t2_result != "win":
                continue
            if t1_result == "loss":
                has_div = (
                    bool(row.get("div_signal", False)) and
                    row.get("div_direction", "") == direction
                )
                if not has_div:
                    continue

        result, exit_p, exit_t, _ = _simulate_trade_be(
            entry, sl, tp, direction, bar_idx, m1_day
        )
        if result == "open":
            result, exit_p = "loss", sl

        risk_usd = capital * RISK_PCT
        pnl = (risk_usd * RISK_REWARD if result == "win"
               else 0.0 if result == "be"
               else -risk_usd)
        capital += pnl

        trades.append({
            "date":            trade_date.isoformat(),
            "signal_time":     str(dt_utc),
            "exit_time":       str(exit_t) if exit_t else "",
            "direction":       direction,
            "cycle":           cycle,
            "entry_price":     round(entry,   5),
            "sl_price":        round(sl,      5),
            "tp_price":        round(tp,      5),
            "exit_price":      round(exit_p,  5),
            "sl_pips":         round(sl_pips, 1),
            "lots":            calculate(sl_pips=sl_pips, capital=capital),
            "risk_usd":        round(risk_usd, 2),
            "result":          result,
            "pnl_usd":         round(pnl,     2),
            "capital_after":   round(capital, 2),
            "trade_num_day":   trades_today + 1,
            "confirmations":   "|".join(confs),
            "induction_price": round(induction["induction_price"], 5),
            "excellence":      False,
            "h4_bias":         htf_bias.get("h4_bias",  "neutral"),
            "h1_bias":         htf_bias.get("h1_bias",  "neutral"),
            "htf_combined":    htf_bias.get("combined", "neutral"),
        })
        trades_today += 1

        if trades_today == 1:
            t1_result = result

        # T2 loss cierra el dia; T3 siempre cierra el dia
        if trades_today == 2 and result == "loss":
            daily_done = True
        elif trades_today >= 3:
            daily_done = True

    return trades, capital


# ---------------------------------------------------------------------------
# Backtest completo del ano — Version 7
# ---------------------------------------------------------------------------

def run_v7(year: int, initial_capital: float = CAPITAL) -> pd.DataFrame:
    """
    V7: quarters AND magnets obligatorios + ventana 08:00-10:00 NY (DST-aware)
        + T2 siempre (sin gate de T1 win) + T3 por resultado + H4 estricto
        + BE 1.5x + FILTER_KNOCKOUT + sin filtro de noticias.
    """
    print(f"\n[BACKTEST V7] Ano {year} -- capital inicial: ${initial_capital:,.2f}")

    from data.fetcher import load
    from analysis.asia_range import compute as ar_compute
    from analysis.cycle_detector import compute as cd_compute
    from analysis.htf_structure import get_htf_bias

    print("  Cargando datos...")
    m1_eu = load(SYMBOL_MAIN, TF_ENTRY,    year)
    m5_eu = load(SYMBOL_MAIN, TF_ANALYSIS, year)
    m5_gu = load(SYMBOL_DIV,  TF_ANALYSIS, year)

    print("  Calculando rango Asia y ciclos...")
    asia_df   = ar_compute(m1_eu)
    cycles_df = cd_compute(m5_eu, asia_df)

    print("  Pre-calculando senales M5...")
    sigs         = _precompute_signals(m5_eu, m5_gu)
    m1_with_sigs = _attach_to_m1(m1_eu, sigs)

    trading_days = _trading_days(year)
    print(f"  Dias operativos: {len(trading_days)}")

    all_trades = []
    capital    = initial_capital

    for i, d in enumerate(trading_days):
        cycle_row = cycles_df[cycles_df["date"] == d]
        cycle     = cycle_row.iloc[0]["cycle"] if not cycle_row.empty else "Unknown"

        if cycle == "Unknown":
            continue
        if FILTER_KNOCKOUT and cycle == "Knockout":
            continue

        htf_bias = get_htf_bias(
            m1_eu, d,
            sweep_pips=HTF_SWEEP_PIPS,
            h4_lookback_days=H4_LOOKBACK_DAYS,
            h1_lookback_bars=H1_LOOKBACK_BARS,
        )

        win_hm = _window_v7(d)

        day_mask = m1_with_sigs["datetime"].dt.date == d
        m1_day   = m1_with_sigs[day_mask].reset_index(drop=True)
        if m1_day.empty:
            continue

        day_trades, capital = _backtest_day_v7(
            d, m1_day, htf_bias, cycle, capital, win_hm
        )
        all_trades.extend(day_trades)

        if (i + 1) % 50 == 0:
            print(f"  [{i+1}/{len(trading_days)}] {d} | capital: ${capital:,.2f} | trades: {len(all_trades)}")

    print(f"\n  Trades totales: {len(all_trades)}")
    print(f"  Capital final:  ${capital:,.2f}")
    print(f"  P&L total:      ${capital - initial_capital:+,.2f}")

    df = pd.DataFrame(all_trades)
    if not df.empty:
        wins  = (df["result"] == "win").sum()
        bes   = (df["result"] == "be").sum()
        total = len(df)
        print(f"  Win rate:       {wins}/{total} = {100*wins/total:.1f}%")
        print(f"  Break-even:     {bes}/{total} = {100*bes/total:.1f}%")
        if "h4_bias" in df.columns:
            for h4_val, g in df.groupby("h4_bias"):
                w = (g["result"] == "win").sum()
                t = len(g)
                print(f"  H4 {h4_val}: {t} trades, WR={100*w/t:.1f}%")
        for tn, g in df.groupby("trade_num_day"):
            w = (g["result"] == "win").sum()
            t = len(g)
            p = g["pnl_usd"].sum()
            print(f"  T{tn}: {t} trades, WR={100*w/t:.1f}%, PnL={p:+.2f}")

        out_dir = _RESULTS_DIR / "v7"
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"backtest_{year}.csv"
        df.to_csv(path, index=False)
        print(f"  [SAVED] {path}")

    return df


# ---------------------------------------------------------------------------
# Backtest de un dia — Version 8
# Magneto diario: precio_08:00 vs precio_07:30 define direccion del dia
# Ventana: 08:00-10:00 NY | Riesgo: 1% | BE 1.5x | quarters+magnets obligatorios
# ---------------------------------------------------------------------------

def _backtest_day_v8(
    trade_date:       date,
    m1_day:           pd.DataFrame,
    htf_bias:         dict,
    cycle:            str,
    capital:          float,
    win_hm:           tuple,
    magnet_direction: str,   # "bullish" | "bearish" — ya pre-computado al 08:00 NY
) -> tuple[list[dict], float]:
    """
    V8: igual que V7 pero el magneto es una señal diaria (08:00 vs 07:30)
    en vez de comparacion precio-actual vs nivel por barra.

    magnet_direction pre-computed:
        "bullish" → precio_08:00 < precio_07:30 → solo LONG tiene confirmacion magneto
        "bearish" → precio_08:00 > precio_07:30 → solo SHORT tiene confirmacion magneto
        "neutral" → no operar (caller debe filtrar antes de llamar aqui)
    """
    from analysis.induction_detector import find_induction
    from engine.entry_logic import _count_confirmations
    from engine.position_sizer import calculate

    h4_bias            = htf_bias.get("h4_bias", "neutral")
    win_start, win_end = win_hm

    # mb construido una sola vez con la direccion diaria del magneto
    mb = {"agreement": True, "bias": magnet_direction}

    trades       = []
    trades_today = 0
    daily_done   = False
    t1_result    = None

    for bar_idx in range(len(m1_day)):
        if daily_done:
            break

        row    = m1_day.iloc[bar_idx]
        dt_utc = row["datetime"]

        dt_hm = (int(dt_utc.hour), int(dt_utc.minute))
        if not (win_start <= dt_hm < win_end):
            continue
        if bar_idx < EXCELLENCE_BODY_LOOKBACK + 2:
            continue
        if bar_idx == 0:
            continue

        bar_c    = float(row["close"])
        bar_o    = float(row["open"])
        bar_body = abs(bar_c - bar_o)

        prev      = m1_day.iloc[bar_idx - 1]
        prev_body = abs(float(prev["close"]) - float(prev["open"]))

        if bar_body <= prev_body:
            continue

        direction = "long" if bar_c > bar_o else ("short" if bar_c < bar_o else None)
        if direction is None:
            continue

        # H4 estricto: bloquear si H4 contradice la direccion
        if h4_bias not in ("neutral", direction):
            continue

        div_r = {"divergence": bool(row.get("div_signal", False)),
                 "direction":  row.get("div_direction", "")}
        q_s   = {"signal":    bool(row.get("q_signal", False)),
                 "direction": row.get("q_direction", None)}
        confs = _count_confirmations(div_r, q_s, mb, direction)

        # quarters AND magnets obligatorios
        if "quarters" not in confs or "magnets" not in confs:
            continue

        # Induccion en ventana M1 de 25 barras
        window    = m1_day.iloc[max(0, bar_idx - 25): bar_idx + 1]
        induction = find_induction(window, direction)
        if induction is None:
            continue

        entry   = bar_c
        sl      = induction["sl_price"]
        sl_pips = abs(entry - sl) / _PIP

        if sl_pips < 1.0:
            continue
        if direction == "long"  and sl >= entry:
            continue
        if direction == "short" and sl <= entry:
            continue

        tp = _tp_price(entry, sl, direction, RISK_REWARD)

        # T3 gating (mismo que V7)
        if trades_today == 2:
            t2_result = trades[1]["result"]
            if t2_result != "win":
                continue
            if t1_result == "loss":
                has_div = (
                    bool(row.get("div_signal", False)) and
                    row.get("div_direction", "") == direction
                )
                if not has_div:
                    continue

        result, exit_p, exit_t, _ = _simulate_trade_be(
            entry, sl, tp, direction, bar_idx, m1_day
        )
        if result == "open":
            result, exit_p = "loss", sl

        risk_usd = capital * RISK_PCT
        pnl = (risk_usd * RISK_REWARD if result == "win"
               else 0.0 if result == "be"
               else -risk_usd)
        capital += pnl

        trades.append({
            "date":            trade_date.isoformat(),
            "signal_time":     str(dt_utc),
            "exit_time":       str(exit_t) if exit_t else "",
            "direction":       direction,
            "cycle":           cycle,
            "entry_price":     round(entry,   5),
            "sl_price":        round(sl,      5),
            "tp_price":        round(tp,      5),
            "exit_price":      round(exit_p,  5),
            "sl_pips":         round(sl_pips, 1),
            "lots":            calculate(sl_pips=sl_pips, capital=capital),
            "risk_usd":        round(risk_usd, 2),
            "result":          result,
            "pnl_usd":         round(pnl,     2),
            "capital_after":   round(capital, 2),
            "trade_num_day":   trades_today + 1,
            "confirmations":   "|".join(confs),
            "induction_price": round(induction["induction_price"], 5),
            "excellence":      False,
            "h4_bias":         htf_bias.get("h4_bias",  "neutral"),
            "h1_bias":         htf_bias.get("h1_bias",  "neutral"),
            "htf_combined":    htf_bias.get("combined", "neutral"),
            "magnet_direction": magnet_direction,
        })
        trades_today += 1

        if trades_today == 1:
            t1_result = result

        if trades_today == 2 and result == "loss":
            daily_done = True
        elif trades_today >= 3:
            daily_done = True

    return trades, capital


# ---------------------------------------------------------------------------
# Backtest completo del ano — Version 8
# ---------------------------------------------------------------------------

def run_v8(year: int, initial_capital: float = CAPITAL) -> pd.DataFrame:
    """
    V8: magneto diario (08:00 vs 07:30 NY) define direccion + ventana 08:00-10:00 NY
        + quarters AND magnets obligatorios + H4 estricto + BE 1.5x
        + T2 siempre + T3 por resultado + RISK_PCT 1%.
    """
    print(f"\n[BACKTEST V8] Ano {year} -- capital inicial: ${initial_capital:,.2f}")

    from data.fetcher import load
    from analysis.asia_range import compute as ar_compute
    from analysis.cycle_detector import compute as cd_compute
    from analysis.htf_structure import get_htf_bias
    from analysis.opening_magnets import compute_direction as mag_dir_compute

    print("  Cargando datos...")
    m1_eu = load(SYMBOL_MAIN, TF_ENTRY,    year)
    m5_eu = load(SYMBOL_MAIN, TF_ANALYSIS, year)
    m5_gu = load(SYMBOL_DIV,  TF_ANALYSIS, year)

    print("  Calculando rango Asia y ciclos...")
    asia_df   = ar_compute(m1_eu)
    cycles_df = cd_compute(m5_eu, asia_df)

    print("  Pre-calculando senales M5...")
    sigs         = _precompute_signals(m5_eu, m5_gu)
    m1_with_sigs = _attach_to_m1(m1_eu, sigs)

    print("  Pre-calculando direccion magneto 07:30 vs 08:00 NY...")
    mag_dir_df = mag_dir_compute(m1_eu)   # usa M1 para precision en 08:00

    trading_days = _trading_days(year)
    print(f"  Dias operativos: {len(trading_days)}")

    all_trades     = []
    capital        = initial_capital
    neutral_magnet = 0

    for i, d in enumerate(trading_days):
        cycle_row = cycles_df[cycles_df["date"] == d]
        cycle     = cycle_row.iloc[0]["cycle"] if not cycle_row.empty else "Unknown"

        if cycle == "Unknown":
            continue
        if FILTER_KNOCKOUT and cycle == "Knockout":
            continue

        # Direccion diaria del magneto (pre-computada)
        mag_row          = mag_dir_df[mag_dir_df["date"] == d]
        magnet_direction = mag_row.iloc[0]["magnet_direction"] if not mag_row.empty else "neutral"
        if magnet_direction == "neutral":
            neutral_magnet += 1
            continue

        htf_bias = get_htf_bias(
            m1_eu, d,
            sweep_pips=HTF_SWEEP_PIPS,
            h4_lookback_days=H4_LOOKBACK_DAYS,
            h1_lookback_bars=H1_LOOKBACK_BARS,
        )

        win_hm = _window_v7(d)   # reutiliza la misma funcion: 08:00-10:00 NY

        day_mask = m1_with_sigs["datetime"].dt.date == d
        m1_day   = m1_with_sigs[day_mask].reset_index(drop=True)
        if m1_day.empty:
            continue

        day_trades, capital = _backtest_day_v8(
            d, m1_day, htf_bias, cycle, capital, win_hm, magnet_direction
        )
        all_trades.extend(day_trades)

        if (i + 1) % 50 == 0:
            print(f"  [{i+1}/{len(trading_days)}] {d} | capital: ${capital:,.2f} | trades: {len(all_trades)}")

    print(f"\n  Dias sin magneto (neutral 08:00=07:30): {neutral_magnet}")
    print(f"  Trades totales: {len(all_trades)}")
    print(f"  Capital final:  ${capital:,.2f}")
    print(f"  P&L total:      ${capital - initial_capital:+,.2f}")

    df = pd.DataFrame(all_trades)
    if not df.empty:
        wins  = (df["result"] == "win").sum()
        bes   = (df["result"] == "be").sum()
        total = len(df)
        print(f"  Win rate:       {wins}/{total} = {100*wins/total:.1f}%")
        print(f"  Break-even:     {bes}/{total} = {100*bes/total:.1f}%")
        if "h4_bias" in df.columns:
            for h4_val, g in df.groupby("h4_bias"):
                w = (g["result"] == "win").sum()
                t = len(g)
                print(f"  H4 {h4_val}: {t} trades, WR={100*w/t:.1f}%")
        for tn, g in df.groupby("trade_num_day"):
            w = (g["result"] == "win").sum()
            t = len(g)
            p = g["pnl_usd"].sum()
            print(f"  T{tn}: {t} trades, WR={100*w/t:.1f}%, PnL={p:+.2f}")
        for md, g in df.groupby("magnet_direction"):
            w = (g["result"] == "win").sum()
            t = len(g)
            print(f"  Magneto {md}: {t} trades, WR={100*w/t:.1f}%")

        out_dir = _RESULTS_DIR / "v8"
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"backtest_{year}.csv"
        df.to_csv(path, index=False)
        print(f"  [SAVED] {path}")

    return df


def save_results(df: pd.DataFrame, year: int) -> Path:
    _RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    path = _RESULTS_DIR / f"backtest_{year}.csv"
    df.to_csv(path, index=False)
    print(f"  [SAVED] {path}")
    return path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _parse_args():
    p = argparse.ArgumentParser(description="Backtester walk-forward V2/V3")
    p.add_argument("--year",    type=int, action="append", dest="years",
                   help="Ano (repetir para multiples: --year 2024 --year 2025)")
    p.add_argument("--capital", type=float, default=CAPITAL,
                   help=f"Capital inicial USD (default: {CAPITAL})")
    p.add_argument("--version", type=int, default=8, choices=[2, 3, 4, 5, 6, 7, 8],
                   help="Version: 2=sweep, 3=HTF+induccion+BE, 4=niveles top+HTF veto+BE, 5=sweep+EQH/EQL+HTF+BE, 6=induccion+HTF permisivo+BE+noticias+NY, 7=quarters+magnets+08-10NY+T2siempre+H4estricto, 8=V7+magneto-diario-08vs07:30+1pct-riesgo")
    return p.parse_args()


if __name__ == "__main__":
    args  = _parse_args()
    years = args.years or BACKTEST_YEARS

    if args.version == 8:
        runner  = run_v8
        sub_dir = "v8"
    elif args.version == 7:
        runner  = run_v7
        sub_dir = "v7"
    elif args.version == 6:
        runner  = run_v6
        sub_dir = "v6"
    elif args.version == 5:
        runner  = run_v5
        sub_dir = "v5"
    elif args.version == 4:
        runner  = run_v4
        sub_dir = "v4"
    elif args.version == 3:
        runner  = run_v3
        sub_dir = "v3"
    else:
        runner  = run
        sub_dir = "v2"
    label = f"V{args.version}"

    for yr in years:
        df = runner(yr, initial_capital=args.capital)
        if not df.empty and args.version not in (5, 6, 7, 8):   # V5-V8 guardan internamente
            out_dir = _RESULTS_DIR / sub_dir
            out_dir.mkdir(parents=True, exist_ok=True)
            path = out_dir / f"backtest_{yr}.csv"
            df.to_csv(path, index=False)
            print(f"  [SAVED] {path}")

    print(f"\n[DONE] Backtesting {label} completado.")
