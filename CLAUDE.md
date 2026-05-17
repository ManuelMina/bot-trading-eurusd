# CLAUDE.md — Bot de Trading (MT5 + Python)

> Instrucciones para Claude Code en este proyecto.

---

## Qué es este proyecto

Bot de trading algorítmico basado en una estrategia de **reacción al mercado** (no predicción). La estrategia se apoya en ciclos de liquidez, inducciones, aperturas como magnetos y divergencias entre pares de divisas.

La documentación completa de la estrategia está en [ESTRATEGIA.md](ESTRATEGIA.md). **Leerla antes de modificar cualquier lógica de análisis.**

---

## Estado actual del proyecto

| Fase | Estado | Descripción |
|---|---|---|
| 1. Infraestructura de datos | **COMPLETO** | config.py, data/fetcher.py, estructura de carpetas, .gitignore |
| 2. Módulos de análisis base | **COMPLETO** | asia_range, opening_magnets, cycle_detector, induction_detector, divergence, quarters_theory |
| 3. Lógica de entrada | **COMPLETO** | entry_logic.py, position_sizer.py |
| 4. Motor de backtesting | **COMPLETO** | backtester.py — walk-forward 2024 y 2025 ejecutado |
| 5. Reportes | **COMPLETO** | report.py — métricas completas por T1/T2/T3, ciclo y mes |
| 6. Optimización de parámetros | Pendiente | Ajustar en base a resultados del primer backtest |

---

## Stack técnico

- **Lenguaje:** Python 3.10+
- **Broker/Plataforma:** MetaTrader 5 (MT5 instalado, broker configurado, sin capital real)
- **Librería MT5:** `MetaTrader5` (pip install MetaTrader5)
- **Datos:** MT5 histórico local + CSV como caché para backtesting
- **Zona horaria operativa:** New York (EDT = UTC-4 en verano, EST = UTC-5 en invierno). Todo en hora NY.
- **Zona horaria MT5:** Verificar al conectar; normalizar todo a UTC internamente

---

## Estructura de archivos prevista

```
BOT TRADING/
├── CLAUDE.md                  ← este archivo
├── ESTRATEGIA.md              ← documentación completa de la estrategia
├── config.py                  ← parámetros globales configurables
├── requirements.txt
├── data/
│   ├── fetcher.py             ← conexión MT5 → descarga OHLCV histórico
│   └── cache/                 ← CSVs de datos descargados (no commitear datos grandes)
├── analysis/
│   ├── asia_range.py          ← High/Low de la sesión asiática (hora NY, DST-aware)
│   ├── opening_magnets.py     ← niveles 00:00 NY y 07:30 NY + sesgo direccional
│   ├── cycle_detector.py      ← Normal / Knockout / Retail Heaven / Sierra
│   ├── induction_detector.py  ← pullback a nivel clave → rebote → nivel de SL
│   ├── divergence.py          ← EURUSD vs GBPUSD: nuevo extremo sin correspondencia
│   └── quarters_theory.py     ← bloques 6h, cuarto actual saca extremo del anterior
├── engine/
│   ├── entry_logic.py         ← vela de fuerza + alineación de confirmaciones
│   ├── position_sizer.py      ← lotes según SL pips y 1% de capital
│   └── backtester.py          ← motor walk-forward día a día
├── reporting/
│   └── report.py              ← métricas y visualizaciones
└── tests/
    └── ...                    ← unit tests por módulo
```

---

## Parámetros clave (ver config.py)

```python
CAPITAL              = 200      # USD (cuenta de fondeo/prop)
RISK_PCT             = 0.03     # 3% por trade (≈$6 con $200)
RISK_REWARD          = 3.0      # TP fijo 1:3
SL_BUFFER_PIPS       = 2        # pips extra sobre el extremo de inducción
SYMBOL_MAIN          = "EURUSD"
SYMBOL_DIV           = "GBPUSD"
TF_ANALYSIS          = "M5"
TF_ENTRY             = "M1"
TRADING_START_NY     = "09:30"  # hora New York (DST-aware)
TRADING_END_NY       = "13:00"  # hora New York (DST-aware)
TRADING_T3_CUTOFF_NY = "12:30"  # hora New York — último momento para T3
ASIA_START_NY        = "19:00"  # hora New York (día anterior)
ASIA_END_NY          = "00:00"  # hora New York
MAGNET_2_NY          = "07:30"  # hora New York — único magneto operativo
BACKTEST_YEARS       = [2024, 2025]
SIERRA_SWEEP_PIPS    = 3        # pips mínimos para confirmar barrido Sierra (ajustable)
MAX_TRADES_DAY       = 2        # máximo trades normales por día
EXCELLENCE_BODY_MULT = 1.5      # multiplicador cuerpo vela para condición de excelencia (T3)
EXCELLENCE_BODY_LOOKBACK = 10   # velas hacia atrás para calcular promedio de cuerpo
MIN_CONFIRMATIONS    = 2        # confirmaciones mínimas para entrar (de 3 posibles)
```

---

## Sistema de documentación

**Todo cambio debe quedar registrado en [CHANGELOG.md](CHANGELOG.md).**

Al hacer cualquier modificación (regla, parámetro, corrección, resultado de backtesting):
1. Abrir `CHANGELOG.md`
2. Agregar una fila a la tabla del día actual (o crear nueva sección de fecha)
3. Indicar: fecha | tipo | descripción | razón/contexto
4. Si el cambio afecta `ESTRATEGIA.md` o `CLAUDE.md`, actualizar también esos archivos

