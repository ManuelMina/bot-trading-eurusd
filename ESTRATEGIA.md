# Estrategia de Trading — Documentación Completa

> Basada en las clases 3, 4, 5 y 6 del curso de trading.  
> Última actualización: 2026-05-11  
> Todos los cambios quedan registrados en [CHANGELOG.md](CHANGELOG.md)

---

## Filosofía base

- Somos **traders que reaccionan**, no que predicen.
- El mercado es un **juego de caza**: está diseñado para atrapar compradores y vendedores antes de hacer el movimiento real.
- **"Lo que no puedo controlar, no lo puedo monetizar."** Si el escenario no encaja en los ciclos estudiados, no se opera.
- Nunca dejar variables al azar. Todo trade necesita contexto validado.

---

## Los 4 Pasos del Trade (proceso obligatorio antes de cada entrada)

1. **Identificar Liquidez** — ¿Dónde está el dinero? (Asia range, dobles techos/pisos, líneas de tendencia, mínimos/máximos iguales)
2. **Ubicación en el Ciclo** — ¿En qué fase estamos? (Buildup → Inducción → Mitigación)
3. **Buscar la Inducción** — Esperar el movimiento falso que saca a los participantes
4. **Confirmación** — Validar con las herramientas definidas antes de entrar

---

## Estructura del Ciclo

Cada movimiento del mercado sigue siempre la misma secuencia fractal:

```
BUILDUP (acumulación)
    ↓
INDUCCIÓN (movimiento falso / trampa)
    ↓
MITIGACIÓN (relleno de imbalances, punto de entrada)
    ↓
DISTRIBUCIÓN (movimiento real hacia el objetivo)
```

- El ciclo se repite en **todas las temporalidades** (fractal). Lo que pasa en M1 es lo mismo que en H4 o Diario.
- Cada ciclo tiene micro-ciclos adentro (canales que sacan por arriba y por abajo).
- Un canal = buildup → siempre saca por arriba Y por abajo antes de continuar.

---

## Rango Asiático

- **Horario:** 19:00 – 00:00 hora Colombia (UTC-5) = 00:00 – 05:00 UTC
- Forma el High y Low del día desde el cual se van a "cazar" compradores y vendedores.
- El mercado **siempre** va a intentar tocar ambos lados del rango asiático (salvo en ciclos especiales).
- La estrategia retail de "operar la ruptura del rango" es una trampa: el precio rompe para atrapar y luego se revierte.

---

## Tipos de Ciclo Diario

### 1. Ciclo Normal
- El precio saca liquidez **por arriba Y por abajo** del rango de Asia durante la sesión.
- Es el ciclo más común y predecible.
- Permite operar en ambas direcciones si se identifica correctamente la inducción.

### 2. London Knockout
- Londres saca **UN solo lado** del rango de Asia y el precio **sigue en esa dirección casi infinitamente** sin regresar.
- Señal clave: hay una meta lejana en la dirección del movimiento (liquidez mayor sin recolectar).
- En este ciclo NO se espera reversión; se opera en la dirección del knockout.

### 3. Retail Heaven (Paraíso Retail)
- El mercado deja una tendencia clara y "bonita" con liquidez abierta en un lado (como un canal).
- Esa liquidez abierta **debe ser recolectada** próximamente.
- Se puede operar buscando que el precio vaya a recolectar esa liquidez pendiente.

### 4. La Sierra
- Movimiento **errático y fuerte** en ambas direcciones, diseñado para confundir y sacar a todos.
- **Regla de operación en Sierra:**
  1. Identificar los límites del rango errático (el High y Low de la zona Sierra).
  2. Esperar que el precio **barra (sweep)** por encima del límite superior O por debajo del límite inferior.
  3. El sweep se confirma cuando el precio supera el límite por al menos **3 pips** (parámetro: `SIERRA_SWEEP_PIPS`, ajustable en backtesting).
  4. Una vez confirmado el barrido (precio superó el límite y empieza a retroceder):
     - Buscar **vela de fuerza** en dirección contraria al barrido.
     - Entrar buscando que el precio vaya a barrer la **zona contraria** del rango.
  5. El objetivo es el lado opuesto del rango Sierra.
  6. **No operar el interior del rango Sierra** — solo los extremos.

---

## Herramientas de Confirmación (en orden de prioridad)

