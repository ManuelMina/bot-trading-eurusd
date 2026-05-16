"""
Analisis de estructura en timeframes altos (H4 y H1) para filtro direccional V3.

Logica top-down:
    H4 — identifica la macro-estructura: barrido de swing high/low o tendencia HH/HL / LH/LL
    H1 — confirma con estructura intermedia mas cercana al precio actual
    Combined — H4 + H1 deben coincidir para generar sesgo accionable

Sesgo de salida:
    "long"    H4/H1 muestran barrido de swing low o estructura alcista (HH+HL)
    "short"   H4/H1 muestran barrido de swing high o estructura bajista (LH+LL)
    "neutral" Sin senal clara o conflicto entre H4 y H1

Uso:
    from analysis.htf_structure import get_htf_bias
    bias = get_htf_bias(m1_df, trade_date)
    direction = bias['combined']  # "long" | "short" | "neutral"
"""

from datetime import date, timedelta

import pandas as pd

_PIP = 0.0001


# ---------------------------------------------------------------------------
# Resampleo OHLC
# ---------------------------------------------------------------------------

def resample_ohlc(m1_df: pd.DataFrame, freq: str) -> pd.DataFrame:
    """Resamplea un DataFrame M1 a la frecuencia indicada ('1h', '4h', etc.)."""
    df = m1_df.set_index("datetime").sort_index()
    result = (
        df[["open", "high", "low", "close"]]
        .resample(freq, label="left", closed="left")
        .agg(
            open=("open",  "first"),
            high=("high",  "max"),
            low =("low",   "min"),
            close=("close","last"),
        )
        .dropna(subset=["close"])
    )
    return result.reset_index()


# ---------------------------------------------------------------------------
# Deteccion de pivots (sin lookahead)
# ---------------------------------------------------------------------------

def _find_pivots(bars: pd.DataFrame, n: int = 2) -> tuple[list[tuple], list[tuple]]:
    """
    Detecta pivot highs y lows con N barras de confirmacion a cada lado.
    Excluye las ultimas N barras (no tienen confirmacion futura en este contexto).

    Retorna:
        piv_highs: list[(bar_index, price)]
        piv_lows:  list[(bar_index, price)]
    """
    highs = bars["high"].values
    lows  = bars["low"].values
    piv_h, piv_l = [], []

    for i in range(n, len(bars) - n):
        window_h = highs[i - n : i + n + 1]
        window_l = lows[i - n : i + n + 1]
        if highs[i] == max(window_h):
            piv_h.append((i, float(highs[i])))
        if lows[i] == min(window_l):
            piv_l.append((i, float(lows[i])))

    return piv_h, piv_l


# ---------------------------------------------------------------------------
# Sesgo a partir de barras OHLC
# ---------------------------------------------------------------------------

def _bias_from_bars(
    bars: pd.DataFrame,
    sweep_pips: float = 2.0,
    n: int = 2,
) -> tuple[str, float | None]:
    """
    Determina el sesgo de una serie de barras OHLC.

    Prioridad:
        1. Barrido confirmado de pivot (precio cruzó el pivot y cerró del lado contrario)
        2. Estructura HH+HL (alcista) o LH+LL (bajista) de al menos 2 swings
        3. neutral si no hay senal clara

    Retorna: (sesgo, nivel_referencia)
    """
    if len(bars) < n * 2 + 4:
        return "neutral", None

    # Pivots en barras -n al final para evitar lookahead
    piv_h, piv_l = _find_pivots(bars.iloc[:-1], n=n)

    last   = bars.iloc[-1]
    last_h = float(last["high"])
    last_l = float(last["low"])
    last_c = float(last["close"])
    thresh = sweep_pips * _PIP

    # 1. Barrido de pivot high → SHORT
    if piv_h:
        ph_price = piv_h[-1][1]
        if last_h > ph_price + thresh and last_c < ph_price:
            return "short", ph_price

    # 2. Barrido de pivot low → LONG
    if piv_l:
        pl_price = piv_l[-1][1]
        if last_l < pl_price - thresh and last_c > pl_price:
            return "long", pl_price

    # 3. Estructura HH+HL o LH+LL
    if len(piv_h) >= 2 and len(piv_l) >= 2:
        sh1, sh2 = piv_h[-2][1], piv_h[-1][1]
        sl1, sl2 = piv_l[-2][1], piv_l[-1][1]
        if sh2 > sh1 and sl2 > sl1:
            return "long", sl2    # HH + HL → alcista
        if sh2 < sh1 and sl2 < sl1:
            return "short", sh2   # LH + LL → bajista

    return "neutral", None


# ---------------------------------------------------------------------------
# API principal
# ---------------------------------------------------------------------------

def get_htf_bias(
    m1_df: pd.DataFrame,
    trade_date: date,
    sweep_pips: float = 2.0,
    h4_lookback_days: int = 5,
    h1_lookback_bars: int = 24,
) -> dict:
    """
    Retorna el sesgo H4 + H1 para un dia de trading.

    Analiza SOLO barras anteriores a las 12:00 UTC (= 07:00 Colombia),
    inicio de la ventana operativa. Sin lookahead.

    Parameters
    ----------
    m1_df            : DataFrame M1 con columna 'datetime' (UTC, naive o aware).
    trade_date       : fecha del dia a analizar.
    sweep_pips       : pips minimos para confirmar barrido de pivot en H4.
    h4_lookback_days : dias de historia hacia atras para construir H4.
    h1_lookback_bars : barras H1 a usar (24 = 24 horas).

    Returns
    -------
    dict con keys:
        h4_bias  : "long" | "short" | "neutral"
        h1_bias  : "long" | "short" | "neutral"
        combined : "long" | "short" | "neutral"
        h4_level : float | None
        h1_level : float | None
    """
    neutral = dict(h4_bias="neutral", h1_bias="neutral", combined="neutral",
                   h4_level=None, h1_level=None)

    cutoff = pd.Timestamp(f"{trade_date} 12:00:00", tz="UTC")
    start  = pd.Timestamp(f"{trade_date - timedelta(days=h4_lookback_days)} 00:00:00", tz="UTC")

    prior = m1_df[
        (m1_df["datetime"] >= start) & (m1_df["datetime"] < cutoff)
    ].copy()

    if len(prior) < 240:   # menos de 4 horas de M1 → no hay suficiente contexto
        return neutral

    # H4: ultimas 10 barras completas
    h4_all = resample_ohlc(prior, "4h")
    if len(h4_all) < 5:
        return neutral
    h4 = h4_all.tail(10)

    # H1: ultimas h1_lookback_bars barras
    h1_all = resample_ohlc(prior, "1h")
    if len(h1_all) < 6:
        return neutral
    h1 = h1_all.tail(h1_lookback_bars)

    h4_bias, h4_level = _bias_from_bars(h4, sweep_pips=sweep_pips,       n=1)
    h1_bias, h1_level = _bias_from_bars(h1, sweep_pips=sweep_pips * 0.5, n=2)

    # Combinar: H4 es el timeframe primario
    if h4_bias == "neutral":
        combined = h1_bias
    elif h1_bias in ("neutral", h4_bias):
        combined = h4_bias
    else:
        combined = "neutral"   # H4 y H1 en conflicto → no operar

    return dict(
        h4_bias=h4_bias, h1_bias=h1_bias, combined=combined,
        h4_level=h4_level, h1_level=h1_level,
    )
