"""
Unificación de datos de citas médicas — Paso 1 del pipeline.

Contexto:
    DonDoctor gestiona citas para múltiples IPS. Cada IPS tiene su propio
    SQL Server con su propio esquema de base de datos. Este script toma los
    archivos crudos (tal como vienen de cada IPS) y los lleva a un esquema
    común para poder analizarlos y compararlos.

Problema que resuelve:
    Las 3 IPS entregan los datos de forma diferente:

    ┌─────────────────┬────────────────────┬────────────────────────┐
    │ Diferencia       │ Norte / Sur         │ Occidente              │
    ├─────────────────┼────────────────────┼────────────────────────┤
    │ Separador CSV    │ coma (,)            │ punto y coma (;)       │
    │ ID de cita       │ cita_id             │ id_cita                │
    │ Fecha de cita    │ fecha_cita          │ fecha_hora_cita        │
    │ Estado           │ ATENDIDA, NO_ASISTIO│ ATD, NAS               │
    │ Sexo             │ M / F               │ Masculino / Femenino   │
    │ Formato fecha    │ 2026-03-14 13:40    │ 2026-03-14T13:40 (ISO) │
    │ Datos sensibles  │ —                   │ —                      │
    │                  │ Sur incluye cédula  │                        │
    │                  │ y teléfono          │                        │
    └─────────────────┴────────────────────┴────────────────────────┘

    Sin esta homologación, no se pueden consolidar las 3 IPS en una
    sola tabla ni calcular métricas comparables como el ausentismo.

Qué produce:
    data/clean/
    ├── ips_norte_clean.csv      (Norte con esquema canónico)
    ├── ips_sur_clean.csv        (Sur con esquema canónico, sin datos sensibles)
    ├── ips_occidente_clean.csv  (Occidente con esquema canónico)
    └── citas_consolidado.csv    (Las 3 IPS juntas, con columna 'ips' de origen)

Qué NO hace este script:
    - No corrige problemas de calidad (edades anómalas, duplicados, etc.).
      Eso lo hace limpiar_calidad.py, el paso 2 del pipeline.
    - No elimina registros. Solo transforma nombres y valores.
    - No toca los archivos originales en data/raw/.

Uso:
    python src/unificar_datos.py
"""

import pandas as pd
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = BASE_DIR / "data" / "raw"
CLEAN_DIR = BASE_DIR / "data" / "clean"


# ════════════════════════════════════════════════════════════════════
# ESQUEMA CANÓNICO
#
# Este es el contrato de datos: todas las IPS se transforman a estas
# 21 columnas, en este orden. Si mañana llega una cuarta IPS con un
# esquema diferente, solo hay que agregar una función cargar_xxx()
# con su mapeo, y el resto del pipeline no cambia.
# ════════════════════════════════════════════════════════════════════

COLUMNAS_CANONICAS = [
    "cita_id",               # Identificador único de la cita (ej: NOR-185255)
    "paciente_id",           # ID seudonimizado del paciente (hash)
    "edad",                  # Edad del paciente al momento de la cita
    "sexo",                  # F o M
    "regimen",               # Contributivo, Subsidiado o Particular
    "localidad",             # Localidad de residencia (Bogotá)
    "especialidad",          # Especialidad médica de la cita
    "medico_id",             # ID del profesional asignado
    "sede",                  # Sede física donde se atiende la cita
    "canal_agendamiento",    # voz, whatsapp, web o call_center
    "fecha_creacion",        # Momento en que se agendó la cita
    "fecha_cita",            # Fecha y hora programada de la cita
    "fecha_actualizacion",   # Última modificación del registro
    "estado",                # PENDIENTE, CONFIRMADA, ATENDIDA, NO_ASISTIO, CANCELADA, REAGENDADA
    "recordatorio_enviado",  # 1 si se envió recordatorio por WhatsApp
    "confirmada",            # 1 si el paciente confirmó asistencia
    "gestion_recuperacion",  # 1 si se hizo gestión posterior a inasistencia
    "motivo_cierre",         # Texto libre: por qué se cerró la cita
    "observaciones",         # Notas del agendamiento
    "cita_origen_id",        # Si es reagendamiento, referencia a la cita original
    "ips",                   # Norte, Sur u Occidente (agregada por este script)
]


# ════════════════════════════════════════════════════════════════════
# MAPEOS DE HOMOLOGACIÓN
#
# Occidente viene de un sistema diferente al de Norte y Sur.
# Estos diccionarios definen cómo traducir sus valores al estándar.
# Se usan con .map(), que reemplaza solo los valores que encuentra
# en el diccionario y deja los demás intactos (vía .fillna()).
# ════════════════════════════════════════════════════════════════════

