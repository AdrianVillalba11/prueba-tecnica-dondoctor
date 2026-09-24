"""
Limpieza de calidad de datos — Corrección de hallazgos del E1.

Este script toma los archivos unificados (data/clean/) y aplica las
correcciones de calidad identificadas en el diagnóstico E1.

Cada corrección se aplica por separado, se reporta cuántos registros
afectó, y se puede rastrear comparando los archivos antes y después.

Hallazgos que corrige:
  H3 — Edades anómalas (-1 y 999): se reemplazan por nulo
  H4 — Duplicados de cita_id en Norte: se conserva el más reciente
  H6 — Citas futuras con estado terminal: se marcan con flag
  H9 — Fecha de creación posterior a fecha de cita: se marcan con flag

Hallazgos que NO corrige (y por qué):
  H1 — Esquemas heterogéneos: ya resuelto en unificar_datos.py
  H2 — Datos personales en Sur: ya eliminados en unificar_datos.py
  H5 — Estado REAGENDADA: es decisión de negocio, no un error de datos
  H7 — Refs rotas en WhatsApp: se filtrarán al cruzar en la capa de consumo
  H8 — Flag recordatorio inconsistente: se usará WhatsApp como fuente real

Uso:
    python src/limpiar_calidad.py
"""

import pandas as pd
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = Path(__file__).resolve().parent.parent
CLEAN_DIR = BASE_DIR / "data" / "clean"

FECHA_EXTRACCION = pd.Timestamp("2026-06-30 23:59:59")

# Estados terminales: son los que indican que algo ya pasó.
# Una cita futura no puede tener ninguno de estos.
ESTADOS_TERMINALES = {"ATENDIDA", "NO_ASISTIO"}


def cargar_consolidado() -> pd.DataFrame:
    """Carga el archivo consolidado que produjo unificar_datos.py."""
    df = pd.read_csv(CLEAN_DIR / "citas_consolidado.csv", encoding="utf-8")
    df["fecha_cita"] = pd.to_datetime(df["fecha_cita"])
    df["fecha_creacion"] = pd.to_datetime(df["fecha_creacion"])
    df["fecha_actualizacion"] = pd.to_datetime(df["fecha_actualizacion"])
    return df


def corregir_edades_anomalas(df: pd.DataFrame) -> pd.DataFrame:
    """
    H3 — Edades anómalas.

    Los valores -1 y 999 no son edades reales. Probablemente son
    convenciones del sistema para "no informada".

    Decisión: reemplazar por nulo (NaN). No eliminamos la fila
    porque la cita sigue siendo válida para calcular ausentismo,
    solo no podemos segmentar por edad.
    """
    mascara = (df["edad"] < 0) | (df["edad"] > 120)
    n_afectados = mascara.sum()

    df.loc[mascara, "edad"] = pd.NA

    # Convertir a Int64 (nullable integer) para que NaN no fuerce a float
    df["edad"] = df["edad"].astype("Int64")

    print(f"  H3 — Edades anómalas corregidas: {n_afectados} registros → edad = nulo")
    print(f"       Valores reemplazados: -1 y 999")
    print(f"       Por IPS: Norte={mascara[df['ips']=='Norte'].sum()}, "
          f"Sur={mascara[df['ips']=='Sur'].sum()}, "
          f"Occidente={mascara[df['ips']=='Occidente'].sum()}")

    return df


def deduplicar_citas(df: pd.DataFrame) -> pd.DataFrame:
    """
    H4 — Duplicados de cita_id en IPS Norte.

    Hay 197 cita_id que aparecen más de una vez. Algunos tienen estados
    diferentes (ej: CONFIRMADA y ATENDIDA para la misma cita).

    Decisión: quedarnos con el registro que tiene la fecha_actualizacion
    más reciente. La lógica es que la última actualización refleja el
    estado final de la cita. Si dos registros tienen la misma fecha,
    priorizamos el estado más avanzado en el ciclo de vida.

    Sur y Occidente no tienen duplicados, pero aplicamos la regla a
    todo el consolidado por consistencia.
    """
    antes = len(df)

    # Ordenar para que el más reciente quede primero
    # En caso de empate por fecha, priorizamos estado terminal sobre no terminal
    orden_estado = {
        "ATENDIDA": 6,
        "NO_ASISTIO": 5,
        "CANCELADA": 4,
        "REAGENDADA": 3,
        "CONFIRMADA": 2,
        "PENDIENTE": 1,
    }
    df["_prioridad_estado"] = df["estado"].map(orden_estado).fillna(0)
    df = df.sort_values(
        ["cita_id", "fecha_actualizacion", "_prioridad_estado"],
        ascending=[True, False, False],
    )

    # Quedarnos con el primero de cada cita_id (el más reciente/prioritario)
    df = df.drop_duplicates(subset=["cita_id"], keep="first")
    df = df.drop(columns=["_prioridad_estado"])

    despues = len(df)
    eliminados = antes - despues

    print(f"  H4 — Duplicados eliminados: {eliminados} registros")
    print(f"       Criterio: conservar el registro con fecha_actualizacion más reciente")
    print(f"       Filas antes: {antes:,} → después: {despues:,}")

    return df


