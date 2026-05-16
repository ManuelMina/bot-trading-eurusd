"""
Calcula el tamano de posicion basado en riesgo fijo por trade.

Formula:
    lotes = (capital * risk_pct) / (sl_pips * pip_value_per_lot)

Para EURUSD / GBPUSD en cuenta estandar:
    pip_value = $10 por lote estandar (1.0 lot)
    → 1 pip = $10 riesgo por lote

Uso:
    from engine.position_sizer import calculate

    lots = calculate(sl_pips=15)          # usa config por defecto
    lots = calculate(sl_pips=10, capital=2000, risk_pct=0.02)
"""

from config import CAPITAL, RISK_PCT

_PIP_VALUE_PER_LOT = 10.0   # USD por pip por lote estandar (EURUSD/GBPUSD)
_MIN_LOTS          = 0.01
_MAX_LOTS          = 10.0


def calculate(
    sl_pips: float,
    capital: float = CAPITAL,
    risk_pct: float = RISK_PCT,
    pip_value: float = _PIP_VALUE_PER_LOT,
) -> float:
    """
    Calcula el tamano de posicion en lotes.

    Parameters
    ----------
    sl_pips   : distancia del stop loss en pips.
    capital   : capital total en USD.
    risk_pct  : fraccion del capital a arriesgar (0.01 = 1%).
    pip_value : valor en USD de 1 pip por lote estandar.

    Returns
    -------
    Tamano de posicion en lotes, redondeado a 2 decimales.
    Siempre en el rango [_MIN_LOTS, _MAX_LOTS].
    """
    if sl_pips <= 0:
        raise ValueError(f"sl_pips debe ser > 0, recibido: {sl_pips}")

    risk_amount = capital * risk_pct
    lots = risk_amount / (sl_pips * pip_value)
    lots = round(lots, 2)
    return max(_MIN_LOTS, min(_MAX_LOTS, lots))


def sl_pips_from_prices(
    entry_price: float,
    sl_price: float,
    pip_size: float = 0.0001,
) -> float:
    """
    Calcula la distancia entre entry y SL en pips.
    Funciona para long y short (usa valor absoluto).
    """
    return abs(entry_price - sl_price) / pip_size


def tp_price(
    entry_price: float,
    sl_price: float,
    direction: str,
    rr: float = 3.0,
) -> float:
    """
    Calcula el precio de take profit dado un ratio riesgo/recompensa.

    Parameters
    ----------
    entry_price : precio de entrada.
    sl_price    : precio de stop loss.
    direction   : "long" o "short".
    rr          : ratio riesgo/recompensa (por defecto 3.0 = 1:3).

    Returns
    -------
    Precio de take profit.
    """
    distance = abs(entry_price - sl_price)
    if direction == "long":
        return entry_price + distance * rr
    return entry_price - distance * rr