# Occidente usa 8 nombres de columna diferentes. Los demás coinciden.
RENOMBRAR_OCCIDENTE = {
    "id_cita": "cita_id",
    "id_paciente": "paciente_id",
    "edad_paciente": "edad",
    "genero": "sexo",
    "regimen_salud": "regimen",
    "fecha_hora_cita": "fecha_cita",
    "estado_cita": "estado",
    "id_cita_origen": "cita_origen_id",
}

# Norte y Sur usan palabras completas; Occidente usa abreviaturas de 3 letras.
HOMOLOGAR_ESTADOS = {
    "ATD": "ATENDIDA",
    "NAS": "NO_ASISTIO",
    "CAN": "CANCELADA",
    "REP": "REAGENDADA",
    "PEN": "PENDIENTE",
    "CONF": "CONFIRMADA",
}

# Norte y Sur codifican como M/F; Occidente como Masculino/Femenino.
# Elegimos M/F porque es más compacto y consistente con estándares de salud.
HOMOLOGAR_SEXO = {
    "Femenino": "F",
    "Masculino": "M",
}

# IPS Sur incluye cédula y teléfono del paciente.
# Norte y Occidente no traen estos campos.
# Los eliminamos porque son datos personales protegidos por la
# Ley 1581/2012 y no deben estar en un data warehouse sin controles.
COLUMNAS_SENSIBLES = ["documento_identidad", "telefono"]


# ════════════════════════════════════════════════════════════════════
# FUNCIONES DE CARGA POR IPS
#
# Cada IPS tiene su propia función porque cada una tiene sus
# particularidades. Si llega un nuevo cliente, se agrega una función
# nueva sin tocar las existentes.
# ════════════════════════════════════════════════════════════════════

def cargar_norte() -> pd.DataFrame:
    """
    IPS Norte — la más simple.

    Formato: CSV separado por coma, encoding UTF-8.
    Esquema: coincide con el canónico (mismos nombres de columna).
    Particularidad: tiene duplicados de cita_id (se corrigen en limpiar_calidad.py).
    """
    df = pd.read_csv(RAW_DIR / "ips_norte_citas.csv", encoding="utf-8")
    df["ips"] = "Norte"
    return df


def cargar_sur() -> pd.DataFrame:
    """
    IPS Sur — incluye datos personales que deben eliminarse.

    Formato: CSV separado por coma, encoding UTF-8.
    Esquema: 22 columnas (vs 20 de Norte). Las 2 extra son
             documento_identidad (cédula) y telefono (celular).
    Particularidad: estos campos son datos personales sensibles.
                    Se eliminan aquí para que nunca lleguen a la capa limpia.
    """
    df = pd.read_csv(RAW_DIR / "ips_sur_citas.csv", encoding="utf-8")

    # Eliminar columnas sensibles. errors="ignore" evita error si
    # alguna columna no existe (defensivo ante cambios en la extracción).
    df = df.drop(columns=COLUMNAS_SENSIBLES, errors="ignore")
    df["ips"] = "Sur"
    return df


def cargar_occidente() -> pd.DataFrame:
    """
    IPS Occidente — la que más transformación necesita.

    Formato: CSV separado por PUNTO Y COMA (;), encoding UTF-8.
             Si se lee con coma, pandas lo interpreta como 1 sola columna.
    Esquema: 20 columnas pero con nombres diferentes (id_cita vs cita_id, etc.)
    Particularidades:
        - Estados abreviados: ATD, NAS, CAN, REP, PEN, CONF
        - Sexo como texto largo: "Femenino", "Masculino"
        - Fechas en formato ISO con T: "2026-03-14T13:40:00"

    Las 3 transformaciones (renombrar, homologar estados, homologar sexo)
    se aplican aquí porque son específicas de esta IPS.
    """
    df = pd.read_csv(
        RAW_DIR / "ips_occidente_citas.csv",
        sep=";",
        encoding="utf-8",
    )

    # 1. Renombrar columnas al esquema canónico
    df = df.rename(columns=RENOMBRAR_OCCIDENTE)

    # 2. Traducir estados abreviados a palabras completas
    #    .map() reemplaza los valores del diccionario; .fillna() conserva
    #    cualquier valor no mapeado (defensivo ante estados nuevos).
    df["estado"] = df["estado"].map(HOMOLOGAR_ESTADOS).fillna(df["estado"])

    # 3. Traducir sexo de texto largo a código corto
    df["sexo"] = df["sexo"].map(HOMOLOGAR_SEXO).fillna(df["sexo"])

    df["ips"] = "Occidente"
    return df


