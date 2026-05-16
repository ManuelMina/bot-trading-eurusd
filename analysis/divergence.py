"""
Detecta divergencias completas entre EURUSD y GBPUSD.

Definicion de divergencia (segun la estrategia):
    Si EURUSD hace un nuevo maximo/minimo y GBPUSD NO lo acompana (o viceversa)
    → el par que indujo (hizo el nuevo extremo sin correspondencia) se alejara con fuerza.

    El "par que indujo" es el que hizo el movimiento sin ser confirmado por el otro.

Logica de deteccion:
    Ventana de comparacion: ultimas N velas M5 (configurable, por defecto 12 = 1 hora)

    Para CADA par calcular:
        new_high = close actual > max(high de la ventana anterior)
        new_low  = close actual < min(low  de la ventana anterior)

    Divergencia alcista (sesgo LONG):
        EURUSD hace new_low Y GBPUSD NO hace new_low
        → EURUSD indujo hacia abajo → esperar rebote alcista en EURUSD

    Divergencia bajista (sesgo SHORT):
        EURUSD hace new_high Y GBPUSD NO hace new_high
        → EURUSD indujo hacia arriba → esperar caida en EURUSD

Uso:
    from analysis.divergence import check

    result = check(eu_bars, gu_bars, window=12)
    if result["divergence"]:
        print(result["direction"])   # "long" o "short"
"""

import pandas as pd

# Ventana por defecto: cuantas velas M5 hacia atras para comparar extremos
_DEFAULT_WINDOW = 12   # 12 velas M5 = 60 minutos


def check(
    eu_bars: pd.DataFrame,
    gu_bars: pd.DataFrame,
    window: int = _DEFAULT_WINDOW,
) -> dict:
    """
    Evalua si existe divergencia EURUSD/GBPUSD en el momento actual.

    Parameters
    ----------
    eu_bars : DataFrame M5 de EURUSD, ordenado cronologicamente.
              Debe tener al menos window + 1 filas.
    gu_bars : DataFrame M5 de GBPUSD, ordenado cronologicamente.
              Sincronizado temporalmente con eu_bars.
    window  : cuantas velas hacia atras comparar para detectar nuevo extremo.

    Returns
    -------
    {
        "divergence": bool,
        "direction":  "long" | "short" | None,
        "eu_new_high": bool,
        "eu_new_low":  bool,
        "gu_new_high": bool,
        "gu_new_low":  bool,
        "note": str  descripcion legible del resultado
    }
    """
    result = {
        "divergence":  False,
        "direction":   None,
        "eu_new_high": False,
        "eu_new_low":  False,
        "gu_new_high": False,
        "gu_new_low":  False,
        "note":        "sin datos suficientes",
    }

    if len(eu_bars) < window + 1 or len(gu_bars) < window + 1:
        return result

    eu_recent  = eu_bars.iloc[-(window + 1):]
    gu_recent  = gu_bars.iloc[-(window + 1):]

    eu_prev    = eu_recent.iloc[:-1]
    gu_prev    = gu_recent.iloc[:-1]

    eu_close   = float(eu_recent.iloc[-1]["close"])
    gu_close   = float(gu_recent.iloc[-1]["close"])

    eu_new_high = eu_close > eu_prev["high"].max()
    eu_new_low  = eu_close < eu_prev["low"].min()
    gu_new_high = gu_close > gu_prev["high"].max()
    gu_new_low  = gu_close < gu_prev["low"].min()

    result["eu_new_high"] = eu_new_high
    result["eu_new_low"]  = eu_new_low
    result["gu_new_high"] = gu_new_high
    result["gu_new_low"]  = gu_new_low

    if eu_new_low and not gu_new_low:
        result["divergence"] = True
        result["direction"]  = "long"
        result["note"]       = "EURUSD hizo nuevo minimo; GBPUSD no lo acompana -> induccion bajista en EU, esperar rebote LONG"

    elif eu_new_high and not gu_new_high:
        result["divergence"] = True
        result["direction"]  = "short"
        result["note"]       = "EURUSD hizo nuevo maximo; GBPUSD no lo acompana -> induccion alcista en EU, esperar caida SHORT"

    elif gu_new_low and not eu_new_low:
        result["divergence"] = True
        result["direction"]  = "long"
        result["note"]       = "GBPUSD hizo nuevo minimo; EURUSD no lo acompana -> sesgo LONG en EURUSD"

    elif gu_new_high and not eu_new_high:
        result["divergence"] = True
        result["direction"]  = "short"
        result["note"]       = "GBPUSD hizo nuevo maximo; EURUSD no lo acompana -> sesgo SHORT en EURUSD"

    else:
        result["note"] = "ambos pares se mueven juntos o no hay nuevo extremo"

    return result


