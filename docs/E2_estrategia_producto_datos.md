# E2. Estrategia y Producto de Datos

**Propuesta al Comité de Dirección — Área de Datos**
**Fecha:** Septiembre 2026 | **Autor:** Adrian Villalba

---

## 0. Tratamiento de datos realizado

Antes de calcular cualquier métrica, se realizó un proceso riguroso de preparación de datos sobre la extracción piloto de las tres IPS. Sin este tratamiento, las cifras no serían confiables.

**Problema de partida:** Las tres IPS entregan datos con esquemas diferentes (nombres de columnas, separadores CSV, códigos de estado, formato de fechas). Además, los datos presentan 9 problemas de calidad.

**Tratamiento en 3 capas:**

1. **Capa cruda (raw):** Archivos originales sin modificación, como respaldo y trazabilidad.
2. **Capa limpia (clean):** Homologación a 21 columnas canónicas, traducción de estados abreviados, eliminación de datos personales de IPS Sur (Ley 1581/2012), corrección de 274 edades anómalas, eliminación de 198 duplicados en Norte, y marcado de 67 citas futuras con estado terminal.
3. **Capa de consumo:** Cruce con eventos de WhatsApp, cálculo de métricas de ausentismo y modelo dimensional (fact_citas + dimensiones) listo para análisis.

**Por qué importa:** Sin este tratamiento, el ausentismo se calcularía sobre datos con duplicados, edades imposibles y citas futuras marcadas como atendidas, produciendo una cifra incorrecta para decisiones.

---

## 1. Definición unificada de ausentismo

### La cifra: 15.8%

El ausentismo real consolidado de las tres IPS piloto es **15.8%**, calculado como:

```
Tasa de ausentismo = NO_ASISTIO / (ATENDIDA + NO_ASISTIO)
```

| IPS | NO_ASISTIO | Citas efectivas | Ausentismo |
|-----|-----------|----------------|------------|
| Norte | 722 | 4,892 | 14.8% |
| Sur | 722 | 4,051 | **17.8%** |
| Occidente | 478 | 3,223 | 14.8% |
| **Total** | **1,922** | **12,166** | **15.8%** |

### Por qué Comercial y Operaciones reportan cifras distintas

La discrepancia no es un error de cálculo. Es una diferencia de definición del denominador:

- **Operaciones (15-17%):** usa solo citas que debían ocurrir (ATENDIDA + NO_ASISTIO). Es la medición correcta.
- **Comercial (12-14%):** incluye cancelaciones en el denominador. Al agregar 1,845 cancelaciones, el denominador crece de 12,166 a 14,011, diluyendo la tasa a 13.7%.

Un paciente que cancela libera la agenda; uno que no llega la desperdicia. Son problemas distintos que requieren intervenciones distintas.

### Tratamiento del estado REAGENDADA

En los datos aparecen 897 citas (5.7%) con estado REAGENDADA, no documentado en el diccionario. Distribución: Norte 357 (5.6%), Sur 312 (5.9%), Occidente 228 (5.4%).

**Decisión:** Excluir del cálculo de ausentismo, igual que CANCELADA. Una cita reagendada no es inasistencia: el paciente tomó acción antes de la fecha. Sin embargo, es señal de riesgo para la cita reprogramada.

**Problema abierto:** Ninguna de las 897 tiene referencia a la cita original (cita_origen_id vacío). Debe resolverse con TI.

### Gobernanza de la definición

1. **Definición única documentada** en glosario versionado, con fórmula, exclusiones y ejemplos.
2. **Cálculo centralizado**: solo en la capa de consumo. Ningún área calcula desde bases transaccionales.
3. **Una sola fuente de verdad**: todos los reportes consumen fact_citas con columnas precalculadas.
4. **Revisión trimestral** por comité de datos. Cambios se versionan con fecha efectiva.

---

## 2. Posición sobre los servicios propuestos por Comercial

En el acta del comité, Dirección Comercial propuso dos servicios nuevos basados en los datos de ausentismo. Ambos buscan generar ingresos vendiendo inteligencia a IPS y EPS. Se analiza cada uno desde datos, viabilidad legal y ética.

### Servicio 1: Benchmark entre IPS — Lanzar con rediseño

