# Prueba Técnica — Líder e Ingeniero de Datos | DonDoctor

Análisis de ausentismo en citas médicas para tres IPS clientes, con diagnóstico de calidad de datos, pipeline de transformación, modelo predictivo y propuesta de arquitectura en Azure/Fabric.

## Estructura del proyecto

```
├── data/
│   ├── raw/              # Datos originales (no versionados)
│   ├── clean/            # Datos limpios y unificados (no versionados)
│   └── consumo/          # Capa de consumo: fact_citas + dimensiones (no versionados)
├── src/
│   ├── unificar_datos.py     # Homologa esquemas de las 3 IPS → citas_consolidado.csv
│   ├── limpiar_calidad.py    # Corrige hallazgos H3, H4, H6, H9 → citas_limpias.csv
│   └── crear_capa_consumo.py # Cruza con WhatsApp, genera fact_citas + dimensiones
├── notebooks/
│   ├── E1_diagnostico_calidad.py  # Perfilamiento y 9 hallazgos de calidad
│   └── E5_modelo_predictivo.py    # Modelo predictivo de ausentismo (LR + GB)
├── tests/
│   └── test_calidad.py       # 22 tests automatizados (R1-R9)
├── docs/
│   ├── E2_estrategia_producto_datos.md/.pdf
│   ├── E3_arquitectura_azure_fabric.md/.pdf
│   ├── E3_diagrama_arquitectura.png
│   ├── E5_curvas_roc.png
│   ├── E5_importancia_variables.png
│   ├── E5_fairness.png
│   └── E6_resumen_ejecutivo.md
├── requirements.txt
└── USO-IA.md
```

## Datos

Los datos **no están incluidos** en el repositorio por política de confidencialidad (Ley 1581/2012).
Para ejecutar el proyecto, ubicar los archivos del dataset en `data/raw/`:

```
data/raw/
├── ips_norte_citas.csv
├── ips_sur_citas.csv
├── ips_occidente_citas.csv
└── whatsapp_eventos.jsonl
```

## Instalación y ejecución

```bash
python -m venv venv
source venv/bin/activate  # En Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### Pipeline completo (en orden)

```bash
# 1. Unificar las 3 IPS en un esquema canónico
python src/unificar_datos.py

# 2. Aplicar correcciones de calidad
python src/limpiar_calidad.py

# 3. Generar capa de consumo (fact_citas + dimensiones)
python src/crear_capa_consumo.py

# 4. Ejecutar diagnóstico de calidad
python notebooks/E1_diagnostico_calidad.py

# 5. Ejecutar modelo predictivo
python notebooks/E5_modelo_predictivo.py

# 6. Ejecutar tests de calidad
python -m pytest tests/ -v
```

El pipeline es **idempotente**: puede ejecutarse múltiples veces sin duplicar datos.

## Decisiones de diseño

- **Ausentismo = NO_ASISTIO / (ATENDIDA + NO_ASISTIO) = 15.8%.** Se excluyen canceladas y reagendadas del denominador porque no representan agenda desperdiciada.
- **REAGENDADA** se excluye del cálculo (897 citas, 5.7%). El paciente tomó acción antes; no es inasistencia.
- **Datos personales** (cédula, teléfono de IPS Sur) se eliminan en la capa de limpieza. Solo se conserva `paciente_id`.
- **Split temporal** (no aleatorio) para el modelo predictivo: train jul-2025 a mar-2026, test abr-jun 2026.
- **Dos escenarios de predicción:** A (al agendar) y B (24h antes, con WhatsApp). El escenario B es el más accionable.
- **Regresión Logística supera a Gradient Boosting** (AUC 0.689 vs 0.652). Con pocos datos y relaciones lineales, el modelo simple generaliza mejor. Se reporta honestamente.

## Limitaciones conocidas

- **3 IPS, 12 meses.** Los resultados pueden no generalizar a IPS en otras ciudades o con perfiles distintos.
- **AUC < 0.70.** El modelo es útil para priorizar (3.5x lift en top-50) pero no para predicción individual.
- **897 citas REAGENDADA** sin referencia a cita original (`cita_origen_id` vacío). Pendiente resolver con TI.
- **WhatsApp:** 31% de eventos sin referencia a cita. Se filtran al cruzar, pero indican un problema de trazabilidad en el sistema fuente.

## Qué haría con más tiempo

- Integrar más variables: distancia al consultorio, clima, historial de pagos.
- Implementar el tablero operacional en Power BI con datos reales.
- Probar modelos adicionales (XGBoost con tuning, redes neuronales).
- Construir el pipeline en Fabric con datos reales de al menos 10 IPS.
