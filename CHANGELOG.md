# Changelog — Bot de Trading

Registro de cada cambio, decisión, prueba y resultado del proyecto.  
Formato: `[FECHA] | [TIPO] | [DESCRIPCIÓN] | [RAZÓN / CONTEXTO]`

**Tipos:**
- `REGLA` — nueva regla de la estrategia
- `PARÁMETRO` — valor numérico ajustado
- `CORRECCIÓN` — corrección a lógica existente
- `MEJORA` — optimización sin cambio de lógica
- `RESULTADO` — resultado de un backtest o prueba
- `OBSERVACIÓN` — patrón o hallazgo notable sin acción inmediata
- `DECISIÓN` — decisión de diseño o arquitectura

---

## 2026-05-11 — Fase 1: Infraestructura de datos

| Fecha | Tipo | Descripción | Razón / Contexto |
|---|---|---|---|
| 2026-05-11 | DECISIÓN | Stack definido: MT5 + Python, backtesting primero | No hay capital real; validar estrategia antes de operar en vivo |
| 2026-05-11 | DECISIÓN | Instrumentos: EURUSD (entradas) + GBPUSD (divergencias) | Profesor opera 90% EURUSD; GBPUSD solo para confirmar divergencias |
| 2026-05-11 | PARÁMETRO | Capital test: $1,000 / Riesgo: 1% / TP: 1:3 fijo | Backtesting inicial; ajustar según resultados |
| 2026-05-11 | PARÁMETRO | Ventana operativa: 07:00–10:00 Colombia | Mejores setups después de 08:00 Colombia (09:00 NY) |
| 2026-05-11 | PARÁMETRO | Rango Asia: 19:00–00:00 Colombia | Equivale a 00:00–05:00 UTC |
| 2026-05-11 | PARÁMETRO | SL: extremo vela de inducción + 2–3 pips buffer | Stoploss mínimo mencionado por el profesor en clases |
| 2026-05-11 | DECISIÓN | Backtesting en dos períodos separados: 2024 y 2025 | Estadísticas recientes más representativas (filosofía del profesor) |
| 2026-05-11 | REGLA | Días operativos: lunes a viernes, excluir festivos NY | El mercado tiene menos liquidez y movimiento en festivos |
| 2026-05-11 | PARÁMETRO | Sierra sweep mínimo: 3 pips (ajustable) | Filtrar falsos barridos; ajustar en backtesting |
| 2026-05-11 | REGLA | Máximo 2 trades por día; 3ro solo si T1+T2 ganaron y setup es excelente | Garantizar calidad sobre cantidad; evitar overtrading |
| 2026-05-11 | REGLA | Si T1 pierde → no entrar T2. Si T1 gana y T2 pierde → cerrar día | Proteger capital; no operar en modo venganza |
| 2026-05-11 | REGLA | Documentar cada cambio en este archivo con fecha y razón | Mejorar la estrategia basándose en datos, no en intuición |
| 2026-05-11 | REGLA | Condiciones de excelencia T3 definidas: ciclo claro + 3 confirmaciones + inducción limpia + vela ≥1.5× promedio + entrada antes 09:30 Colombia | Aprobadas por el usuario; sujetas a revisión si el backtesting muestra pérdidas en T3 |
| 2026-05-11 | REGLA | Si el backtesting muestra win rate negativo en T3 → revisar y endurecer condiciones de excelencia antes de continuar | El T3 es excepcional; si pierde consistentemente es señal de que las condiciones no son suficientemente estrictas |
| 2026-05-11 | DECISIÓN | Fase 1 iniciada: estructura de carpetas, config.py, data/fetcher.py | Primer paso antes de cualquier lógica de análisis |
| 2026-05-11 | DECISIÓN | Todos los datos almacenados en UTC internamente; conversión a Colombia solo para filtros de ventana | Evitar bugs de timezone en backtesting |
| 2026-05-11 | DECISIÓN | Caché en CSV por símbolo/timeframe/año; se excluye del control de versiones (.gitignore) | Archivos grandes (~700k filas M1); se regeneran con MT5 |
| 2026-05-11 | PARÁMETRO | NY_HOLIDAYS definidos en config.py para 2024 y 2025 (9 días cada año) | El bot no opera en festivos de Nueva York |
| 2026-05-11 | OBSERVACIÓN | MT5 conectado a MetaQuotes demo — solo tiene M1 desde feb 2026, M5 desde ene 2025 | El broker real (ICMarkets) tiene más historia; pendiente reconectar |
| 2026-05-11 | DECISIÓN | Se creó data/histdata_loader.py para cargar datos desde HistData.com | HistData tiene EURUSD/GBPUSD M1 desde 2000; descarga manual requerida (bloquean POST automatizado) |
| 2026-05-11 | DECISIÓN | Fuente de datos: HistData.com (manual) como plan A; ICMarkets MT5 como plan B | Ambas rutas procesadas por fetcher.py con el mismo formato de caché |

