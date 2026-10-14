# Conciliación de facturas y pagos con pandas: explicación completa

Este documento explica todo el proyecto `conciliacion-pagos`: para qué sirve, cómo está
organizado, qué hace cada archivo línea a línea en lo importante, qué operaciones de pandas usa
y por qué, cómo se prueba y cómo explicarlo en una entrevista.

---

## 1. Para qué sirve

Una empresa emite **facturas** a sus clientes y luego recibe **pagos**. En el mundo real esos pagos
casi nunca cuadran limpio:

- El número de factura llega escrito de mil maneras: `INV-001005`, `inv1005`, `Factura #01005`.
- A veces pagan en dos partes, a veces pagan de menos (descuentos, deducciones), a veces pagan y
  luego **revierten** el pago (un *chargeback*).
- Hay facturas en dólares, euros y dólares canadienses, con tasas de cambio que cambian cada semana.
- Hay pagos sin código de proveedor, o con una referencia que no existe.

El proyecto **cruza cada pago con su factura**, detecta qué facturas están pagadas, cuáles están
incompletas o sin pagar, y genera un reporte de **dinero recuperable**: lo que el cliente todavía
le debe al proveedor.

Es exactamente el tipo de trabajo que describe la oferta de Paired: *"reconcile Amazon claims
against invoices, purchase orders and payment records"*. También se parece a lo que haces en la
JCE: comparar un dato contra el registro oficial y señalar lo que no coincide.

---

## 2. Estructura del proyecto

```
conciliacion-pagos/
├── conciliacion/            ← el código principal (un "paquete" de Python)
│   ├── __init__.py          ← marca la carpeta como paquete
│   ├── normalize.py         ← limpieza de datos
│   ├── fx.py                ← conversión de monedas
│   ├── reconcile.py         ← cruce pagos ↔ facturas y clasificación
│   ├── report.py            ← reportes CSV y Parquet
│   └── __main__.py          ← punto de entrada: python -m conciliacion
├── scripts/
│   └── generate_sample_data.py   ← genera datos ficticios de prueba
├── data/sample/             ← los CSV generados (facturas, pagos, tasas)
├── tests/                   ← 33 pruebas con pytest
├── docs/EXPLICACION.md      ← este documento
├── README.md                ← descripción en inglés para GitHub
├── requirements.txt         ← dependencias (pandas, pyarrow, pytest)
└── pytest.ini               ← configuración de pytest
```

El flujo completo es: **datos crudos → limpieza → conversión de moneda → cruce → clasificación → reportes**.

---

## 3. Los datos

Todos los datos son **ficticios**. Los genera `scripts/generate_sample_data.py` con una semilla fija
(`SEED = 42`), así que cada vez que lo ejecutas salen exactamente los mismos datos.

### `invoices.csv` (facturas), 123 filas
| Columna | Ejemplo | Nota |
|---|---|---|
| `invoice_id` | `I0001` | identificador interno único |
| `vendor_id` | `VND-01` o `vnd-01 ` | a propósito, 10% viene en minúscula y con espacio |
| `invoice_number` | `INV-001005` | el número que aparece en la factura |
| `invoice_date` | `2026-07-15` | |
| `amount` | `"1,234.50"` | texto con coma de miles, como en un Excel exportado |
| `currency` | `USD`, `EUR`, `CAD` | |

### `payments.csv` (pagos), 127 filas
| Columna | Ejemplo | Nota |
|---|---|---|
| `payment_id` | `PAY-00001` | |
| `vendor_id` | `VND-01` o vacío | algunos pagos llegan sin código de proveedor |
| `invoice_ref` | `inv1005`, `Factura #01005` | la referencia "sucia" |
| `payment_date` | | |
| `amount` | `1234.5` o `"(1,234.50)"` | los paréntesis significan negativo (reversión) |
| `currency` | | |
| `note` | `full`, `short-paid (deduction)`… | dice qué escenario se generó; sirve para verificar |