### 1. Divergencia Completa EURUSD / GBPUSD
- Comparar ambos pares en la misma ventana de tiempo.
- Si **EURUSD hace un nuevo máximo/mínimo** y **GBPUSD NO lo acompaña** (o viceversa) → el par que indujo se **alejará con fuerza**.
- El que indujo = el que hizo el nuevo extremo sin ser correspondido.
- Operar el par que tenga mejor configuración (preferentemente EURUSD).
- **Es la confirmación más confiable según el profesor.**

### 2. Teoría de Cuartos
- El día se divide en **4 bloques de 6 horas** (00:00, 06:00, 12:00, 18:00 hora NY).
- Confirmación: el cuarto actual **saca el máximo o mínimo del cuarto anterior** → señal de inducción.
- Si el cuarto verde (actual) supera el máximo del cuarto rojo (anterior) → inducción confirmada hacia abajo.
- Si el cuarto verde supera el mínimo del cuarto rojo → inducción confirmada hacia arriba.

### 3. Aperturas como Magnetos
Dos niveles clave que actúan como imanes:

| Apertura | Hora Colombia | Hora NY | Regla |
|---|---|---|---|
| Cierre Asia / Apertura 00:00 | 00:00 (invierno) / 23:00 (verano) | 00:00 NY | Precio arriba = vender; precio abajo = comprar |
| Pre-apertura NY | 07:30 (invierno) / 06:30 (verano) | 07:30 NY | Precio arriba = vender; precio abajo = comprar |

- **Nota sobre DST:** Colombia es siempre UTC-5. NY es UTC-5 (invierno/EST) y UTC-4 (verano/EDT). Ajustar en los meses de marzo a noviembre.
- La regla puede ejecutarse directamente O después de que el precio primero induzca el lado contrario.

---

## Detección de Inducción (programable)

```
1. Precio viaja en dirección X (tendencia corto plazo definida)
2. Precio retrocede en contra (contra-tendencia) hacia un nivel clave (swing high/low)
3. Precio llega cercano o rompe ligeramente ese nivel (el "barrido" de la inducción)
4. Precio regresa a la dirección X original
5. El punto tocado = NIVEL DE INDUCCIÓN (SL va justo afuera de ese punto)
```

---

## Trampas y Conceptos de Ejecución

### Smart Money Trap (SMT)
- Zona que parece obvia como punto de rebote pero que el mercado usa para atrapar participantes.
- Si el precio llega a una "mitigación válida" con mucha gente comprando al mismo tiempo → es probablemente una trampa.
- La señal real viene después de que el precio saca esa zona.

### FFS (Force Full Swing)
- Vela o movimiento de **mucha fuerza** que rompe un nivel clave y mete a muchos traders en la dirección errónea.
- Diferencia con SMT: el FFS rompe con velocidad y fuerza extrema (no suavemente).
- Después de un FFS, buscar el movimiento contrario hacia la liquidez opuesta.
- Siempre buscar excusa en el lado contrario (liquidez, altos/bajos iguales) antes de entrar.

### Final Blow / Agotamiento
- Vela(s) de gran tamaño y volumen al **final** de un movimiento.
- Indica que el mercado atrapó suficientes personas y está por revertir.
- No entrar en la dirección de esas velas de agotamiento: esperar la reversión.

### Jerarquía de Temporalidades
- Las inducciones en temporalidades **mayores** (H4, Diario) mandan sobre las menores (M5, M1).
- Si en H4 hay una inducción alcista y en M15 hay una señal bajista → el M15 está equivocado.
- Siempre leer de mayor a menor: Diario → H4 → H1 → M15 → M5 → M1.

---

## Parámetros de Gestión de Riesgo

| Parámetro | Valor |
|---|---|
| Capital de prueba | $1,000 |
| Riesgo por trade | 1% ($10) |
| Take Profit | Fijo 1:3 |
| Stop Loss | Extremo vela de inducción ± 2-3 pips |
| Entrada (trigger) | Vela de fuerza en M1 (cuerpo > cuerpo vela anterior) |
| Temporalidad análisis | M5 |
| Temporalidad entrada | M1 |

---

## Horario Operativo

