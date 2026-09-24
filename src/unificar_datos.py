"""
Script de unificación de datos de citas médicas.

Lee las 3 fuentes de IPS (Norte, Sur, Occidente), estandariza sus esquemas,
y genera 4 archivos limpios: uno por IPS + uno consolidado.

Uso:
    python src/unificar_datos.py
"""

import pandas as pd
import json
import sys
import os
from pathlib import Path

# Rutas
BASE_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = BASE_DIR / "data" / "raw"
CLEAN_DIR = BASE_DIR / "data" / "clean"


# ── Columnas canónicas ─────────────────────────────────────────────
# Este es el esquema único al que llevamos las 3 IPS.
COLUMNAS_CANONICAS = [
    "cita_id",
    "paciente_id",
    "edad",
    "sexo",
    "regimen",
    "localidad",
    "especialidad",
    "medico_id",
    "sede",
    "canal_agendamiento",
    "fecha_creacion",
    "fecha_cita",
    "fecha_actualizacion",
    "estado",
    "recordatorio_enviado",
    "confirmada",
    "gestion_recuperacion",
    "motivo_cierre",
    "observaciones",
    "cita_origen_id",
    "ips",
]


# ── Mapeos de homologación ──────────────────────────────────────────

# Occidente usa nombres de columnas diferentes
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

# Occidente usa abreviaturas en los estados
HOMOLOGAR_ESTADOS = {
    "ATD": "ATENDIDA",
    "NAS": "NO_ASISTIO",
    "CAN": "CANCELADA",
    "REP": "REAGENDADA",
    "PEN": "PENDIENTE",
    "CONF": "CONFIRMADA",
}

# Occidente usa texto largo para sexo
HOMOLOGAR_SEXO = {
    "Femenino": "F",
    "Masculino": "M",
}

# Columnas sensibles que Sur tiene de más y deben eliminarse
COLUMNAS_SENSIBLES = ["documento_identidad", "telefono"]


def cargar_norte() -> pd.DataFrame:
    """Carga IPS Norte. Separador coma, esquema estándar."""
    df = pd.read_csv(RAW_DIR / "ips_norte_citas.csv", encoding="utf-8")
    df["ips"] = "Norte"
    return df


def cargar_sur() -> pd.DataFrame:
    """Carga IPS Sur. Separador coma, tiene columnas sensibles extra."""
    df = pd.read_csv(RAW_DIR / "ips_sur_citas.csv", encoding="utf-8")
    df = df.drop(columns=COLUMNAS_SENSIBLES, errors="ignore")
    df["ips"] = "Sur"
    return df


def cargar_occidente() -> pd.DataFrame:
    """
    Carga IPS Occidente. Separador punto y coma, nombres de columna
    diferentes, estados abreviados y sexo como texto largo.
    """
    df = pd.read_csv(
        RAW_DIR / "ips_occidente_citas.csv",
        sep=";",
        encoding="utf-8",
    )

    df = df.rename(columns=RENOMBRAR_OCCIDENTE)
    df["estado"] = df["estado"].map(HOMOLOGAR_ESTADOS).fillna(df["estado"])
    df["sexo"] = df["sexo"].map(HOMOLOGAR_SEXO).fillna(df["sexo"])
    df["ips"] = "Occidente"

    return df


def estandarizar_fechas(df: pd.DataFrame) -> pd.DataFrame:
    """
    Convierte las 3 columnas de fecha a datetime.
    Occidente viene con formato ISO (T separador), Norte/Sur con espacio.
    pd.to_datetime maneja ambos formatos automáticamente.
    """
    for col in ["fecha_creacion", "fecha_cita", "fecha_actualizacion"]:
        df[col] = pd.to_datetime(df[col], errors="coerce")
    return df


def ordenar_columnas(df: pd.DataFrame) -> pd.DataFrame:
    """Asegura que el DataFrame tenga exactamente las columnas canónicas, en orden."""
    for col in COLUMNAS_CANONICAS:
        if col not in df.columns:
            df[col] = pd.NaT if "fecha" in col else None
    return df[COLUMNAS_CANONICAS]


def main():
    sys.stdout.reconfigure(encoding="utf-8")

    CLEAN_DIR.mkdir(parents=True, exist_ok=True)

    print("Cargando fuentes de datos...")
    df_norte = cargar_norte()
    print(f"  Norte:     {len(df_norte):,} filas, {len(df_norte.columns)} columnas")

    df_sur = cargar_sur()
    print(f"  Sur:       {len(df_sur):,} filas, {len(df_sur.columns)} columnas")

    df_occidente = cargar_occidente()
    print(f"  Occidente: {len(df_occidente):,} filas, {len(df_occidente.columns)} columnas")

    print("\nEstandarizando fechas...")
    df_norte = estandarizar_fechas(df_norte)
    df_sur = estandarizar_fechas(df_sur)
    df_occidente = estandarizar_fechas(df_occidente)

    print("Ordenando columnas al esquema canónico...")
    df_norte = ordenar_columnas(df_norte)
    df_sur = ordenar_columnas(df_sur)
    df_occidente = ordenar_columnas(df_occidente)

    print("\nGuardando archivos individuales limpios...")
    df_norte.to_csv(CLEAN_DIR / "ips_norte_clean.csv", index=False, encoding="utf-8")
    df_sur.to_csv(CLEAN_DIR / "ips_sur_clean.csv", index=False, encoding="utf-8")
    df_occidente.to_csv(CLEAN_DIR / "ips_occidente_clean.csv", index=False, encoding="utf-8")

    print("Consolidando las 3 IPS...")
    df_consolidado = pd.concat([df_norte, df_sur, df_occidente], ignore_index=True)
    df_consolidado.to_csv(CLEAN_DIR / "citas_consolidado.csv", index=False, encoding="utf-8")

    print(f"\n{'='*50}")
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
