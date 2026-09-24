"""
Limpieza de calidad de datos — Paso 2 del pipeline.

Contexto:
    Este script es el segundo paso del pipeline. El primero (unificar_datos.py)
    homologó los esquemas de las 3 IPS para que tengan las mismas columnas,
    estados y formatos. Pero los datos todavía tienen problemas de calidad
    que se identificaron en el diagnóstico E1.

    Este script corrige esos problemas sin eliminar registros cuando es posible.
    La filosofía es: marcar lo sospechoso, no eliminarlo. Un registro con edad
    anómala sigue siendo una cita válida para calcular ausentismo; un registro
    con fecha futura y estado ATENDIDA no.

Qué corrige (y cómo):
    H3 — Edades -1 y 999 → se reemplazan por nulo (la fila se conserva)
    H4 — cita_id duplicados en Norte → se conserva el más reciente
    H6 — Citas futuras con estado ATENDIDA → se marcan con flag
    H9 — fecha_creacion > fecha_cita → se marcan con flag

Qué NO corrige (y por qué):
    H1 (esquemas diferentes) → ya resuelto en unificar_datos.py
    H2 (datos personales Sur) → ya eliminados en unificar_datos.py
    H5 (estado REAGENDADA) → no es un error, es una decisión de negocio
                              que se aborda en el entregable E2
    H7 (refs rotas WhatsApp) → se resuelve al cruzar en la capa de consumo,
                                filtrando solo eventos con match confirmado
    H8 (flag recordatorio inconsistente) → no se modifica la flag; en su lugar
                                           se usarán los eventos WhatsApp como
                                           fuente de verdad en el análisis

Flujo de datos:
    data/clean/citas_consolidado.csv  →  [este script]  →  data/clean/citas_limpias.csv
    (16,095 filas, con problemas)         (correcciones)    (15,897 filas, limpio)

    También genera archivos individuales por IPS:
    ips_norte_limpia.csv, ips_sur_limpia.csv, ips_occidente_limpia.csv

Trazabilidad:
    Los archivos *_clean.csv (paso 1) se conservan junto a los *_limpia.csv
    (paso 2), así se puede comparar el antes y el después de cada corrección.

Uso:
    python src/limpiar_calidad.py
"""

import pandas as pd
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = Path(__file__).resolve().parent.parent
CLEAN_DIR = BASE_DIR / "data" / "clean"

# La extracción de datos se realizó el 30 de junio de 2026 a las 23:59
# (según el diccionario de datos). Cualquier cita con fecha posterior
# no ha ocurrido aún, por lo que no puede tener un estado terminal.
FECHA_EXTRACCION = pd.Timestamp("2026-06-30 23:59:59")

# Estados terminales: indican que la cita ya ocurrió (o no ocurrió).
# PENDIENTE y CONFIRMADA son estados intermedios (la cita aún no pasó).
# CANCELADA y REAGENDADA son acciones previas a la cita.
# Solo ATENDIDA y NO_ASISTIO implican que la fecha de la cita ya pasó.
ESTADOS_TERMINALES = {"ATENDIDA", "NO_ASISTIO"}


def cargar_consolidado() -> pd.DataFrame:
    """
    Lee el archivo consolidado que produjo unificar_datos.py.

    Convierte las columnas de fecha a datetime para poder hacer
    comparaciones temporales (ej: ¿la fecha de creación es posterior
    a la fecha de la cita?).
    """
    df = pd.read_csv(CLEAN_DIR / "citas_consolidado.csv", encoding="utf-8")
    df["fecha_cita"] = pd.to_datetime(df["fecha_cita"])
    df["fecha_creacion"] = pd.to_datetime(df["fecha_creacion"])
    df["fecha_actualizacion"] = pd.to_datetime(df["fecha_actualizacion"])
    return df