### `fx_rates.csv` (tasas de cambio), 40 filas
Una tasa **por semana** para EUR y CAD (`rate_to_usd`: 1 EUR = 1.08 USD, por ejemplo). Es semanal a
propósito: así el programa tiene que buscar "la última tasa publicada antes de esta fecha".

### Escenarios sembrados
Para cada factura el generador elige uno de estos casos:

| Escenario | Qué genera | Resultado esperado |
|---|---|---|
| `paid` (45%) | un pago completo | `PAID` |
| `split` (12%) | dos pagos (60% + 40%) | `PAID` |
| `under` (15%) | un pago del 70% al 97% | `UNDERPAID` |
| `unpaid` (10%) | ningún pago | `UNPAID` |
| `reversed` (5%) | un pago y luego el mismo monto negativo | `REVERSED` |
| `over` (4%) | un pago del 105% | `OVERPAID` |
| `no_vendor` (9%) | pago completo sin código de proveedor | `PAID` (si el número es único) |

Además siembra 4 casos especiales:
1. **Dos proveedores con el mismo número de factura** y un pago sin proveedor → debe quedar `AMBIGUOUS`.
2. **Un pago a una factura que no existe** (`INV-999999`) → `UNMATCHED_PAYMENT`.
3. **Un pago sin referencia** → `UNMATCHED_PAYMENT`.
4. **Una factura duplicada** (exportada dos veces) → la limpieza la elimina.

---

## 4. Cada módulo explicado

### 4.1 `normalize.py`: limpieza

**`normalize_invoice_id`** convierte cualquier forma del número en una clave canónica:

1. Pasa a texto, quita espacios y convierte a mayúsculas: `" inv1005 "` → `"INV1005"`.
2. Quita el prefijo (`INVOICE`, `INV`, `FACTURA`, `FAC`, `NO`) **solo si después viene un dígito**.
   La expresión regular es `^(INVOICE|INV|FACTURA|FAC|NO)(?=[\s#.\-:]*\d)`:
   - `^` = al inicio del texto.
   - `(?=...)` es un *lookahead*: mira lo que sigue sin consumirlo.
   - `[\s#.\-:]*\d` = cero o más separadores y luego un dígito.
   - Así `INV1005` pierde `INV`, pero `NORTH-12` conserva `NORTH` (no es un prefijo, es parte del id).
3. Borra todo lo que no sea letra o número: `"#01005"` → `"01005"`.
4. Quita los ceros a la izquierda: `"01005"` → `"1005"`.
5. Si no queda nada, devuelve `None` (no inventa un id).

> **Error real que se encontró al construirlo:** la primera versión usaba `\b` (límite de palabra)
> en vez del lookahead. Entre la `V` y el `1` de `inv1005` no hay límite de palabra, así que el
> prefijo no se quitaba y 26 pagos quedaban sin cruzar en vez de 3. Las pruebas ahora cubren ese caso.

**`normalize_vendor_id`**: mayúsculas y sin espacios (`" vnd-01 "` → `"VND-01"`).

**`parse_amount`**: convierte texto a número:
- `"1,234.50"` → `1234.5` (quita la coma de miles).
- `"$ 99.90"` → `99.9`.
- `"(25.00)"` → `-25.0` (en contabilidad, los paréntesis significan negativo).

**`clean_invoices` / `clean_payments`** aplican esas funciones a cada columna con `.map()`,
convierten las fechas con `pd.to_datetime` y, en facturas, eliminan duplicados exactos con
`drop_duplicates(subset=[...])`.

### 4.2 `fx.py`: conversión de monedas

**`to_usd(df, rates, date_col)`** agrega dos columnas: `rate_to_usd` y `amount_usd`.

La clave es **`pd.merge_asof`**: un *join* por fecha aproximada. Para cada fila busca la tasa con
la fecha más reciente que sea **menor o igual** a la fecha de la fila (`direction="backward"`),
y solo dentro de la misma moneda (`by="currency"`).