**Propuesta de Comercial:** Que cada IPS cliente vea su ausentismo comparado con las demás del portafolio (ej.: una IPS con 17.8% ve que otras están en 14.8%).

**Cómo se calcularía:** Tasa unificada de la capa de consumo. Cada IPS ve su percentil segmentado por especialidad, horario o mes. Solo indicadores agregados, nunca datos de pacientes entre clientes.

**Rediseño necesario:** Comparar solo IPS con perfil similar (tamaño, especialidades, zona). La IPS ve su posición pero no la identidad de las demás.

**Riesgo legal:** Bajo (solo datos agregados). **Riesgo ético:** Medio (mitigar con variables de contexto).

**Acción:** Diseñar con pares comparables en mes 2, validar legalmente, lanzar mes 3.

### Servicio 2: Informe a EPS con pacientes de alto riesgo — No lanzar

**Propuesta de Comercial:** Enviar a las EPS un listado mensual de pacientes con alta probabilidad de inasistencia. Según Comercial, "las EPS ya mostraron interés en pagar" por esta información.

**Qué implicaría:** Modelo predictivo + compartir nombre, documento y score de riesgo de pacientes con citas próximas. La EPS contactaría o reprogramaría a los señalados.

**Riesgo legal — ALTO:** Tratamiento de datos sensibles (Ley 1581/2012, Ley 1751/2015). Requiere autorización expresa de cada paciente y base jurídica clara. El interés comercial no es suficiente.

**Riesgo ético — ALTO:** Los factores de riesgo correlacionan con vulnerabilidad socioeconómica. Si la EPS restringe servicios, DonDoctor sería corresponsable.

**Alternativa:** Informe agregado por zona, horario y especialidad, sin identificar individuos. Evaluar en mes 3.

---

## 3. Producto de datos que priorizaría

### Tablero operacional de gestión de ausentismo

**Qué es:** Dashboard con actualización diaria para directores de operaciones. Los datos del piloto muestran palancas accionables:

| Factor | Ausentismo | Diferencia |
|--------|-----------|------------|
| Con recordatorio WhatsApp | 11.2% | — |
| Sin recordatorio WhatsApp | 20.2% | **9.0 pp** |
| Psicología | 24.6% | Especialidad más alta |
| Cardiología | 9.6% | Especialidad más baja |
| Lunes | 17.3% | Día más alto |
| Jueves | 14.1% | Día más bajo |

El recordatorio por WhatsApp reduce el ausentismo en 9 pp. El primer paso no es un modelo predictivo complejo sino asegurar que el 100% de las citas tengan recordatorio (hoy solo el 49%).

### Efecto del recordatorio por IPS

El impacto no es uniforme. Sur es la que más se beneficia y la que tiene peor cobertura:

| IPS | Con WhatsApp | Sin WhatsApp | Reducción | Cobertura actual |
|-----|-------------|-------------|-----------|-----------------|
| Norte | 10.3% | 19.1% | 8.8 pp | 49.4% |
| **Sur** | **12.5%** | **22.8%** | **10.2 pp** | **48.4%** |
| Occidente | 10.9% | 18.7% | 7.8 pp | 49.6% |

Sur tiene el ausentismo más alto (17.8%) y el mayor margen de mejora (10.2 pp). Si se lleva la cobertura al 90%, podría bajar a 13-14%. Mayor impacto con menor esfuerzo.

**Validación:** Prototipo en 2 semanas. Medir consultas (>=3/semana) y acciones concretas.

**Éxito:** Adopción >=80% semanal, reducción >=2pp a 90 días, cobertura WhatsApp del 49% al 90%.

---

## 4. Sobre la solicitud de tiempo real

**Recomendación: no implementar tiempo real ahora.**

El ausentismo se gestiona con anticipación (horas o días antes), no en segundos. Un recordatorio 24h antes es efectivo; uno 5 minutos antes no cambia la decisión.

1. **Costo:** Streaming cuesta 3-5x más que batch diario, sin beneficio proporcional.
2. **Madurez:** Streaming antes de batch estable es construir el segundo piso sin cimientos.
3. **Cuándo sí:** Cuando se integren confirmaciones en tiempo real y reasignación automática de slots.