def corregir_edades_anomalas(df: pd.DataFrame) -> pd.DataFrame:
    """
    H3 — Edades anómalas: -1 y 999.

    En las 3 IPS encontramos 274 registros con edad=-1 o edad=999.
    Estos valores no son edades reales. Son probablemente convenciones
    del sistema fuente para representar "edad no informada" o "no aplica".

    Decisión: reemplazar por nulo (NaN), no eliminar la fila.
    Razón: la cita sigue siendo válida para calcular ausentismo.
    Lo que perdemos es la posibilidad de segmentar esas 274 citas por
    grupo etario, pero eso es preferible a distorsionar los promedios
    (999 infla la media de edad de toda la IPS).

    Nota técnica: usamos pd.NA (nullable integer) en vez de np.nan
    porque np.nan fuerza la columna entera a float64 (las edades
    pasarían de 34 a 34.0), mientras que Int64 mantiene los enteros.
    """
    mascara = (df["edad"] < 0) | (df["edad"] > 120)
    n_afectados = mascara.sum()

    df.loc[mascara, "edad"] = pd.NA
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

    Norte tiene 197 cita_id que aparecen 2 veces (395 filas en total).
    Sur y Occidente no tienen duplicados.

    ¿Qué pasó? El sistema fuente parece guardar versiones históricas
    del registro de la cita. Ejemplo real:
        NOR-182102 → CONFIRMADA (actualizado 21/abr)
        NOR-182102 → ATENDIDA   (actualizado 22/abr)
    El paciente confirmó y luego asistió, pero el sistema guardó
    ambos estados en vez de actualizar el registro existente.

    Decisión: conservar el registro con la fecha_actualizacion más
    reciente, porque refleja el estado final de la cita.

    Criterio de desempate: si dos registros del mismo cita_id tienen
    la misma fecha_actualizacion (raro pero posible), priorizamos el
    estado más avanzado en el ciclo de vida de la cita:
        PENDIENTE → CONFIRMADA → REAGENDADA → CANCELADA → NO_ASISTIO → ATENDIDA

    Aunque aplicamos la regla sobre el consolidado completo (las 3 IPS),
    solo Norte se ve afectada porque las otras no tienen duplicados.
    """
    antes = len(df)

    # Asignar prioridad numérica a cada estado.
    # Mayor número = más avanzado en el ciclo de vida.
    orden_estado = {
        "PENDIENTE": 1,
        "CONFIRMADA": 2,
        "REAGENDADA": 3,
        "CANCELADA": 4,
        "NO_ASISTIO": 5,
        "ATENDIDA": 6,
    }
    df["_prioridad_estado"] = df["estado"].map(orden_estado).fillna(0)

    # Ordenar: por cita_id, luego por fecha más reciente primero,
    # luego por estado más avanzado primero. Así el primer registro
    # de cada cita_id es siempre el "ganador".
    df = df.sort_values(
        ["cita_id", "fecha_actualizacion", "_prioridad_estado"],
        ascending=[True, False, False],
    )

    # drop_duplicates con keep="first" conserva el primer registro
    # de cada grupo (el que tiene la fecha/estado más reciente).
    df = df.drop_duplicates(subset=["cita_id"], keep="first")

    # Limpiar la columna auxiliar
    df = df.drop(columns=["_prioridad_estado"])

    despues = len(df)
    eliminados = antes - despues

    print(f"  H4 — Duplicados eliminados: {eliminados} registros")
    print(f"       Criterio: conservar el registro con fecha_actualizacion más reciente")
    print(f"       Filas antes: {antes:,} → después: {despues:,}")

    return df


def marcar_citas_futuras_terminales(df: pd.DataFrame) -> pd.DataFrame:
    """
    H6 — Citas futuras con estado terminal.

    La extracción se hizo el 30/jun/2026. Hay citas programadas para
    julio y agosto de 2026, lo cual es normal (citas agendadas a futuro).
    Lo anómalo es que 67 de esas citas ya están marcadas como ATENDIDA
    o NO_ASISTIO — algo que no puede haber pasado porque la fecha
    de la cita aún no ha llegado.

    Decisión: NO eliminar la fila (la cita existe y se agendó realmente),
    pero agregar una flag para que se puedan excluir del cálculo de
    ausentismo y otras métricas que asumen que la cita ya ocurrió.

    La columna flag_anomalia_temporal queda con valor:
        1 = cita futura con estado terminal (excluir de métricas)
        0 = cita normal
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

    La secuencia lógica es: primero se crea la cita (fecha_creacion),
    luego ocurre la cita (fecha_cita). Si fecha_creacion > fecha_cita,
    algo no cuadra. Encontramos 121 registros así.

    Posibles explicaciones:
        - Registro retroactivo: una cita de urgencia que se registra
          en el sistema después de que ya ocurrió.
        - Desfase de zona horaria entre el servidor y la aplicación.
        - Error de captura en el sistema fuente.

    Decisión: marcar con flag para análisis posterior, no eliminar.
    Son solo el 0.76% del total y no afectan significativamente las
    métricas. Pero es información útil para preguntar al dueño del dato.

    La columna flag_fecha_creacion_posterior queda con valor:
        1 = fecha_creacion posterior a fecha_cita (revisar)
        0 = orden temporal correcto
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

    print("\nCargando datos unificados (salida de unificar_datos.py)...")
    df = cargar_consolidado()
    print(f"  Registros iniciales: {len(df):,}")

    # Aplicar correcciones en orden. El orden importa:
    # 1. Primero corregimos edades (no afecta otras correcciones)
    # 2. Luego deduplicamos (reduce filas, debe ser antes de los flags)
    # 3. Luego marcamos anomalías temporales (sobre datos ya deduplicados)
    # 4. Finalmente marcamos fechas invertidas
    print("\nAplicando correcciones:\n")
    df = corregir_edades_anomalas(df)
    print()
    df = deduplicar_citas(df)
    print()
    df = marcar_citas_futuras_terminales(df)
    print()
    df = marcar_fechas_creacion_posteriores(df)

    # ── Guardar el consolidado limpio ──
    salida = CLEAN_DIR / "citas_limpias.csv"
    df.to_csv(salida, index=False, encoding="utf-8")

    # ── Reporte final ──
    print(f"\n{'=' * 60}")
    print(f"RESULTADO FINAL")
    print(f"{'=' * 60}")
    print(f"  Registros finales: {len(df):,}")
    print(f"  Columnas: {len(df.columns)}")
    print(f"  Columnas nuevas: flag_anomalia_temporal, flag_fecha_creacion_posterior")
    print(f"  Archivo: {salida}")

    n_anomalia = df["flag_anomalia_temporal"].sum()
    n_fecha = df["flag_fecha_creacion_posterior"].sum()
    n_edad_nula = df["edad"].isna().sum()
    print(f"\n  Resumen de correcciones:")
    print(f"    Edades convertidas a nulo (era -1 o 999): {n_edad_nula}")
    print(f"    Citas con flag_anomalia_temporal=1:       {n_anomalia}")
    print(f"    Citas con flag_fecha_creacion_posterior=1: {n_fecha}")

    print(f"\n  Distribución de estados (después de deduplicar):")
    for estado, count in df["estado"].value_counts().items():
        print(f"    {estado:<15} {count:>5} ({100*count/len(df):.1f}%)")

    print(f"\n  Distribución por IPS:")
    for ips, count in df["ips"].value_counts().items():
        print(f"    {ips:<12} {count:>5}")

    # ── Guardar archivos individuales por IPS ──
    # Útil para análisis específicos por IPS y para validar que
    # la deduplicación solo afectó a Norte.
    print(f"\n  Guardando archivos individuales por IPS...")
    for ips in ["Norte", "Sur", "Occidente"]:
        df_ips = df[df["ips"] == ips]
        nombre = f"ips_{ips.lower()}_limpia.csv"
        df_ips.to_csv(CLEAN_DIR / nombre, index=False, encoding="utf-8")
        print(f"    {nombre}: {len(df_ips):,} filas")


if __name__ == "__main__":
    main()