Ejemplo: tasas EUR el 1 y el 8 de agosto. Un pago del 5 de agosto usa la del 1; uno del 8 usa la del 8.

Detalles:
- `merge_asof` exige que ambas tablas estén **ordenadas por fecha**. Por eso se ordena y luego se
  recupera el orden original con una columna auxiliar `_row`.
- Las filas en USD no necesitan buscar tasa: se les pone `1.0`.
- Si no hay tasa anterior, el resultado queda `NaN` y `__main__.py` detiene el programa con un
  mensaje. **Nunca se adivina una tasa.**

### 4.3 `reconcile.py`: el corazón del proyecto

#### `assign_payments`: a qué factura pertenece cada pago

Reglas, en orden:
1. Si el pago **tiene proveedor**, se cruza por `(vendor_id, invoice_key)`.
2. Si **no tiene proveedor**, se cruza solo por `invoice_key`, **pero solo si exactamente una
   factura tiene esa clave**.
3. Si nada coincide → `UNMATCHED_PAYMENT`. Si coinciden varias → `AMBIGUOUS`.

La función interna `match_on` hace el trabajo con un truco importante: **cuenta los candidatos
antes de unir**. Con un `merge` normal, si dos facturas comparten la clave, el pago se duplicaría
(una fila por cada factura) y **el dinero se contaría dos veces**. En cambio:
1. `keys.groupby(on).size()` cuenta cuántas facturas tiene cada clave.
2. Solo las claves con exactamente 1 candidato se unen para obtener el `invoice_id`.
3. El pago queda `MATCHED`, `UNMATCHED_PAYMENT` (0 candidatos) o `AMBIGUOUS` (2 o más).

Otro detalle: **pandas une los valores vacíos (`NaN`) entre sí** en un `merge`. Por eso las facturas
sin número válido se excluyen como candidatas (`dropna(subset=["invoice_key"])`).

**¿Por qué no adivinar en los casos ambiguos?** Porque si asignas un pago a la factura equivocada,
esa factura aparece como pagada y **escondes una deuda real**. En recuperación de dinero, un cruce
equivocado es peor que ningún cruce. Es la misma lógica que pide la oferta: *"avoiding
unsupported or ambiguous matches"*.

#### `classify_invoices`: el estado de cada factura

1. Toma solo los pagos `MATCHED`.
2. **Compara en la moneda de la factura**, no en USD. ¿Por qué? Una factura de 100 EUR emitida
   cuando el euro valía 1.10 USD, pagada con 100 EUR cuando valía 1.05 USD, **está pagada completa**.
   Si convirtieras ambas cosas a USD en fechas distintas, saldría un "faltante" de 5 USD que no
   existe. (Este error estaba en el diseño inicial y se corrigió antes de ejecutar nada; hay una
   prueba para ello.)
3. Si un pago viene en otra moneda, se convierte a la moneda de la factura pasando por USD.
4. `groupby("invoice_id").agg(...)` suma lo pagado, cuenta los pagos y cuenta las reversiones
   (montos negativos).
5. Calcula `gap` = facturado − pagado, y sus versiones en USD para reportar.
6. Asigna el estado:

| Estado | Condición |
|---|---|
| `UNPAID` | ningún pago |
| `REVERSED` | hubo reversión y lo pagado neto es ~0 |
| `PAID` | la diferencia está dentro de ±0.01 |
| `UNDERPAID` | diferencia positiva (pagaron de menos) |
| `OVERPAID` | diferencia negativa (pagaron de más) |

7. `recoverable_usd`: solo cuenta como recuperable lo que se le debe al proveedor
   (`UNDERPAID`, `UNPAID`, `REVERSED`). Un sobrepago no es dinero a recuperar.

### 4.4 `report.py`: los reportes