def scan(
    eu_df: pd.DataFrame,
    gu_df: pd.DataFrame,
    window: int = _DEFAULT_WINDOW,
) -> pd.DataFrame:
    """
    Escanea toda la serie M5 buscando divergencias (vectorizado, O(n)).

    Parameters
    ----------
    eu_df  : DataFrame M5 EURUSD completo.
    gu_df  : DataFrame M5 GBPUSD completo, sincronizado con eu_df.
    window : ventana de comparacion en velas (default 12 = 60 min).

    Returns
    -------
    DataFrame con columnas: datetime, divergence, direction,
    eu_new_high, eu_new_low, gu_new_high, gu_new_low.
    Solo incluye filas donde divergence == True.
    """
    # Alinear por datetime
    eu_df = eu_df.set_index("datetime")
    gu_df = gu_df.set_index("datetime")
    common = eu_df.index.intersection(gu_df.index)
    eu_df  = eu_df.loc[common].reset_index()
    gu_df  = gu_df.loc[common].reset_index()

    # Rolling max/min de las 'window' velas ANTERIORES (no incluir la actual)
    # shift(1) + rolling(window) = maximo de las [i-window .. i-1] velas
    eu_prev_high = pd.Series(eu_df["high"].values).rolling(window, min_periods=window).max().shift(1).values
    eu_prev_low  = pd.Series(eu_df["low"].values).rolling(window, min_periods=window).min().shift(1).values
    gu_prev_high = pd.Series(gu_df["high"].values).rolling(window, min_periods=window).max().shift(1).values
    gu_prev_low  = pd.Series(gu_df["low"].values).rolling(window, min_periods=window).min().shift(1).values

    eu_close = eu_df["close"].values
    gu_close = gu_df["close"].values

    eu_new_high = eu_close > eu_prev_high
    eu_new_low  = eu_close < eu_prev_low
    gu_new_high = gu_close > gu_prev_high
    gu_new_low  = gu_close < gu_prev_low

    long_mask  = (eu_new_low & ~gu_new_low)  | (gu_new_high & ~eu_new_high)
    short_mask = (eu_new_high & ~gu_new_high) | (gu_new_low  & ~eu_new_low)
    div_mask   = long_mask | short_mask

    # Ignorar filas con NaN en rolling (primeras 'window' filas)
    nan_mask = ~(
        pd.isnull(eu_prev_high) | pd.isnull(eu_prev_low) |
        pd.isnull(gu_prev_high) | pd.isnull(gu_prev_low)
    )
    div_mask = div_mask & nan_mask

    direction = pd.array([""] * len(eu_df), dtype=object)
    direction[long_mask  & nan_mask] = "long"
    direction[short_mask & nan_mask] = "short"
    # Si ambos son True (edge case), short toma prioridad
    direction[long_mask & short_mask & nan_mask] = "short"

    result = pd.DataFrame({
        "datetime":    eu_df["datetime"],
        "divergence":  div_mask,
        "direction":   direction,
        "eu_new_high": eu_new_high,
        "eu_new_low":  eu_new_low,
        "gu_new_high": gu_new_high,
        "gu_new_low":  gu_new_low,
    })
    return result[result["divergence"]].reset_index(drop=True)


def scan_legacy(
    eu_df: pd.DataFrame,
    gu_df: pd.DataFrame,
    window: int = _DEFAULT_WINDOW,
) -> pd.DataFrame:
    """Version original (lenta) de scan(). Mantenida para referencia."""
    eu_df = eu_df.set_index("datetime")
    gu_df = gu_df.set_index("datetime")
    common = eu_df.index.intersection(gu_df.index)
    eu_df = eu_df.loc[common].reset_index()
    gu_df = gu_df.loc[common].reset_index()

    rows = []
    for i in range(window + 1, len(eu_df)):
        eu_window = eu_df.iloc[i - window - 1: i + 1]
        gu_window = gu_df.iloc[i - window - 1: i + 1]
        r = check(eu_window, gu_window, window)
        if r["divergence"]:
            rows.append({
                "datetime":   eu_df.iloc[i]["datetime"],
                "divergence": True,
                "direction":  r["direction"],
                "eu_new_high": r["eu_new_high"],
                "eu_new_low":  r["eu_new_low"],
                "gu_new_high": r["gu_new_high"],
                "gu_new_low":  r["gu_new_low"],
            })

    return pd.DataFrame(rows)