---

## 2026-05-11 — Fase 2: Módulos de análisis base

| Fecha | Tipo | Descripción | Razón / Contexto |
|---|---|---|---|
| 2026-05-11 | DECISIÓN | Creado analysis/asia_range.py — calcula High/Low diario 00:00-05:00 UTC (19:00-00:00 Colombia) | Módulo base del que dependen cycle_detector, opening_magnets e induction_detector |
| 2026-05-11 | DECISIÓN | Creado analysis/opening_magnets.py — niveles 00:00 NY y 07:30 NY + sesgo por precio relativo | Usa ZoneInfo para manejar DST de New York automáticamente |
| 2026-05-11 | DECISIÓN | Creado analysis/cycle_detector.py — clasifica Normal / Knockout / RetailHeaven / Sierra | Umbral de choppiness 62% para separar RetailHeaven de Sierra; ajustable en backtesting |
| 2026-05-11 | DECISIÓN | Creado analysis/induction_detector.py — detecta barrido de swing + retorno en ventana M1 | Lookback 20 velas, retroceso mínimo 2 pips, overshoot máximo 5 pips; todos ajustables |
| 2026-05-11 | DECISIÓN | Creado analysis/divergence.py — detecta divergencias EURUSD/GBPUSD con ventana M5 | Ventana 12 velas M5 (60 min); función scan() para uso en backtesting completo |
| 2026-05-11 | DECISIÓN | Creado analysis/quarters_theory.py — bloques 6h hora NY, cuarto actual saca extremo del anterior | Maneja correctamente Q4→Q1 (cruce de día) y DST de New York |
| 2026-05-11 | PARÁMETRO | cycle_detector: umbral choppiness = 0.62 para clasificar RetailHeaven vs Sierra | Valor inicial conservador; revisar distribución de ciclos en backtesting antes de ajustar |
| 2026-05-11 | PARÁMETRO | induction_detector: min_retrace = 2 pips, max_overshoot = 5 pips, lookback = 20 velas M1 | Parámetros de entrada; se esperan ajustes una vez se corra el backtesting completo |

---

## 2026-05-11 — Fase 3+4+5: Motor de entrada, position sizer y backtester

| Fecha | Tipo | Descripción | Razón / Contexto |
|---|---|---|---|
| 2026-05-11 | DECISIÓN | Creado engine/entry_logic.py — vela de fuerza + confirmaciones + inducción | Combina todos los módulos de análisis en una señal accionable |
| 2026-05-11 | DECISIÓN | Creado engine/position_sizer.py — lotes = (capital × 1%) / (sl_pips × $10) | $10/pip por lote estándar en EURUSD/GBPUSD |
| 2026-05-11 | DECISIÓN | Creado engine/backtester.py con pre-computación vectorizada de señales | Pre-calcula divergencia, cuartos y magnetos en M5 una sola vez antes del bucle M1 |
| 2026-05-11 | MEJORA | Vectorizado divergence.scan() — de O(n×window) a O(n) usando rolling().max/min() | Speedup de 930×: de ~56 segundos a 0.06 segundos por año |
| 2026-05-11 | MEJORA | Agregado quarters_theory.precompute() vectorizado | Elimina O(n²) de filtrar el DataFrame completo en cada barra M1 |
| 2026-05-11 | DECISIÓN | Creado reporting/report.py — métricas por T1/T2/T3, ciclo, mes y comparativa 2024 vs 2025 | Primer reporte completo del sistema |

---

## 2026-05-11 — Resultados del primer backtest completo

