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
    TZ_COLOMBIA,
)

_PIP = 0.0001
_RESULTS_DIR = Path(__file__).parent.parent / "reporting" / "results"
_WINDOW_UTC_START = 12   # 07:00 Colombia
_WINDOW_UTC_END   = 15   # 10:00 Colombia


# ---------------------------------------------------------------------------
# Calendario
# ---------------------------------------------------------------------------

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
    def _side(lvl):
        if lvl is None or (isinstance(lvl, float) and np.isnan(lvl)):
            return None
        return "bullish" if price < lvl else "bearish"

    b1 = _side(row.get("magnet_1"))
    b2 = _side(row.get("magnet_2"))
    avail = [b for b in (b1, b2) if b is not None]
    if not avail:
        return {"magnet_1": None, "magnet_2": None, "agreement": False, "bias": "neutral"}
    if len(avail) == 1:
        return {"magnet_1": b1, "magnet_2": b2, "agreement": True, "bias": avail[0]}
    agreement = b1 == b2
    return {"magnet_1": b1, "magnet_2": b2, "agreement": agreement,
            "bias": b1 if agreement else "conflict"}


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
    mag_df    = mag_compute(m5_eu)   # date, magnet_1, magnet_2

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

        # Magnetos del dia
        mag_row = mag_df[mag_df["date"] == d]
        mag1 = float(mag_row.iloc[0]["magnet_1"]) if not mag_row.empty and pd.notna(mag_row.iloc[0]["magnet_1"]) else None
        mag2 = float(mag_row.iloc[0]["magnet_2"]) if not mag_row.empty and pd.notna(mag_row.iloc[0]["magnet_2"]) else None

        # Gap semanal como 4a confirmacion
        gap_bias = get_gap_bias(gaps_df, d)

        # Catalogo de niveles del dia
        day_levels = build_day_levels(
            d, asia, mag1, mag2, daily_hl, weekly_hl,
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
    p.add_argument("--version", type=int, default=2, choices=[2, 3],
                   help="Version de la estrategia: 2 (sweep) o 3 (HTF+induccion+BE)")
    return p.parse_args()


if __name__ == "__main__":
    args  = _parse_args()
    years = args.years or BACKTEST_YEARS

    runner = run_v3 if args.version == 3 else run
    label  = f"V{args.version}"

    for yr in years:
        df = runner(yr, initial_capital=args.capital)
        if not df.empty:
            save_results(df, yr)

    print(f"\n[DONE] Backtesting {label} completado.")
