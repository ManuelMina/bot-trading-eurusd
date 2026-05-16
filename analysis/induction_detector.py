"""
Detecta patrones de induccion en series de velas M1/M5.

Definicion de induccion (segun la estrategia):
    1. Precio viaja en direccion X
    2. Precio retrocede en contra hacia un nivel clave (swing high/low)
    3. Precio llega cerca o rompe ligeramente ese nivel (el "barrido")
    4. Precio regresa a la direccion X original
    5. El punto tocado = nivel de induccion (SL va justo afuera de ese punto)

Parametros configurables:
    lookback      - cuantas velas hacia atras buscar el swing previo
    min_retrace   - retroceso minimo en pips para que cuente como induccion valida
    max_overshoot - cuanto puede "pasar" del swing antes de invalidar (en pips)

Uso:
    from analysis.induction_detector import find_induction

    induction = find_induction(bars, direction="long")
    if induction:
        sl_price = induction["sl_price"]
        entry_zone = induction["return_price"]
"""

import pandas as pd

_PIP = 0.0001

# Cuantas velas M1 hacia atras buscar el swing previo
_LOOKBACK_BARS = 20

# Retroceso minimo para validar la induccion (pips): el precio debe retroceder
# al menos este valor desde el punto de referencia antes de volver
_MIN_RETRACE_PIPS = 2.0

# Maximo que el precio puede pasar del swing antes de invalidarlo (pips)
# Si lo pasa por mas de esto, ya no es "barrido limpio"
_MAX_OVERSHOOT_PIPS = 5.0

# La vela de regreso debe cerrar al menos este porcentaje del retroceso
_MIN_RETURN_PCT = 0.5


def find_induction(
    bars: pd.DataFrame,
    direction: str,
    lookback: int = _LOOKBACK_BARS,
    min_retrace_pips: float = _MIN_RETRACE_PIPS,
    max_overshoot_pips: float = _MAX_OVERSHOOT_PIPS,
) -> dict | None:
    """
    Busca el patron de induccion mas reciente en la serie de velas dada.

    Parameters
    ----------
    bars      : DataFrame con columnas [datetime, open, high, low, close].
                Debe estar ordenado cronologicamente (mas antiguo primero).
                Se analiza el extremo de la serie (ultimas 'lookback' velas).
    direction : "long"  = buscamos induccion bajista (precio bajo, regreso arriba)
                "short" = buscamos induccion alcista (precio subio, regreso abajo)
    lookback  : cuantas velas usar para la ventana de busqueda

    Returns
    -------
    dict con keys:
        induction_time  - timestamp de la vela que toco el nivel de induccion
        induction_price - precio extremo tocado (low para long, high para short)
        sl_price        - nivel de SL sugerido (extremo + buffer de config.SL_BUFFER_PIPS)
        return_candle   - timestamp de la primera vela de regreso
        return_price    - precio de cierre de esa vela (zona de entrada aproximada)
        retrace_pips    - tamano del retroceso en pips
    None si no se encuentra patron valido.
    """
    from config import SL_BUFFER_PIPS

    if bars is None or len(bars) < lookback + 2:
        return None

    window = bars.iloc[-lookback:].reset_index(drop=True)

    if direction == "long":
        return _find_long_induction(window, min_retrace_pips, max_overshoot_pips, SL_BUFFER_PIPS)
    elif direction == "short":
        return _find_short_induction(window, min_retrace_pips, max_overshoot_pips, SL_BUFFER_PIPS)
    return None


def _find_long_induction(
    window: pd.DataFrame,
    min_retrace_pips: float,
    max_overshoot_pips: float,
    sl_buffer_pips: int,
) -> dict | None:
    """
    Induccion para entrada LONG:
      - Precio cayo (retroceso bajista hacia swing low previo)
      - Barrido del swing low (toco o paso ligeramente)
      - Precio regresa alcista
    """
    # Buscar el swing low en la primera mitad de la ventana
    half = len(window) // 2
    swing_low_idx = window["low"].iloc[:half].idxmin()
    swing_low     = window["low"].iloc[swing_low_idx]

    # Verificar que la parte final de la ventana baja hasta ese nivel
    retrace_bars = window.iloc[swing_low_idx:]
    if retrace_bars.empty:
        return None

    retrace_low = retrace_bars["low"].min()
    retrace_low_idx = retrace_bars["low"].idxmin()

    retrace_pips = (swing_low - retrace_low) / _PIP
    if retrace_pips < min_retrace_pips:
        return None  # retroceso insuficiente

    overshoot_pips = (swing_low - retrace_low) / _PIP
    if overshoot_pips > max_overshoot_pips:
        return None  # paso demasiado: no es barrido limpio

    # Buscar la primera vela de regreso (cierra por encima del swing_low)
    return_bars = window.iloc[retrace_low_idx + 1:]
    if return_bars.empty:
        return None

    return_bar = return_bars[return_bars["close"] > swing_low]
    if return_bar.empty:
        return None

    return_bar = return_bar.iloc[0]
    induction_bar = window.iloc[retrace_low_idx]

    return {
        "direction":       "long",
        "induction_time":  induction_bar["datetime"],
        "induction_price": retrace_low,
        "sl_price":        retrace_low - sl_buffer_pips * _PIP,
        "return_candle":   return_bar["datetime"],
        "return_price":    return_bar["close"],
        "retrace_pips":    round(retrace_pips, 1),
    }


def _find_short_induction(
    window: pd.DataFrame,
    min_retrace_pips: float,
    max_overshoot_pips: float,
    sl_buffer_pips: int,
) -> dict | None:
    """
    Induccion para entrada SHORT:
      - Precio subio (retroceso alcista hacia swing high previo)
      - Barrido del swing high
      - Precio regresa bajista
    """
    half = len(window) // 2
    swing_high_idx = window["high"].iloc[:half].idxmax()
    swing_high     = window["high"].iloc[swing_high_idx]

    retrace_bars = window.iloc[swing_high_idx:]
    if retrace_bars.empty:
        return None

    retrace_high     = retrace_bars["high"].max()
    retrace_high_idx = retrace_bars["high"].idxmax()

    retrace_pips = (retrace_high - swing_high) / _PIP
    if retrace_pips < min_retrace_pips:
        return None

    overshoot_pips = (retrace_high - swing_high) / _PIP
    if overshoot_pips > max_overshoot_pips:
        return None

    return_bars = window.iloc[retrace_high_idx + 1:]
    if return_bars.empty:
        return None

    return_bar = return_bars[return_bars["close"] < swing_high]
    if return_bar.empty:
        return None

    return_bar = return_bar.iloc[0]
    induction_bar = window.iloc[retrace_high_idx]

    return {
        "direction":       "short",
        "induction_time":  induction_bar["datetime"],
        "induction_price": retrace_high,
        "sl_price":        retrace_high + sl_buffer_pips * _PIP,
        "return_candle":   return_bar["datetime"],
        "return_price":    return_bar["close"],
        "retrace_pips":    round(retrace_pips, 1),
    }
