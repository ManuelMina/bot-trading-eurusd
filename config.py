from pathlib import Path
from zoneinfo import ZoneInfo

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
ROOT_DIR       = Path(__file__).parent
DATA_CACHE_DIR = ROOT_DIR / "data" / "cache"

# ---------------------------------------------------------------------------
# Timezones
# ---------------------------------------------------------------------------
TZ_UTC      = ZoneInfo("UTC")
TZ_COLOMBIA = ZoneInfo("America/Bogota")   # UTC-5, sin cambio horario
TZ_NEW_YORK = ZoneInfo("America/New_York") # UTC-5 invierno / UTC-4 verano

# ---------------------------------------------------------------------------
# Instruments
# ---------------------------------------------------------------------------
SYMBOL_MAIN = "EURUSD"
SYMBOL_DIV  = "GBPUSD"

# ---------------------------------------------------------------------------
# Timeframes
# ---------------------------------------------------------------------------
TF_ANALYSIS = "M5"
TF_ENTRY    = "M1"

# ---------------------------------------------------------------------------
# Risk management
# ---------------------------------------------------------------------------
CAPITAL      = 200.0     # USD
RISK_PCT     = 0.03      # 3% por trade
RISK_REWARD  = 3.0       # TP fijo 1:3
SL_BUFFER_PIPS = 2       # pips extra sobre el extremo de inducción

# ---------------------------------------------------------------------------
# Trading window — hora Colombia (America/Bogota)
# ---------------------------------------------------------------------------
TRADING_START_COL  = "07:00"
TRADING_END_COL    = "10:00"
TRADING_T3_CUTOFF  = "09:30"  # último momento para entrar T3

# ---------------------------------------------------------------------------
# Asia range — hora Colombia
# ---------------------------------------------------------------------------
ASIA_START_COL = "19:00"   # día anterior
ASIA_END_COL   = "00:00"   # día actual

# ---------------------------------------------------------------------------
# Opening magnets — hora New York
# ---------------------------------------------------------------------------
MAGNET_1_NY = "00:00"
MAGNET_2_NY = "07:30"

# ---------------------------------------------------------------------------
# Backtesting
# ---------------------------------------------------------------------------
BACKTEST_YEARS = [2024, 2025]

# ---------------------------------------------------------------------------
# News blackouts — eventos de alto impacto para EURUSD (hora UTC)
# Ventana: ±60 minutos desde el horario del evento
# Fuentes: NFP (primer viernes del mes, 13:30 UTC)
#          ECB rate decision (~6-8 veces/año, 13:15 UTC)
#          US CPI (mensual, 13:30 UTC)
# ---------------------------------------------------------------------------
NEWS_BLACKOUTS: dict[str, list[str]] = {
    # ---- 2024 ----
    # NFP
    "2024-01-05": ["13:30"], "2024-02-02": ["13:30"], "2024-03-08": ["13:30"],
    "2024-04-05": ["13:30"], "2024-05-03": ["13:30"], "2024-06-07": ["13:30"],
    "2024-07-05": ["13:30"], "2024-08-02": ["13:30"], "2024-09-06": ["13:30"],
    "2024-10-04": ["13:30"], "2024-11-01": ["13:30"], "2024-12-06": ["13:30"],
    # ECB
    "2024-01-25": ["13:15"], "2024-03-07": ["13:15"], "2024-04-11": ["13:15"],
    "2024-06-06": ["13:15"], "2024-07-18": ["13:15"], "2024-09-12": ["13:15"],
    "2024-10-17": ["13:15"], "2024-12-12": ["13:15"],
    # CPI
    "2024-01-11": ["13:30"], "2024-02-13": ["13:30"], "2024-03-12": ["13:30"],
    "2024-04-10": ["13:30"], "2024-05-15": ["13:30"], "2024-06-12": ["13:30"],
    "2024-07-11": ["13:30"], "2024-08-14": ["13:30"], "2024-09-11": ["13:30"],
    "2024-10-10": ["13:30"], "2024-11-13": ["13:30"], "2024-12-11": ["13:30"],
    # ---- 2025 ----
    # NFP
    "2025-01-10": ["13:30"], "2025-02-07": ["13:30"], "2025-03-07": ["13:30"],
    "2025-04-04": ["13:30"], "2025-05-02": ["13:30"], "2025-06-06": ["13:30"],
    "2025-07-03": ["13:30"], "2025-08-01": ["13:30"], "2025-09-05": ["13:30"],
    "2025-10-03": ["13:30"], "2025-11-07": ["13:30"], "2025-12-05": ["13:30"],
    # ECB
    "2025-01-30": ["13:15"], "2025-03-06": ["13:15"], "2025-04-17": ["13:15"],
    "2025-06-05": ["13:15"], "2025-07-24": ["13:15"], "2025-09-11": ["13:15"],
    "2025-10-30": ["13:15"], "2025-12-18": ["13:15"],
    # CPI
    "2025-01-15": ["13:30"], "2025-02-12": ["13:30"], "2025-03-12": ["13:30"],
    "2025-04-10": ["13:30"], "2025-05-13": ["13:30"], "2025-06-11": ["13:30"],
    "2025-07-15": ["13:30"], "2025-08-13": ["13:30"], "2025-09-10": ["13:30"],
    "2025-10-15": ["13:30"], "2025-11-13": ["13:30"], "2025-12-10": ["13:30"],
}