| Sesión | Hora Colombia | Hora NY | Notas |
|---|---|---|---|
| Rango Asia | 19:00 – 00:00 | 20:00 – 01:00 (invierno) | Calcular High/Low del día |
| Apertura Londres | 02:00 | 03:00 | Minutos mágicos: 03:30 y 04:30 Col |
| Pre-apertura NY | 07:00 | 07:00* | Empezar a monitorear |
| Apertura magneto #2 | 07:30 | 07:30* | Nivel magneto |
| Ventana operativa | **07:00 – 10:00** | **08:00 – 11:00** | Única ventana activa |
| Cierre Londres | 10:00 | 11:00 | Fin de ventana |

*Ajustar 1 hora en verano (EDT, marzo–noviembre).

**Días operativos:** Lunes a Viernes, excluyendo festivos de Nueva York.

---

## Instrumentos

| Par | Uso |
|---|---|
| EURUSD | Análisis principal + entradas (90% de los trades) |
| GBPUSD | Análisis de divergencias completas (confirmación) |

---

## Backtesting

- **2024:** Período completo (enero 2024 – diciembre 2024)
- **2025:** Período completo (enero 2025 – diciembre 2025)
- Se generan reportes separados por año para comparar comportamiento.

---

## Gestión de Trades por Día

### Árbol de decisiones diario

```
INICIO DEL DÍA (07:00 Colombia)
        │
        ▼
   ¿Aparece setup válido?
    NO → esperar / fin de ventana
    SÍ → ejecutar TRADE 1
        │
        ├── TRADE 1 PIERDE ──────────────────→ FIN DEL DÍA ✗
        │
        └── TRADE 1 GANA
                │
                ▼
           ¿Aparece setup válido?
            NO → fin de ventana (1 trade ganado)
            SÍ → ejecutar TRADE 2
                │
                ├── TRADE 2 PIERDE ──────────→ FIN DEL DÍA ✓✗
                │
                └── TRADE 2 GANA
                        │
                        ▼
                   ¿Setup de EXCELENCIA?
                    NO → FIN DEL DÍA ✓✓
                    SÍ → ejecutar TRADE 3 (único posible)
                            │
                            └── Resultado → FIN DEL DÍA ✓✓✓ o ✓✓✗
```

### Condiciones de EXCELENCIA para el Trade 3

El trade 3 solo se habilita si **todas** las siguientes condiciones se cumplen simultáneamente:

| Condición | Descripción |
|---|---|
| T1 y T2 ganados | Ambos trades anteriores del día terminaron en TP |
| Ciclo identificado | El ciclo del día está claramente clasificado (no Sierra ambigua) |
| 3 confirmaciones activas | Divergencia + Cuartos + Apertura magneto alineadas al mismo tiempo |
| Inducción limpia | El precio tocó el nivel de inducción con precisión (no aproximación) |
| Vela de fuerza destacada | El cuerpo de la vela de entrada es ≥ 1.5× el promedio de las últimas 10 velas |
| Dentro de ventana | La entrada ocurre antes de las 09:30 Colombia (media hora antes del cierre) |

### Principio
- El sistema prioriza **calidad sobre cantidad**.
- 2 trades bien seleccionados por día son suficientes para rentabilidad consistente.
- El 3er trade es excepcional, no la norma.
- Nunca operar por FOMO ni para recuperar pérdidas del día.

### Protocolo de ajuste del T3
Si el backtesting muestra que el T3 tiene **win rate negativo o inferior al T1/T2**, se deben revisar y endurecer las condiciones de excelencia antes de continuar. Posibles ajustes a evaluar en orden:

1. Subir el multiplicador de vela de fuerza (`EXCELLENCE_BODY_MULT`: 1.5 → 2.0)
2. Exigir que la divergencia sea en **ambas temporalidades** (M5 y M1 simultáneamente)
3. Reducir la ventana de entrada a antes de 09:00 Colombia en lugar de 09:30
4. Requerir que el ciclo sea estrictamente **Normal** (excluir Retail Heaven y Knockout del T3)
5. Deshabilitar el T3 completamente si ningún ajuste mejora el resultado

Cada ajuste se documenta en `CHANGELOG.md` con tipo `PARÁMETRO` y el resultado que lo motivó.

---

## Reglas de Oro

1. Solo operar dentro de la ventana 07:00–10:00 Colombia.
2. Si el ciclo del día no está identificado, no operar.
3. Al menos 2 confirmaciones deben alinearse antes de entrar.
4. Si el escenario no encaja en los 4 pasos → no entrar.
5. Las pérdidas son parte del negocio; lo que importa es la consistencia del proceso.
