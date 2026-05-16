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
CAPITAL      = 1_000.0   # USD
RISK_PCT     = 0.01      # 1% por trade
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
}