# ---------------------------------------------------------------------------
# Sierra (legacy V1)
# ---------------------------------------------------------------------------
SIERRA_SWEEP_PIPS = 3   # pips mínimos para confirmar barrido Sierra

# ---------------------------------------------------------------------------
# V2: Sweep-based entry (barrido de niveles clave)
# ---------------------------------------------------------------------------
SWEEP_MIN_PIPS       = 1    # pips mínimos para considerar un nivel barrido
MIN_SWEEP_WEIGHT     = 2    # peso mínimo del nivel (1=magnets,2=Asia,3=prev_day,4=prev_week)
MAX_LEVEL_WEIGHT     = 3    # peso máximo del nivel a usar (excluye prev_week=4 que es no confiable)
GAP_MIN_PIPS         = 5    # pips mínimos para considerar un gap semanal significativo
MAX_BARS_AFTER_SWEEP = 7    # máximo barras M1 para esperar vela de fuerza tras el barrido

# ---------------------------------------------------------------------------
# Trade management
# ---------------------------------------------------------------------------
MAX_TRADES_DAY           = 2    # máximo trades normales por día
EXCELLENCE_BODY_MULT     = 1.5  # multiplicador cuerpo vela para T3
EXCELLENCE_BODY_LOOKBACK = 10   # velas hacia atrás para calcular promedio
MIN_CONFIRMATIONS        = 2    # confirmaciones mínimas para entrada (de 3)
FILTER_KNOCKOUT          = True # excluir dias de ciclo Knockout (WR < break-even en 2024 y 2025)

# ---------------------------------------------------------------------------
# V3: Multi-timeframe top-down + Break-Even management
# ---------------------------------------------------------------------------
BE_TRIGGER_RR    = 1.5  # mover SL a entrada cuando el trade gana 1.5× el riesgo
H4_LOOKBACK_DAYS = 5    # días de historia hacia atrás para construir H4
H1_LOOKBACK_BARS = 24   # barras H1 a analizar (24 = últimas 24 horas)
HTF_SWEEP_PIPS   = 2    # pips mínimos para confirmar barrido de swing en H4/H1

# ---------------------------------------------------------------------------
# NY Federal holidays — el bot NO opera estos días
# ---------------------------------------------------------------------------
NY_HOLIDAYS: set[str] = {
    # 2021
    "2021-01-01",  # New Year's Day
    "2021-01-18",  # MLK Day
    "2021-02-15",  # Presidents Day
    "2021-05-31",  # Memorial Day
    "2021-06-19",  # Juneteenth (first year observed)
    "2021-07-05",  # Independence Day (observed, July 4 = Sunday)
    "2021-09-06",  # Labor Day
    "2021-11-25",  # Thanksgiving
    "2021-12-24",  # Christmas (observed, Dec 25 = Saturday)
    # 2022
    "2022-01-17",  # MLK Day (Jan 1 = Saturday, no extra day)
    "2022-02-21",  # Presidents Day
    "2022-05-30",  # Memorial Day
    "2022-06-19",  # Juneteenth
    "2022-07-04",  # Independence Day
    "2022-09-05",  # Labor Day
    "2022-11-24",  # Thanksgiving
    "2022-12-26",  # Christmas (observed, Dec 25 = Sunday)
    # 2023
    "2023-01-02",  # New Year's Day (observed, Jan 1 = Sunday)
    "2023-01-16",  # MLK Day
    "2023-02-20",  # Presidents Day
    "2023-05-29",  # Memorial Day
    "2023-06-19",  # Juneteenth
    "2023-07-04",  # Independence Day
    "2023-09-04",  # Labor Day
    "2023-11-23",  # Thanksgiving
    "2023-12-25",  # Christmas
    # 2024
    "2024-01-01",  # New Year's Day
    "2024-01-15",  # MLK Day
    "2024-02-19",  # Presidents Day
    "2024-05-27",  # Memorial Day
    "2024-06-19",  # Juneteenth
    "2024-07-04",  # Independence Day
    "2024-09-02",  # Labor Day
    "2024-11-28",  # Thanksgiving
    "2024-12-25",  # Christmas
    # 2025
    "2025-01-01",  # New Year's Day
    "2025-01-20",  # MLK Day
    "2025-02-17",  # Presidents Day
    "2025-05-26",  # Memorial Day
    "2025-06-19",  # Juneteenth
    "2025-07-04",  # Independence Day
    "2025-09-01",  # Labor Day
    "2025-11-27",  # Thanksgiving
    "2025-12-25",  # Christmas
    # 2026
    "2026-01-01",  # New Year's Day
    "2026-01-19",  # MLK Day
    "2026-02-16",  # Presidents Day
    "2026-05-25",  # Memorial Day
    "2026-06-19",  # Juneteenth
    "2026-07-03",  # Independence Day (observed, July 4 = Saturday)
    "2026-09-07",  # Labor Day
    "2026-11-26",  # Thanksgiving
    "2026-12-25",  # Christmas
}
