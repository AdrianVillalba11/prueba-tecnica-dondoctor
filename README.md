# Prueba Técnica — Líder e Ingeniero de Datos | DonDoctor

Análisis de ausentismo en citas médicas para tres IPS clientes, con diagnóstico de calidad de datos, pipeline de transformación, modelo predictivo y propuesta de arquitectura en Azure/Fabric.

## Estructura del proyecto

```
├── data/
│   ├── raw/          # Datos originales (no versionados)
│   └── clean/        # Datos limpios y unificados (no versionados)
├── notebooks/        # Análisis exploratorio y modelo predictivo
├── src/              # Scripts del pipeline y utilidades
├── tests/            # Pruebas de calidad de datos
├── docs/             # Documentos de entrega (E2, E3, E6)
├── requirements.txt  # Dependencias Python
└── USO-IA.md         # Declaración de uso de IA
```

## Datos

Los datos **no están incluidos** en el repositorio por política de confidencialidad.
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

### Ejecutar el pipeline de unificación
```bash
python src/unificar_datos.py
```

### Ejecutar pruebas de calidad
```bash
python -m pytest tests/
```

## Decisiones de diseño

Documentadas en cada entregable y en los commits del repositorio.

## Limitaciones conocidas

Se documentarán conforme avance el desarrollo.