- **`summary_by_vendor`**: una fila por proveedor con cuántas facturas hay en cada estado
  (`pd.crosstab`) y los totales facturado, pagado y recuperable (`groupby().agg()`), ordenado de
  mayor a menor recuperable.
- **`write_reports`** escribe 5 archivos en `output/`:

| Archivo | Para quién |
|---|---|
| `recovery_claims.csv` | las facturas con dinero recuperable, de mayor a menor: la lista de trabajo |
| `vendor_summary.csv` | el resumen por proveedor, para un cliente no técnico |
| `payment_exceptions.csv` | pagos que no se pudieron asignar: requieren revisión humana |
| `invoice_results.csv` | todas las facturas con su estado |
| `invoice_results.parquet` | lo mismo en Parquet (formato columnar, más rápido para millones de filas) |

### 4.5 `__main__.py`: cómo se ejecuta todo

`python -m conciliacion --data data/sample --out output` hace:
1. Lee los CSV con `dtype=str` (todo como texto, para que pandas no "adivine" tipos y, por
   ejemplo, convierta `001005` en `1005` antes de tiempo).
2. Limpia, convierte a USD y verifica que no falten tasas.
3. Concilia y escribe los reportes.
4. Imprime un resumen en pantalla.

---

## 5. Las pruebas (33 con pytest)

| Archivo | Qué prueba |
|---|---|
| `test_normalize.py` (19) | 11 formas de escribir un número de factura (incluido `inv1005` y `NORTH-12`), proveedores, montos con comas, `$` y paréntesis, y eliminación de duplicados |
| `test_fx.py` (3) | que use la última tasa anterior, que conserve el orden y que una tasa faltante quede visible |
| `test_reconcile.py` (8) | cada uno de los 6 estados, el número compartido entre proveedores, el caso ambiguo (no se adivina), pagos sin proveedor, referencias desconocidas, que la variación de tasa no cuente como faltante, pagos en otra moneda y **conservación del dinero** (pagado + diferencia = facturado) |
| `test_end_to_end.py` (3) | ejecuta todo con los datos de ejemplo y verifica que los conteos coincidan **exactamente** con los escenarios sembrados por el generador |

**`@pytest.mark.parametrize`** permite escribir una prueba y ejecutarla con muchos datos distintos.
**Las fixtures** (`@pytest.fixture`) preparan algo una sola vez y lo reutilizan: aquí, ejecutar el
pipeline completo en una carpeta temporal (`tmp_path_factory`).

**Se comprobó que las pruebas detectan errores:** al reintroducir a propósito el error del prefijo,
4 pruebas fallaron. Con el código correcto, las 33 pasan.

### Resultado con los datos de ejemplo
```
Invoices: 122  |  Payment exceptions: 3
PAID 71 | UNPAID 21 | UNDERPAID 15 | REVERSED 9 | OVERPAID 6
Recoverable: USD 61,768.69
```
Verificación contra lo sembrado: 71 pagadas = 50 completas + 14 en dos partes + 7 sin proveedor;
15 incompletas, 9 revertidas y 6 sobrepagadas coinciden exactamente; y las 3 excepciones son
justo las 3 sembradas.

---

## 6. Operaciones de pandas usadas (para la pregunta del formulario)

| Operación | Dónde | Para qué |
|---|---|---|
| `read_csv(dtype=str)` | `__main__.py` | leer sin que pandas cambie los datos |
| `.map(func)` | `normalize.py` | aplicar una función de limpieza a cada valor |
| `.str.strip().str.upper()` | `normalize.py`, `fx.py` | limpiar texto en toda una columna |
| `pd.to_datetime` | `normalize.py` | convertir texto a fechas |
| `drop_duplicates(subset=...)` | `normalize.py` | quitar filas repetidas |
| `merge(how="left")` | `reconcile.py` | unir pagos con facturas |
| `merge_asof(by=, direction="backward")` | `fx.py` | unir por fecha aproximada |
| `groupby().size()` | `reconcile.py` | contar candidatos por clave |
| `groupby().agg(nombre=(col, func))` | `reconcile.py`, `report.py` | sumar y contar por factura o proveedor |
| `where` | `reconcile.py` | elegir un valor u otro según una condición |
| filtros booleanos `df[df[col] > 0]` | varios | filtrar filas |
| `pd.crosstab` | `report.py` | tabla de conteos proveedor × estado |
| `value_counts` | `__main__.py` | contar estados |
| `sort_values`, `concat`, `fillna`, `round` | varios | ordenar, combinar, rellenar y redondear |
| `to_csv`, `to_parquet` | `report.py` | escribir resultados |