| Fecha | Tipo | Descripción | Razón / Contexto |
|---|---|---|---|
| 2026-05-11 | RESULTADO | 2024: 253 trades / WR 29.6% / P&L +$534 (+53.4%) / MaxDD $289 (28.9%) / PF 1.29 | Capital $1,000 / riesgo 1% / TP 1:3 / MIN_CONFIRMATIONS=2 |
| 2026-05-11 | RESULTADO | 2025: 252 trades / WR 38.5% / P&L +$2,704 (+270%) / MaxDD $247 (7.8%) / PF 1.85 | Capital $1,000 / riesgo 1% / TP 1:3 / MIN_CONFIRMATIONS=2 |
| 2026-05-11 | OBSERVACIÓN | T1 WR: 20.7% (2024) y 31.4% (2025) — T1 en 2024 está BAJO el punto de equilibrio (25%) | T1 solo es rentable en 2025; el sistema depende fuertemente de T2 para ser rentable |
| 2026-05-11 | OBSERVACIÓN | T2 WR: 68.4% (2024) y 70.5% (2025) — consistente y muy por encima del break-even | El filtro "T1 ganó antes de T2" funciona perfectamente; T2 es el trade más rentable |
| 2026-05-11 | OBSERVACIÓN | T3 WR: 85.7% (2024, 7 trades) y 50% (2025, 4 trades) — muestra pequeña, resultados no concluyentes | Mantener condiciones actuales de excelencia; necesita más muestra estadística |
| 2026-05-11 | OBSERVACIÓN | Sierra: 0% WR en ambos años (5 trades cada año) — la lógica de entrada Sierra no funciona | Pendiente revisar: ¿el sweep se está detectando correctamente? ¿el TP es el lado opuesto del rango? |
| 2026-05-11 | OBSERVACIÓN | Ciclo Normal supera a Knockout en 2025 (48.6% vs 32.4% WR) | Considerar dar preferencia a setups en ciclo Normal en futuras optimizaciones |
| 2026-05-11 | OBSERVACIÓN | Variación significativa entre años: 2024 (PF 1.29) vs 2025 (PF 1.85) | El sistema es rentable en ambos años pero con robustez variable; necesita más años de datos |
| 2026-05-11 | OBSERVACIÓN | Mejor combinación de confirmaciones: divergencia+cuartos+magnetos (WR 35-36%) | Las 3 confirmaciones juntas son más confiables que cualquier combinación de 2 |

---

## 2026-05-16 — Versión 2: Barridos de niveles clave (Sweep-based V2)

### Backup de V1

| Fecha | Tipo | Descripción | Razón / Contexto |
|---|---|---|---|
| 2026-05-16 | DECISIÓN | V1 results backed up en `reporting/results/v1/` | Preservar resultados originales antes de cualquier cambio de lógica |

### Nuevos módulos creados para V2

| Fecha | Tipo | Descripción | Razón / Contexto |
|---|---|---|---|
| 2026-05-16 | DECISIÓN | Creado `analysis/levels.py` — catálogo de niveles clave con pesos por antigüedad | Magnetos=1, Asia=2, dia_anterior=3, semana_anterior=4. Los niveles más viejos tienen mayor influencia |
| 2026-05-16 | DECISIÓN | Creado `analysis/gap_detector.py` — detecta gaps semanales y retorna sesgo direccional | Gap alcista → sesgo SHORT (precio vuelve a llenarlo); gap bajista → sesgo LONG |
| 2026-05-16 | DECISIÓN | Clase `Level` tiene campo `side`: "high" → solo SHORT, "low" → solo LONG, "both" → ambos | Corrección crítica: HIGH levels solo generan SHORT (fake breakout), LOW levels solo generan LONG (fake breakdown) |

### Cambios en engine/backtester.py (V2)

| Fecha | Tipo | Descripción | Razón / Contexto |
|---|---|---|---|
| 2026-05-16 | DECISIÓN | Reemplazado detector de inducción por detección de barrido de nivel clave | El concepto de "barrido" es más preciso: precio cruza un nivel H/L por ≥ SWEEP_MIN_PIPS desde el lado correcto |
| 2026-05-16 | DECISIÓN | Vela de fuerza: `cuerpo >= cuerpo_de_la_vela_del_barrido` (no cuerpo > max desde el barrido) | Más preciso con la descripción del usuario: "debe ser mayor a la vela de bajada" |
| 2026-05-16 | PARÁMETRO | MAX_BARS_AFTER_SWEEP = 7 — abandona el barrido si no aparece vela de fuerza en 7 barras | El usuario dijo que la reversión ocurre en 1-5 velas; 7 da margen sin que la entrada sea tardía |
| 2026-05-16 | PARÁMETRO | MAX_LEVEL_WEIGHT = 3 — excluye niveles de semana anterior (peso=4) | prev_week tuvo 0% WR en 2025 consistentemente; nivel demasiado alejado para ser relevante en la ventana operativa |
| 2026-05-16 | PARÁMETRO | SWEEP_MIN_PIPS = 1 / MIN_SWEEP_WEIGHT = 2 (Asia o mayor) / GAP_MIN_PIPS = 5 | Parámetros iniciales V2 ajustables en optimización |
| 2026-05-16 | CORRECCIÓN | Validación SL: para LONG sl < entry; para SHORT sl > entry — descarta trades con SL invertido | Evita entradas donde la vela de fuerza cerró debajo del mínimo del barrido |
| 2026-05-16 | MEJORA | Pre-computación de daily_hl y weekly_hl una sola vez antes del bucle de días | Evita O(n²) de filtrar el DataFrame completo en cada día |
| 2026-05-16 | MEJORA | Gap semanal como 4a confirmación opcional (además de divergencia, cuartos, magnetos) | Si el sesgo del gap coincide con la dirección del trade → suma 1 confirmación |