Tipos válidos de entrada:
- `REGLA` — nueva regla de la estrategia
- `PARÁMETRO` — valor numérico ajustado
- `CORRECCIÓN` — corrección a lógica existente
- `MEJORA` — optimización sin cambio de lógica
- `RESULTADO` — resultado de un backtest o prueba
- `OBSERVACIÓN` — patrón o hallazgo notable sin acción inmediata
- `DECISIÓN` — decisión de diseño o arquitectura

---

## Gestión de trades diarios (lógica del backtester)

```
T1: primer trade del día
  → PIERDE: no generar T2 ese día (daily_trades_done = True)
  → GANA:   permitir buscar T2

T2: segundo trade (solo si T1 ganó)
  → PIERDE: cerrar día (daily_trades_done = True)
  → GANA:   evaluar si el próximo setup cumple EXCELENCIA

T3: tercer trade (solo si T1+T2 ganaron Y excellence_score == True)
  → cualquier resultado: cerrar día (daily_trades_done = True)
```

**Condiciones de EXCELENCIA (todas deben cumplirse):**
- Ciclo del día claramente identificado (no Sierra ambigua)
- Las 3 confirmaciones activas simultáneamente (divergencia + cuartos + apertura)
- Inducción limpia (precio tocó el nivel con precisión)
- Vela de fuerza con body ≥ `EXCELLENCE_BODY_MULT` × promedio últimas `EXCELLENCE_BODY_LOOKBACK` velas
- Entrada antes de `TRADING_T3_CUTOFF_NY` (12:30 NY)

**Si el backtesting muestra win rate negativo en T3:**
Revisar y ajustar condiciones en este orden (documentar cada cambio en `CHANGELOG.md`):
1. Subir `EXCELLENCE_BODY_MULT` de 1.5 → 2.0
2. Exigir divergencia confirmada en M5 y M1 simultáneamente
3. Reducir `TRADING_T3_CUTOFF` de 09:30 → 09:00
4. Restringir T3 solo a ciclo Normal
5. Deshabilitar T3 completamente (`MAX_TRADES_DAY = 2` permanente)

---

## Reglas de desarrollo

### Documentación obligatoria
- Cada cambio al código que modifique la lógica de la estrategia → entrada en `CHANGELOG.md`.
- Cada resultado de backtesting → entrada tipo `RESULTADO` con métricas clave.
- Si el usuario reporta un patrón observado en el mercado → entrada tipo `OBSERVACIÓN`.

### Al modificar lógica de análisis
- Siempre leer `ESTRATEGIA.md` antes de cambiar la lógica de un módulo.
- No simplificar ni reemplazar conceptos de la estrategia con indicadores técnicos estándar (RSI, MACD, etc.) a menos que el usuario lo pida explícitamente.
- La estrategia es **reacción**, no predicción: los módulos detectan patrones ocurridos, no proyectan futuros.

### Al agregar confirmaciones
- El sistema requiere que al menos **2 confirmaciones** se alineen para generar una señal.
- El orden de prioridad es: Divergencia > Cuartos > Aperturas Magneto.
- No agregar confirmaciones nuevas sin que el usuario las valide primero.

### Días operativos
- Solo de **lunes a viernes**.
- Excluir **festivos de Nueva York** (New Year's Day, MLK Day, Presidents Day, Memorial Day, Independence Day, Labor Day, Thanksgiving, Christmas).
- Implementar lista de festivos en `config.py`.

### Zona horaria
- Todo el procesamiento interno en **UTC**.
- La referencia externa es **hora New York** (NY) — usar `ZoneInfo("America/New_York")` para conversiones.
- NY cambia entre EDT (UTC-4) y EST (UTC-5) en marzo y noviembre. Manejar el offset dinámicamente.
- **No usar hora Colombia** en ninguna parte del código ni de la documentación.

### Ciclo Sierra
- En Sierra: esperar sweep del High o Low del rango errático.
- Confirmar con vela de fuerza en dirección contraria al sweep.
- Objetivo: el lado opuesto del rango Sierra.
- No intentar operar el interior del rango Sierra (solo los extremos).

### Gestión de riesgo
- Position size: `lotes = (capital × risk_pct) / (sl_pips × pip_value)`
- Pip value para EURUSD en cuenta estándar: $10/pip por lote estándar.
- Para cuentas sin capital real (fondeo/prop): usar capital del fondeo como base.

### Código
- Sin comentarios que expliquen qué hace el código (los nombres lo dicen).
- Comentarios solo para invariantes no obvios o workarounds.
- Módulos independientes y testeables por separado.
- Guardar resultados de backtesting en CSV para no tener que re-ejecutar.

---

## Backtesting — Períodos y criterios

| Período | Símbolo | Propósito |
|---|---|---|
| Enero–Diciembre 2024 | EURUSD + GBPUSD M1/M5 | Validación histórica año 1 |
| Enero–Diciembre 2025 | EURUSD + GBPUSD M1/M5 | Validación histórica año 2 |

**Métricas mínimas del reporte:**
- Win rate total y por tipo de ciclo
- P&L acumulado en USD
- Drawdown máximo (absoluto y %)
- Número de trades por día/semana/mes
- Distribución por hora de entrada
- Impacto individual de cada confirmación en el win rate
- Comparativa 2024 vs 2025

---

## Comandos útiles (una vez implementado)

```bash
# Descargar datos históricos
python -m data.fetcher --symbol EURUSD --timeframe M1 --year 2024

# Ejecutar backtesting año 2024
python -m engine.backtester --year 2024

# Ejecutar backtesting año 2025
python -m engine.backtester --year 2025

# Generar reporte comparativo
python -m reporting.report --compare 2024 2025
```