---

## 7. Cómo explicarlo en una entrevista

**En 30 segundos (en inglés):**
> "I built a small reconciliation tool in Python and pandas. It cleans messy invoice references,
> converts currencies with the rate in force on each date using merge_asof, matches payments to
> invoices, and classifies each invoice as paid, underpaid, unpaid, reversed or overpaid. The key
> design decision is that it never guesses: if a payment could belong to two invoices, it flags it
> as ambiguous instead of matching it, because a wrong match would hide money the client is owed.
> It has 33 pytest tests, including an end-to-end test that checks the results against the
> scenarios I planted in the sample data."

**Preguntas probables y cómo responder:**

1. **"Why compare in the invoice currency and not in USD?"**
   Because the exchange rate changes between the invoice date and the payment date. If you
   convert both to USD on different dates, a correct payment looks short. You compare in the
   currency of the debt and convert to USD only to report.

2. **"What happens if two invoices have the same number?"**
   If the payment has a vendor code, it's matched by vendor plus number. If not, and more than one
   invoice has that number, it goes to the exceptions file as AMBIGUOUS for a human to review.

3. **"How would this scale to millions of rows?"**
   Everything is vectorized pandas (merge, groupby), not Python loops, except the status function,
   which could be rewritten with `numpy.select`. For very large files I would read Parquet instead
   of CSV and only load the needed columns.

4. **"How do you know it's correct?"**
   Unit tests for each rule, a money-conservation test (paid plus gap equals invoiced), and an
   end-to-end test on generated data where I know the right answer for every invoice.

5. **"Did you use AI?"**
   Yes, I built it with Claude Code. Sé honesto y explica que revisaste cada regla, entiendes cada
   decisión y que las pruebas lo verifican. **Antes de cualquier entrevista, ejecuta el proyecto
   tú mismo y lee cada archivo hasta que puedas explicar cada línea sin mirar este documento.**

---

## 8. Cómo ejecutarlo tú mismo

```bash
cd C:\Users\willi\Code\conciliacion-pagos
.venv\Scripts\activate
python scripts/generate_sample_data.py
python -m conciliacion --data data/sample --out output
python -m pytest -v
```

Ejercicios para dominarlo (recomendado antes de una entrevista):
1. Cambia `SEED = 42` por otro número, regenera los datos y verifica que las pruebas siguen pasando.
2. Agrega una moneda nueva (por ejemplo `DOP`) al generador y a las tasas.
3. Agrega un estado nuevo, `PARTIAL_REVERSAL`, para reversiones que no llegan a cero, con su prueba.
4. Reescribe la función `status` con `numpy.select` en vez de `apply`.

---

## 9. Cómo usarlo con Paired

Ya enviaste la solicitud a Paired respondiendo con honestidad que no habías usado pandas ni pytest
en proyectos reales. Si te contactan, este proyecto te permite decir con hechos:

- Qué operaciones de pandas has usado: `merge`, `merge_asof`, `groupby` + `agg`, `crosstab`,
  filtros, `drop_duplicates`, `to_parquet` (sección 6).
- Qué framework de pruebas usas con Python: **pytest**, con `parametrize` y fixtures.
- Un repositorio de GitHub con un proyecto de datos en Python (cuando lo publiques).

Úsalo solo para lo que es: un proyecto personal de práctica con datos ficticios.