### Resultados V2 y comparativa con V1

| Fecha | Tipo | Descripción | Razón / Contexto |
|---|---|---|---|
| 2026-05-16 | RESULTADO | V2 2024: 94 trades / WR 25.5% / P&L +$6 (+0.6%) / MaxDD $213 (20.1%) / PF 1.01 | Capital $1,000 / riesgo 1% / TP 1:3 / MIN_CONFIRMATIONS=2 / niveles Asia+dia_anterior |
| 2026-05-16 | RESULTADO | V2 2025: 92 trades / WR 31.5% / P&L +$251 (+25.1%) / MaxDD $168 (16.0%) / PF 1.38 | Capital $1,000 / riesgo 1% / TP 1:3 / MIN_CONFIRMATIONS=2 / niveles Asia+dia_anterior |

### Comparativa V1 vs V2

| Métrica | V1 2024 | V2 2024 | V1 2025 | V2 2025 |
|---|---|---|---|---|
| Trades | 253 | 94 | 252 | 92 |
| WR | 29.6% | 25.5% | 38.5% | 31.5% |
| P&L | +$534 (+53%) | +$6 (+0.6%) | +$2,704 (+270%) | +$251 (+25.1%) |
| MaxDD | $289 (28.9%) | $213 (20.1%) | $247 (7.8%) | $168 (16.0%) |
| PF | 1.29 | 1.01 | 1.85 | 1.38 |
| T1 WR | 20.7% | 21.0% | 31.4% | 30.9% |
| T2 WR | 68.4% | 50.0% | 70.5% | 40.0% |

### Hallazgos críticos de V2

| Fecha | Tipo | Descripción | Razón / Contexto |
|---|---|---|---|
| 2026-05-16 | OBSERVACIÓN | **Ciclo KNOCKOUT tiene WR 9.5% (2024) y 22.5% (2025)** — bajo break-even en ambos años | En Knockout el precio sigue en una dirección; los barridos de niveles en contra de esa dirección fracasan |
| 2026-05-16 | OBSERVACIÓN | **Ciclo NORMAL tiene WR 29.6% (2024) y 37.3% (2025)** — rentable en ambos años | El ciclo Normal es el entorno ideal para el concepto de barrido: el precio regresa al rango después del sweep |
| 2026-05-16 | OBSERVACIÓN | **Asia_high → SHORT es el mejor setup**: WR 35.3% (2024) y 48.1% (2025) | Fake breakout sobre el máximo de la sesión asiática es un patrón institucional muy confiable |
| 2026-05-16 | OBSERVACIÓN | **prev_day_low → LONG funciona en 2024** (WR 36.8%) pero solo break-even en 2025 (25%) | Consistente en 2024 pero no en 2025; necesita más datos para confirmar |
| 2026-05-16 | OBSERVACIÓN | **Niveles prev_week → desactivados**: 0% WR en 2025, 14-17% en 2024 | Precio demasiado alejado del nivel para que el sweep tenga significado intradiario |
| 2026-05-16 | OBSERVACIÓN | **T2 WR sigue siendo fuerte**: 50% (2024) y 40% (2025) — ambos sobre break-even | El filtro "T1 ganó" sigue siendo válido para mejorar la calidad de T2 |
| 2026-05-16 | OBSERVACIÓN | **Bug directional corregido**: HIGH levels → solo SHORT / LOW levels → solo LONG | Bug original: prev_week_high podía generar LONG (entrada contra el concepto de barrido) |
| 2026-05-16 | DECISIÓN | V1 sigue siendo más rentable en términos absolutos por la ventaja del T2 frecuente | V2 es más selectivo (94 vs 253 trades) con menor MaxDD pero menor P&L total |

### Próximos pasos V2 (Fase 6 continuación)

| Fecha | Tipo | Descripción | Razón / Contexto |
|---|---|---|---|
| 2026-05-16 | DECISIÓN | Próximo experimento: filtrar Knockout del ciclo antes de entrar | Si se excluyen Knockout: 2024 estimado +$132 (+13%), 2025 estimado +$294 (+29%) |
| 2026-05-16 | DECISIÓN | Evaluar aumentar MIN_CONFIRMATIONS a 3 para T1 en Knockout | Alternativa a desactivar Knockout completamente |
| 2026-05-16 | DECISIÓN | Evaluar "divergence|magnets" como la combinación más fuerte de V2 (WR 44.8% en 2025) | Esta combinación superó a las 3 confirmaciones juntas en 2025 |