def marcar_citas_futuras_terminales(df: pd.DataFrame) -> pd.DataFrame:
    """
    H6 — Citas con fecha posterior a la extracción y estado terminal.

    La extracción fue el 30/jun/2026. Si una cita está programada para
    julio o agosto de 2026, no puede estar ATENDIDA ni haber tenido
    NO_ASISTIO porque esa fecha aún no ha llegado.

    Decisión: NO eliminar (la cita existe y puede ser válida para otros
    análisis), pero agregar una flag para excluirlas de las métricas
    de ausentismo.
    """
    mascara = (
        (df["fecha_cita"] > FECHA_EXTRACCION)
        & (df["estado"].isin(ESTADOS_TERMINALES))
    )
    df["flag_anomalia_temporal"] = mascara.astype(int)

    n_marcados = mascara.sum()
    print(f"  H6 — Citas futuras con estado terminal marcadas: {n_marcados}")
    print(f"       Son citas post-30/jun/2026 con estado ATENDIDA o NO_ASISTIO")
    print(f"       Marcadas con flag_anomalia_temporal=1 (no se eliminan)")

    return df


def marcar_fechas_creacion_posteriores(df: pd.DataFrame) -> pd.DataFrame:
    """
    H9 — Fecha de creación posterior a la fecha de la cita.

    Lógicamente una cita primero se crea y luego ocurre. Si la fecha
    de creación es posterior, puede ser un registro retroactivo (cita
    de urgencia registrada después) o un error de timestamp.

    Decisión: marcar con flag para análisis posterior, no eliminar.
    """
    mascara = df["fecha_creacion"] > df["fecha_cita"]
    df["flag_fecha_creacion_posterior"] = mascara.astype(int)

    n_marcados = mascara.sum()
    print(f"  H9 — Citas con fecha_creacion > fecha_cita marcadas: {n_marcados}")
    print(f"       Marcadas con flag_fecha_creacion_posterior=1 (no se eliminan)")

    return df


def main():
    print("=" * 60)
    print("LIMPIEZA DE CALIDAD — Corrección de hallazgos E1")
    print("=" * 60)

    print("\nCargando datos unificados...")
    df = cargar_consolidado()
    print(f"  Registros iniciales: {len(df):,}")

    print("\nAplicando correcciones:\n")
    df = corregir_edades_anomalas(df)
    print()
    df = deduplicar_citas(df)
    print()
    df = marcar_citas_futuras_terminales(df)
    print()
    df = marcar_fechas_creacion_posteriores(df)

    # ── Guardar resultado ──
    salida = CLEAN_DIR / "citas_limpias.csv"
    df.to_csv(salida, index=False, encoding="utf-8")

    print(f"\n{'=' * 60}")
    print(f"RESULTADO FINAL")
    print(f"{'=' * 60}")
    print(f"  Registros finales: {len(df):,}")
    print(f"  Columnas: {len(df.columns)} ({list(df.columns)})")
    print(f"  Archivo: {salida}")

    # Resumen de flags
    n_anomalia = df["flag_anomalia_temporal"].sum()
    n_fecha = df["flag_fecha_creacion_posterior"].sum()
    n_edad_nula = df["edad"].isna().sum()
    print(f"\n  Registros con edad nula (era -1 o 999): {n_edad_nula}")
    print(f"  Registros con flag_anomalia_temporal=1:  {n_anomalia}")
    print(f"  Registros con flag_fecha_creacion_posterior=1: {n_fecha}")

    print(f"\n  Distribución de estados (después de deduplicar):")
    for estado, count in df["estado"].value_counts().items():
        print(f"    {estado:<15} {count:>5} ({100*count/len(df):.1f}%)")

    print(f"\n  Distribución por IPS:")
    for ips, count in df["ips"].value_counts().items():
        print(f"    {ips:<12} {count:>5}")

    # ── Guardar también las 3 IPS por separado ──
    print(f"\n  Guardando archivos individuales por IPS...")
    for ips in ["Norte", "Sur", "Occidente"]:
        df_ips = df[df["ips"] == ips]
        nombre = f"ips_{ips.lower()}_limpia.csv"
        df_ips.to_csv(CLEAN_DIR / nombre, index=False, encoding="utf-8")
        print(f"    {nombre}: {len(df_ips):,} filas")


if __name__ == "__main__":
    main()
