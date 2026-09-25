# E3. Arquitectura Objetivo en Azure y Fabric

**Documento de decisiones — Área de Datos**
**Fecha:** Septiembre 2026 | **Autor:** Adrian Villalba

---

## 1. Ingesta sin afectar la operación

Cada IPS tiene su base SQL Server transaccional; los eventos de WhatsApp están en MongoDB. La ingesta no puede degradar el sistema de citas en producción.

**SQL Server (citas por IPS):**

- **Data Pipeline de Fabric** con actividad Copy Data, usando el conector SQL Server.
- **Copia incremental** por columna de marca de agua (`fecha_modificacion`). Cada ejecución trae solo los registros nuevos o modificados desde la última carga.
- **Horario nocturno (2-5 AM)**, cuando la operación de citas es mínima.
- **Recomendación:** solicitar a TI réplicas de lectura (Always On readable secondary). La ingesta lee de la réplica, cero impacto en producción. Si no hay réplica, la carga incremental nocturna es suficiente: mueve pocos registros y no bloquea tablas.

**MongoDB (eventos WhatsApp):**

- **Data Pipeline de Fabric** con conector MongoDB Atlas (o API REST si es on-premise).
- Incremental por campo `timestamp` del evento. Los eventos son append-only (no se modifican), lo que simplifica la ingesta.
- Mismo horario nocturno.

**Idempotencia:** ambos pipelines usan MERGE INTO (upsert) al escribir en Bronze. Si se ejecutan dos veces con los mismos datos, no duplican registros.

---

## 2. Capas y modelo canónico multi-cliente

La organización sigue el patrón Medallion en un único Lakehouse de Fabric:

### Bronze (crudo)

Datos tal cual llegan de cada fuente, en formato Parquet, particionados por `client_id` y `fecha_carga`. No se modifica ni limpia nada. Es el respaldo y la trazabilidad.

Estructura: `Bronze/sql_server/{client_id}/citas/`, `Bronze/mongodb/whatsapp_eventos/`

### Silver (limpio y canónico)

Aquí se resuelve el problema central: **cada IPS llega con esquemas diferentes** (nombres de columnas, códigos de estado, formatos de fecha). La solución:

- Un **archivo de mapping por cliente** (JSON/YAML) que define la traducción de cada columna al esquema canónico de 21 columnas (el mismo que implementamos en el pipeline E4 con `unificar_datos.py`).
- Cuando se onboardea una IPS nueva, solo se crea su mapping. No se toca el código del pipeline.
- En esta capa se aplican las **reglas de calidad**: deduplicación, corrección de edades anómalas, marcado de anomalías temporales (las mismas reglas de E1, automatizadas con los tests de E4).
- **Eliminación de PII:** cédula y teléfono se eliminan aquí. Solo se conserva `paciente_id` (hash o ID interno).

Resultado: una tabla unificada `silver_citas` con todos los clientes, misma estructura, limpia.

### Gold (consumo)

Modelo estrella listo para análisis y Power BI:

- `fact_citas`: una fila por cita, con claves a dimensiones, métricas precalculadas (`es_ausentismo`, `es_cita_efectiva`), y `client_id` para filtrado multi-tenant.
- `dim_paciente`, `dim_especialidad`, `dim_ips`, `dim_tiempo`: dimensiones estándar.
- `scoring_ausentismo`: predicciones del modelo E5, con versión y trazabilidad.

**Multi-tenant sin complejidad:** todos los clientes comparten las mismas tablas con `client_id`. No se crean lakehouses separados por cliente (sería inmanejable a 50+ IPS). La seguridad se garantiza con RLS (sección 3).

---

## 3. Seguridad y privacidad

### Aislamiento por cliente (Row-Level Security)

- **Power BI:** RLS configurado sobre `client_id`. Cada usuario de IPS solo ve las filas de su organización. Configurado en el modelo semántico, transparente para el usuario.
- **Lakehouse Gold:** vistas con filtro por `client_id`, asignadas por workspace role en Fabric.
- **Bronze y Silver:** acceso restringido al equipo de datos de DonDoctor. Ningún cliente accede a estas capas.

### Datos sensibles de pacientes (Ley 1581/2012)

| Capa | Cédula/teléfono | Nombre | paciente_id |
|------|:-:|:-:|:-:|
| Bronze | Sí (tal cual llega) | Sí | Sí |
| Silver | **Eliminados** | **Eliminado** | Sí (hash) |
| Gold | No existen | No existe | Sí (hash) |

- Bronze retiene los datos originales como respaldo legal, con acceso restringido (solo equipo de datos, con justificación).
- Desde Silver en adelante, los pacientes son identificables solo por `paciente_id` (hash irreversible). Esto cumple con minimización de datos de la Ley 1581/2012.
- Si una IPS necesita vincular un score de riesgo con un paciente real, lo hace en su propio sistema usando `paciente_id`. DonDoctor nunca expone la identidad.

---

## 4. Capacidad, costo y aislamiento de cargas

### Supuestos

| Variable | Valor | Justificación |
|----------|-------|---------------|
| IPS clientes | 50 (año 1) | Piloto con 3, escalamiento gradual |
| Citas por IPS/mes | 20,000 | Promedio del piloto (~1,300/mes) + clientes más grandes |
| Filas nuevas/mes | 1,000,000 | 50 × 20K |
| Eventos WhatsApp/mes | 2,000,000 | ~2 por cita (envío + entrega) |
| Almacenamiento Gold | ~2 GB (año 1) | Parquet comprimido, solo métricas |
| Retención Bronze | 24 meses | Requisito legal |