---

## 2026-05-16 — Filtro Knockout (V2 + FILTER_KNOCKOUT)

### Parámetro agregado

| Fecha | Tipo | Descripción | Razón / Contexto |
|---|---|---|---|
| 2026-05-16 | PARÁMETRO | `FILTER_KNOCKOUT = True` en config.py | Knockout tenía WR 9.5% (2024) y 22.5% (2025), bajo el break-even de 25%. El filtro es configurable para futuros experimentos |

### Resultados con Knockout filtrado

| Fecha | Tipo | Descripción | Razón / Contexto |
|---|---|---|---|
| 2026-05-16 | RESULTADO | V2+KO 2024: 73 trades / WR 30.1% / P&L +$148 (+14.8%) / MaxDD 9.7% | Capital $1,000 / FILTER_KNOCKOUT=True / 21 trades Knockout eliminados |
| 2026-05-16 | RESULTADO | V2+KO 2025: 52 trades / WR 38.5% / P&L +$309 (+30.9%) / MaxDD 4.9% | Capital $1,000 / FILTER_KNOCKOUT=True / 40 trades Knockout eliminados |

### Comparativa V2 vs V2+KO

| Métrica | V2 2024 | V2+KO 2024 | V2 2025 | V2+KO 2025 |
|---|---|---|---|---|
| Trades | 94 | 73 | 92 | 52 |
| WR | 25.5% | **30.1%** | 31.5% | **38.5%** |
| P&L | +$6 (+0.6%) | **+$148 (+14.8%)** | +$251 (+25.1%) | **+$309 (+30.9%)** |
| MaxDD | 20.1% | **9.7%** | 16.0% | **4.9%** |
| T1 WR | 21.0% | 24.6% | 30.9% | 39.5% |
| T2 WR | 50.0% | 54.5% | 40.0% | 37.5% |

### Hallazgos críticos por nivel de barrido (con FILTER_KNOCKOUT activo)

| Fecha | Tipo | Descripción | Razón / Contexto |
|---|---|---|---|
| 2026-05-16 | OBSERVACIÓN | **asia_high → SHORT: el mejor setup** — WR 48.3% (2024, 29 trades, +$278) y 64.7% (2025, 17 trades, +$293) | Fake breakout sobre el máximo asiático durante la sesión de Londres/NY. Patrón institucional más confiable del sistema |
| 2026-05-16 | OBSERVACIÓN | **prev_day_low → LONG: el mejor setup LONG** — WR 50.0% (2024, 12 trades, +$119) y 33.3% (2025, 6 trades, +$20) | Fake breakdown bajo el mínimo del día anterior. Funciona bien en 2024; 2025 tiene muestra pequeña (6 trades) |
| 2026-05-16 | OBSERVACIÓN | **asia_low → LONG: el peor setup** — WR 6.2% (2024, 16 trades, -$129) y 25.0% (2025, 24 trades, +$8) | Cuando el precio rompe bajo el mínimo asiático frecuentemente es una continuación bajista genuina, no un barrido fake |
| 2026-05-16 | OBSERVACIÓN | **prev_day_high → SHORT: muy débil** — WR 6.2% (2024, 16 trades, -$120) y 20.0% (2025, 5 trades, -$11) | Rotura del máximo del día anterior frecuentemente es continuación alcista, no trampa institucional |
| 2026-05-16 | OBSERVACIÓN | **El MaxDD se redujo drásticamente**: 20.1%→9.7% (2024), 16.0%→4.9% (2025) | Los días Knockout generaban rachas de pérdidas concentradas que elevaban el drawdown |

### Próximo experimento sugerido

| Fecha | Tipo | Descripción | Razón / Contexto |
|---|---|---|---|
| 2026-05-16 | DECISIÓN | Próximo experimento: filtrar `asia_low` y `prev_day_high` (solo operar `asia_high` y `prev_day_low`) | asia_low y prev_day_high tienen WR bajo o negativo en ambos años. Estimado: 2024 ~+$397 (41 trades, ~49% WR), 2025 ~+$312 (23 trades, ~57% WR) |
| 2026-05-16 | DECISIÓN | Alternativa más conservadora: mantener asia_low pero solo si MIN_CONFIRMATIONS=3 para esos setups | Reducir tamaño de muestra muy pequeño si filtramos completamente asia_low+prev_day_high en 2025 |