# ════════════════════════════════════════════════════════════════════
# FUNCIONES DE TRANSFORMACIÓN COMUNES
# ════════════════════════════════════════════════════════════════════

def estandarizar_fechas(df: pd.DataFrame) -> pd.DataFrame:
    """
    Convierte las 3 columnas de fecha a tipo datetime de pandas.

    Norte y Sur usan formato "2026-03-14 13:40:00" (con espacio).
    Occidente usa formato ISO "2026-03-14T13:40:00" (con T).
    pd.to_datetime() reconoce ambos formatos automáticamente.

    errors="coerce" convierte valores no parseables a NaT (nulo de fecha)
    en vez de lanzar un error, para no perder todo el lote por un registro malo.
    """
    for col in ["fecha_creacion", "fecha_cita", "fecha_actualizacion"]:
        df[col] = pd.to_datetime(df[col], errors="coerce")
    return df


def ordenar_columnas(df: pd.DataFrame) -> pd.DataFrame:
    """
    Garantiza que el DataFrame tenga exactamente las columnas canónicas, en orden.

    Si una columna del esquema canónico no existe en el DataFrame (porque esa IPS
    no la tiene), se crea con valor nulo. Luego se seleccionan solo las columnas
    canónicas en el orden definido, descartando cualquier columna extra.

    Esto asegura que los 3 DataFrames tengan la misma estructura antes de
    concatenarlos, evitando errores de pd.concat por columnas faltantes.
    """
    for col in COLUMNAS_CANONICAS:
        if col not in df.columns:
            df[col] = pd.NaT if "fecha" in col else None
    return df[COLUMNAS_CANONICAS]


# ════════════════════════════════════════════════════════════════════
# EJECUCIÓN PRINCIPAL
# ════════════════════════════════════════════════════════════════════

def main():
    sys.stdout.reconfigure(encoding="utf-8")
    CLEAN_DIR.mkdir(parents=True, exist_ok=True)

    # ── Cargar cada IPS con su lógica específica ──
    print("Cargando fuentes de datos...")
    df_norte = cargar_norte()
    print(f"  Norte:     {len(df_norte):,} filas, {len(df_norte.columns)} columnas")

    df_sur = cargar_sur()
    print(f"  Sur:       {len(df_sur):,} filas, {len(df_sur.columns)} columnas")

    df_occidente = cargar_occidente()
    print(f"  Occidente: {len(df_occidente):,} filas, {len(df_occidente.columns)} columnas")

    # ── Estandarizar fechas y columnas ──
    print("\nEstandarizando fechas...")
    df_norte = estandarizar_fechas(df_norte)
    df_sur = estandarizar_fechas(df_sur)
    df_occidente = estandarizar_fechas(df_occidente)

    print("Alineando columnas al esquema canónico...")
    df_norte = ordenar_columnas(df_norte)
    df_sur = ordenar_columnas(df_sur)
    df_occidente = ordenar_columnas(df_occidente)

    # ── Guardar archivos individuales ──
    # Se guardan por separado para poder comparar cada IPS de forma aislada
    # y para trazabilidad (saber exactamente qué entró de cada fuente).
    print("\nGuardando archivos individuales...")
    df_norte.to_csv(CLEAN_DIR / "ips_norte_clean.csv", index=False, encoding="utf-8")
    df_sur.to_csv(CLEAN_DIR / "ips_sur_clean.csv", index=False, encoding="utf-8")
    df_occidente.to_csv(CLEAN_DIR / "ips_occidente_clean.csv", index=False, encoding="utf-8")

    # ── Consolidar las 3 IPS ──
    # pd.concat apila los DataFrames verticalmente. ignore_index=True genera
    # un índice nuevo (0, 1, 2...) en vez de mantener los índices originales,
    # evitando índices duplicados.
    print("Consolidando las 3 IPS en un solo archivo...")
    df_consolidado = pd.concat([df_norte, df_sur, df_occidente], ignore_index=True)
    df_consolidado.to_csv(CLEAN_DIR / "citas_consolidado.csv", index=False, encoding="utf-8")

    # ── Reporte de lo que se produjo ──
    print(f"\n{'=' * 50}")
    print(f"Total consolidado: {len(df_consolidado):,} filas")
    print(f"\nDistribución por IPS:")
    print(df_consolidado["ips"].value_counts().to_string())
    print(f"\nDistribución de estados:")
    print(df_consolidado["estado"].value_counts().to_string())
    print(f"\nArchivos generados en {CLEAN_DIR}/:")
    for f in sorted(CLEAN_DIR.glob("*.csv")):
        size_kb = f.stat().st_size / 1024
        print(f"  {f.name} ({size_kb:.0f} KB)")


if __name__ == "__main__":
    main()