**Propuesta:** Batch diario en fase 1 (meses 1-3). Evaluar micro-batch en fase 2.

---

## 5. Impacto económico del ausentismo

Una vez definida la métrica y las intervenciones, el comité necesita dimensionar el problema en términos financieros. Las tres IPS registraron 1,922 inasistencias: cada una es una hora de agenda médica perdida (médico disponible, consultorio ocupado, paciente ausente).

### Costo estimado de la inasistencia

Valor promedio de consulta: $60,000 COP (rango: $50,000 - $80,000 según especialidad).

| IPS | Inasistencias | Costo estimado perdido |
|-----|--------------|----------------------|
| Norte | 722 | $43,320,000 COP |
| Sur | 722 | $43,320,000 COP |
| Occidente | 478 | $28,680,000 COP |
| **Total** | **1,922** | **$115,320,000 COP** |

Más de $115 millones en agenda desperdiciada, solo en 3 IPS y un año. Escalado a toda la base de clientes, el costo se multiplica.

### Cuánto se puede recuperar

El recordatorio WhatsApp reduce el ausentismo en 9 pp (de 20.2% a 11.2%). Hoy solo el 49% de las citas lo reciben. Llevando la cobertura al 90% se evitarían ~450 inasistencias adicionales, equivalentes a ~$27 millones COP recuperados. La inversión adicional es prácticamente cero: la infraestructura ya existe.

**En resumen:** $115M COP perdidos al año en 3 IPS. ~$27M recuperables sin costo adicional.

---

## 6. Hoja de ruta — 90 días

### Mes 1: Cimientos (semanas 1-4)

| Semana | Entregable | Indicador |
|--------|-----------|-----------|
| 1-2 | Data warehouse en Fabric: capas raw, clean, consumo. Pipeline batch diario. | Sin errores 5 días seguidos |
| 3 | Definición de ausentismo aprobada. Glosario publicado. | Firmado por Comercial y Operaciones |
| 4 | Prototipo tablero operacional con datos reales. | Presentado a 2 directores |

### Mes 2: Validación (semanas 5-8)

| Semana | Entregable | Indicador |
|--------|-----------|-----------|
| 5-6 | Tablero en producción. Alertas de cobertura. | >=2 IPS consultando semanalmente |
| 7 | Benchmark v1 (pares y métricas agregadas). | Revisión legal aprobada |
| 8 | Modelo predictivo v1 validado. | AUC >= 0.70 en validación temporal |

### Mes 3: Escalamiento (semanas 9-12)

| Semana | Entregable | Indicador |
|--------|-----------|-----------|
| 9-10 | Onboarding de 2 IPS adicionales. Seguridad multi-cliente. | 5 IPS en el warehouse |
| 11 | Benchmark lanzado para clientes piloto. | >=3 IPS usando benchmark |
| 12 | Revisión de resultados. Decisión go/no-go servicio EPS. | Reducción >=2pp en ausentismo |

### KPIs de la función de datos

| Indicador | Meta | Cómo se mide |
|-----------|------|-------------|
| Ausentismo consolidado | Reducción >=2pp | fact_citas, cálculo mensual |
| Cobertura de recordatorios | >=90% con WhatsApp | fact_citas.wa_enviado |
| Adopción del tablero | >=80% uso semanal | Logs de acceso |
| Confiabilidad del pipeline | >=99% ejecuciones OK | Monitoreo de orquestador |
| Onboarding nueva IPS | <=5 días hábiles | Desde acceso hasta consumo |

---

## Resumen de decisiones para el comité

| Solicitud | Recomendación | Acción inmediata |
|-----------|--------------|-----------------|
| Cifra única de ausentismo | 15.8% con fórmula estandarizada | Aprobar definición (semana 3) |
| Benchmark entre IPS | Lanzar con rediseño | Diseño mes 2, lanzamiento mes 3 |
| Informe EPS con pacientes | No lanzar. Riesgo legal alto | Rediseñar como informe agregado |
| Tiempo real | No ahora. Batch diario | Pipeline batch mes 1 |
| Impacto económico | $115M perdidos, ~$27M recuperables | Cobertura WhatsApp al 90% |
| Producto prioritario | Tablero operacional | Prototipo semana 4 |