### Costo estimado

| Componente | SKU | Costo mensual (USD) |
|-----------|-----|-------------------:|
| Fabric capacity | F2 (2 CU) | $262 |
| Almacenamiento OneLake | ~50 GB total | Incluido en F2 |
| Power BI Pro (5 usuarios internos) | Pro | $50 |
| **Total estimado** | | **~$312/mes** |

F2 es suficiente para 50 IPS con batch diario. Si se escala a 200+ IPS o se necesita reentrenamiento frecuente de modelos, se sube a F4 ($525/mes). El salto es lineal, no exponencial.

### Aislamiento ETL vs. dashboards

- **Scheduling rules:** los pipelines de ingesta corren entre **2:00 y 5:00 AM**. Si un pipeline no termina a las 6:30 AM, se pausa automáticamente y alerta al equipo.
- **Horario laboral (7 AM - 7 PM):** la capacidad queda reservada para consultas de Power BI y el SQL analytics endpoint.
- **Fabric permite priorizar workloads** por tipo (Interactive > Pipeline). Un refresh pesado de datos nunca bloquea el tablero de gerencia.

---

## 5. Ambientes: desarrollo, pruebas y producción

Fabric ofrece **Deployment Pipelines** nativos con tres etapas:

| Ambiente | Workspace | Datos | Uso |
|----------|-----------|-------|-----|
| **Dev** | ws-datos-dev | Subset (3 IPS piloto, 3 meses) | Desarrollo de pipelines y notebooks |
| **Test** | ws-datos-test | Copia anonimizada de prod | Validación de reglas de calidad, pruebas de regresión |
| **Prod** | ws-datos-prod | Datos reales, todos los clientes | Operación diaria |

- La promoción Dev → Test → Prod se hace con un clic desde Deployment Pipelines de Fabric. Solo promueve artefactos (pipelines, notebooks, modelos semánticos), nunca datos.
- **Git integration:** los notebooks y definiciones de pipeline se versionan en el mismo repositorio Git. Cambios en el pipeline pasan por pull request antes de llegar a producción.
- **Regla:** nunca se desarrolla directamente en producción. Los datos de test se generan anonimizando un snapshot de producción.

---

## 6. Consumo por modelos e IA de forma trazable

Los agentes y modelos de IA de DonDoctor (como el modelo predictivo E5) consumen datos así:

### Acceso

- Fabric expone un **SQL analytics endpoint** sobre el Lakehouse Gold. Los modelos se conectan por SQL estándar (ODBC/JDBC), sin necesidad de copiar datos fuera de Fabric.
- Para notebooks de ML dentro de Fabric: acceso directo a las tablas Delta vía Spark.

### Trazabilidad de predicciones

Cada ejecución del modelo escribe a la tabla `scoring_ausentismo` en Gold:

| Campo | Contenido |
|-------|-----------|
| `cita_id` | Cita evaluada |
| `client_id` | IPS del paciente |
| `probabilidad` | Score del modelo (0.0 a 1.0) |
| `modelo_version` | Ej: "lr_b_v1.2" |
| `features_hash` | Hash del conjunto de features usado |
| `fecha_scoring` | Timestamp de cuándo se generó |

Si alguien pregunta "¿por qué este paciente fue marcado como alto riesgo?", se puede:
1. Buscar su `cita_id` en `scoring_ausentismo`.
2. Ver qué versión del modelo lo evaluó y cuándo.
3. Reproducir la predicción con las features de ese momento.

### Gobernanza

- **Microsoft Purview** (incluido en Fabric) proporciona linaje automático: desde qué tabla de Bronze se originó cada dato hasta qué reporte de Power BI lo consume.
- Los modelos de IA solo leen de Gold, nunca de Bronze o Silver. Esto garantiza que consumen datos limpios, sin PII, y con calidad validada.

---

## 7. Qué NO haría en Fabric

| Decisión | Razón |
|----------|-------|
| **NO streaming en tiempo real** | El ausentismo se gestiona con horas o días de anticipación, no segundos. Batch diario (y micro-batch si se necesita) cubre el caso. Streaming (Event Hubs + Stream Analytics) cuesta 3-5x más sin beneficio proporcional. Se evaluaría en fase 2 solo si se integran confirmaciones en tiempo real. |
| **NO entrenamiento pesado de ML** | Un modelo reentrenado trimestralmente con 12M filas no justifica Azure ML dedicado. Los notebooks de Fabric (Spark) son suficientes. Si se escala a modelos deep learning o reentrenamiento diario, entonces sí se migra a Azure ML. |
| **NO como base transaccional** | Fabric es analítico (OLAP), no transaccional (OLTP). El sistema de citas sigue en SQL Server. Fabric consume, no reemplaza. |
| **NO un lakehouse por cliente** | Con 50+ IPS, gestionar 50 lakehouses sería inmanejable. Un solo lakehouse con `client_id` + RLS es más simple, más barato y más fácil de mantener. |
| **NO Data Activator (alertas en tiempo real)** | Requiere streaming, que no implementamos en fase 1. Se evaluaría junto con streaming en fase 2. |
