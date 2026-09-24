"""
Capa de consumo — Paso 3 del pipeline.

Contexto:
    Este es el último paso del pipeline de datos. Toma la tabla de citas
    limpia (paso 2) y los eventos de WhatsApp (raw), y produce las tablas
    listas para responder preguntas de negocio:

    - ¿Cuál es el ausentismo real por IPS?
    - ¿Los recordatorios por WhatsApp reducen el ausentismo?
    - ¿En qué especialidad, sede o día de la semana hay más ausentismo?
    - ¿Qué pacientes tienen mayor riesgo de no asistir?

Modelo de datos (estrella):
    Se organiza en un modelo dimensional tipo estrella, donde hay una
    tabla de hechos central (fact_citas) rodeada de tablas de dimensiones.
    Este diseño permite consultas rápidas tipo:
        "Ausentismo por IPS, mes y especialidad"
    sin tener que hacer joins complejos cada vez.

    fact_citas ← tabla central, una fila por cita con métricas calculadas
    dim_paciente ← un registro por paciente (datos demográficos)
    dim_especialidad ← catálogo de especialidades con ID numérico
    dim_sede ← catálogo de sedes con su IPS asociada
    dim_tiempo ← una fila por fecha-hora, con año, mes, día de semana, hora

Definición de ausentismo:
    Tasa = NO_ASISTIO / (ATENDIDA + NO_ASISTIO)

    ¿Por qué este denominador?
    - PENDIENTE y CONFIRMADA se excluyen porque la cita aún no ocurrió.
    - CANCELADA se excluye porque el paciente avisó (no es "no llegar").
    - REAGENDADA se excluye porque se reprogramó (hay una nueva cita).
    - Solo contamos citas con desenlace definitivo: asistió o no asistió.
    - También excluimos citas con flag_anomalia_temporal=1 (futuras con
      estado terminal, que son incoherentes).

    Esta definición produce una tasa más alta que la de Comercial (12-14%)
    porque excluye cancelaciones del denominador. Es más honesta: mide
    realmente "de los que debían venir, cuántos no vinieron".

Cruce con WhatsApp:
    Los eventos de WhatsApp registran el ciclo del recordatorio:
    enviado → entregado → leído → respuesta.
    Cruzamos por ref_cita ↔ cita_id para saber si cada cita recibió
    recordatorio y si el paciente interactuó con él.
    Solo usamos eventos con ref_cita válida (~70% del total).

Pipeline completo:
    data/raw/ → unificar_datos.py → data/clean/*_clean.csv
                                         ↓
                                    limpiar_calidad.py → data/clean/citas_limpias.csv
                                                              ↓
                                                    [este script] → data/consumo/
                                                                     ├── fact_citas.csv
                                                                     ├── dim_paciente.csv
                                                                     ├── dim_especialidad.csv
                                                                     ├── dim_sede.csv
                                                                     └── dim_tiempo.csv
Uso:
    python src/crear_capa_consumo.py
"""

import pandas as pd
import json
import sys
from pathlib import Path
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = Path(__file__).resolve().parent.parent
CLEAN_DIR = BASE_DIR / "data" / "clean"
RAW_DIR = BASE_DIR / "data" / "raw"
CONSUMO_DIR = BASE_DIR / "data" / "consumo"

# Estados que representan un desenlace definitivo: la cita ya debió ocurrir.
# Solo estos entran en el cálculo de ausentismo.
ESTADOS_EFECTIVOS = {"ATENDIDA", "NO_ASISTIO"}


# ════════════════════════════════════════════════════════════════════
# CARGA DE DATOS
# ════════════════════════════════════════════════════════════════════

def cargar_citas_limpias() -> pd.DataFrame:
    """
    Lee la tabla de citas limpia (salida de limpiar_calidad.py).
    Son 15,897 registros con 23 columnas, ya deduplicados y con flags.
    """
    df = pd.read_csv(CLEAN_DIR / "citas_limpias.csv", encoding="utf-8")
    df["fecha_cita"] = pd.to_datetime(df["fecha_cita"])
    df["fecha_creacion"] = pd.to_datetime(df["fecha_creacion"])
    df["fecha_actualizacion"] = pd.to_datetime(df["fecha_actualizacion"])
    return df


def cargar_eventos_whatsapp() -> list[dict]:
    """
    Lee los eventos de WhatsApp desde el JSONL original.

    Cada línea es un documento JSON con esta estructura:
        _id: identificador del evento (ej: wa48210027766)
        ts: timestamp en milisegundos epoch
        tipo: enviado | entregado | leido | respuesta
        mensaje:
            destinatario: teléfono (+57...)
            plantilla: recordatorio_cita_v3
            cuerpo: (solo en respuestas) texto del paciente
        contexto:
            ips: NORTE | SUR | OCCIDENTE
            ref_cita: (opcional) ID de la cita asociada
    """
    with open(RAW_DIR / "whatsapp_eventos.jsonl", "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f]


# ════════════════════════════════════════════════════════════════════
# CRUCE CON WHATSAPP
#
# Agrupamos los eventos por ref_cita para saber, de cada cita:
# - ¿Se envió recordatorio?
# - ¿Se entregó al teléfono?
# - ¿El paciente lo leyó?
# - ¿El paciente respondió?
# - ¿Qué respondió?
#
# Esto permite medir la efectividad de los recordatorios:
# "¿los pacientes que reciben recordatorio faltan menos?"
# ════════════════════════════════════════════════════════════════════

def construir_resumen_whatsapp(eventos: list[dict]) -> pd.DataFrame:
    """
    Agrupa los eventos de WhatsApp por cita y resume la interacción.

    De los 38,416 eventos, solo usamos los que tienen ref_cita válida
    (no XXX- ni vacía). Eso nos da ~70% del total.

    Para cada cita construimos un resumen:
        wa_enviado: 1 si hubo al menos un evento "enviado"
        wa_entregado: 1 si hubo al menos un evento "entregado"
        wa_leido: 1 si hubo al menos un evento "leido"
        wa_respondio: 1 si hubo al menos un evento "respuesta"
        wa_texto_respuesta: el texto de la primera respuesta (si la hay)

    Retorna un DataFrame indexado por cita_id, listo para hacer merge.
    """
    resumen = defaultdict(lambda: {
        "wa_enviado": 0,
        "wa_entregado": 0,
        "wa_leido": 0,
        "wa_respondio": 0,
        "wa_texto_respuesta": None,
    })

    for evento in eventos:
        ref = evento.get("contexto", {}).get("ref_cita")

        # Filtrar eventos sin referencia o con referencia corrupta (XXX-)
        if not ref or ref.startswith("XXX-"):
            continue

        tipo = evento["tipo"]

        if tipo == "enviado":
            resumen[ref]["wa_enviado"] = 1
        elif tipo == "entregado":
            resumen[ref]["wa_entregado"] = 1
        elif tipo == "leido":
            resumen[ref]["wa_leido"] = 1
        elif tipo == "respuesta":
            resumen[ref]["wa_respondio"] = 1
            # Guardamos el texto de la primera respuesta
            if resumen[ref]["wa_texto_respuesta"] is None:
                resumen[ref]["wa_texto_respuesta"] = evento["mensaje"].get("cuerpo")

    # Convertir a DataFrame
    df_wa = pd.DataFrame.from_dict(resumen, orient="index")
    df_wa.index.name = "cita_id"
    df_wa = df_wa.reset_index()

    return df_wa


# ════════════════════════════════════════════════════════════════════
# TABLA DE HECHOS: fact_citas
#
# Es la tabla central del modelo. Cada fila es una cita con todas
# las métricas calculadas. Las dimensiones se consultan haciendo
# join por los IDs (paciente_id, medico_id, especialidad_id, etc.)
# ════════════════════════════════════════════════════════════════════

def construir_fact_citas(df: pd.DataFrame, df_wa: pd.DataFrame) -> pd.DataFrame:
    """
    Construye la tabla de hechos de citas.

    Toma la tabla limpia y le agrega:
    1. Datos de interacción WhatsApp (cruce por cita_id)
    2. Métricas calculadas:
       - es_cita_efectiva: 1 si la cita entra en el denominador del ausentismo
         (estado ATENDIDA o NO_ASISTIO, sin anomalía temporal)
       - es_ausentismo: 1 si el paciente no asistió
         (estado NO_ASISTIO y es cita efectiva)
    3. Campos temporales derivados para facilitar el análisis:
       - anio, mes, dia_semana, hora_cita

    El left join con WhatsApp asegura que las citas sin evento de
    recordatorio se conservan con valores 0 (no se pierde ninguna cita).
    """
    # ── Cruzar con WhatsApp ──
    # Left join: todas las citas se conservan. Las que no tienen
    # evento WhatsApp quedan con NaN, que llenamos con 0.
    fact = df.merge(df_wa, on="cita_id", how="left")

    columnas_wa = ["wa_enviado", "wa_entregado", "wa_leido", "wa_respondio"]
    for col in columnas_wa:
        fact[col] = fact[col].fillna(0).astype(int)

    # ── Calcular métricas de ausentismo ──

    # es_cita_efectiva: ¿esta cita entra en el cálculo de ausentismo?
    # Sí, solo si tiene un desenlace definitivo (ATENDIDA o NO_ASISTIO)
    # y no tiene anomalía temporal (cita futura marcada como terminada).
    fact["es_cita_efectiva"] = (
        fact["estado"].isin(ESTADOS_EFECTIVOS)
        & (fact["flag_anomalia_temporal"] == 0)
    ).astype(int)

    # es_ausentismo: ¿el paciente no asistió?
    # Solo vale 1 si la cita es efectiva Y el estado es NO_ASISTIO.
    fact["es_ausentismo"] = (
        (fact["estado"] == "NO_ASISTIO")
        & (fact["es_cita_efectiva"] == 1)
    ).astype(int)

    # ── Campos temporales derivados ──
    # Facilitan análisis como "ausentismo por día de la semana" o
    # "ausentismo por hora del día" sin tener que extraer en cada consulta.
    fact["anio"] = fact["fecha_cita"].dt.year
    fact["mes"] = fact["fecha_cita"].dt.month
    fact["dia_semana"] = fact["fecha_cita"].dt.day_name()
    fact["hora_cita"] = fact["fecha_cita"].dt.hour

    # ── Calcular días de anticipación del agendamiento ──
    # ¿Cuántos días antes de la cita se agendó?
    # Útil para el modelo predictivo: ¿las citas agendadas con poca
    # anticipación tienen más ausentismo?
    fact["dias_anticipacion"] = (
        fact["fecha_cita"] - fact["fecha_creacion"]
    ).dt.days

    return fact


# ════════════════════════════════════════════════════════════════════
# TABLAS DE DIMENSIONES
#
# Cada dimensión es un catálogo con un ID único. Permiten analizar
# los hechos desde diferentes ángulos sin duplicar información.
# ════════════════════════════════════════════════════════════════════

def construir_dim_paciente(df: pd.DataFrame) -> pd.DataFrame:
    """
    Dimensión de pacientes.

    Un paciente puede tener varias citas a lo largo del tiempo. Sus datos
    demográficos (edad, localidad) pueden cambiar entre citas. Tomamos
    los datos de la cita más reciente como los "vigentes".

    Columnas: paciente_id, edad, sexo, regimen, localidad
    """
    # Ordenar por fecha de cita descendente para que la primera fila
    # de cada paciente sea la cita más reciente.
    df_sorted = df.sort_values("fecha_cita", ascending=False)

    dim = df_sorted.drop_duplicates(subset=["paciente_id"], keep="first")[
        ["paciente_id", "edad", "sexo", "regimen", "localidad"]
    ].copy()

    dim = dim.reset_index(drop=True)
    return dim


def construir_dim_especialidad(df: pd.DataFrame) -> pd.DataFrame:
    """
    Dimensión de especialidades médicas.

    Catálogo simple: un ID numérico secuencial por cada especialidad
    única encontrada en los datos. El ID numérico es más eficiente
    que el texto para joins y agrupaciones.

    Columnas: especialidad_id, especialidad
    """
    especialidades = sorted(df["especialidad"].unique())
    dim = pd.DataFrame({
        "especialidad_id": range(1, len(especialidades) + 1),
        "especialidad": especialidades,
    })
    return dim


def construir_dim_sede(df: pd.DataFrame) -> pd.DataFrame:
    """
    Dimensión de sedes.

    Cada sede pertenece a una IPS. Esta dimensión permite analizar
    el ausentismo por sede y por IPS.

    Columnas: sede_id, sede, ips
    """
    sedes = df[["sede", "ips"]].drop_duplicates().sort_values(["ips", "sede"])
    sedes = sedes.reset_index(drop=True)
    sedes.insert(0, "sede_id", range(1, len(sedes) + 1))
    return sedes


def construir_dim_tiempo(df: pd.DataFrame) -> pd.DataFrame:
    """
    Dimensión de tiempo.

    Una fila por cada fecha-hora única de cita. Descompone la fecha
    en sus componentes para facilitar análisis temporales:
    - ¿Hay más ausentismo los lunes que los viernes?
    - ¿Las citas de la mañana tienen menos ausentismo?
    - ¿Qué meses son peores?

    Columnas: fecha_cita, fecha (solo fecha), anio, mes, dia, dia_semana,
              hora, es_fin_de_semana
    """
    fechas_unicas = df["fecha_cita"].drop_duplicates().sort_values()

    dim = pd.DataFrame({"fecha_cita": fechas_unicas})
    dim["fecha"] = dim["fecha_cita"].dt.date
    dim["anio"] = dim["fecha_cita"].dt.year
    dim["mes"] = dim["fecha_cita"].dt.month
    dim["dia"] = dim["fecha_cita"].dt.day
    dim["dia_semana"] = dim["fecha_cita"].dt.day_name()
    dim["hora"] = dim["fecha_cita"].dt.hour
    dim["es_fin_de_semana"] = dim["fecha_cita"].dt.dayofweek.isin([5, 6]).astype(int)

    dim = dim.reset_index(drop=True)
    return dim


# ════════════════════════════════════════════════════════════════════
# REPORTE DE AUSENTISMO
#
# Con la fact_citas construida, calculamos la tasa de ausentismo
# por IPS para responder la pregunta del comité.
# ════════════════════════════════════════════════════════════════════

def reportar_ausentismo(fact: pd.DataFrame):
    """
    Calcula y muestra la tasa de ausentismo por IPS y consolidada.

    Fórmula: NO_ASISTIO / (ATENDIDA + NO_ASISTIO)
    Solo se consideran citas efectivas (sin anomalía temporal).
    """
    print("\n── Tasa de ausentismo ──")
    print("  Fórmula: NO_ASISTIO / (ATENDIDA + NO_ASISTIO)")
    print("  Excluye: PENDIENTE, CONFIRMADA, CANCELADA, REAGENDADA,")
    print("           y citas con anomalía temporal.\n")

    # Por IPS
    for ips in ["Norte", "Sur", "Occidente"]:
        df_ips = fact[fact["ips"] == ips]
        efectivas = df_ips["es_cita_efectiva"].sum()
        ausentes = df_ips["es_ausentismo"].sum()
        tasa = 100 * ausentes / efectivas if efectivas > 0 else 0
        print(f"  {ips:<12} {ausentes:>5} ausentes / {efectivas:>5} efectivas = {tasa:.1f}%")

    # Consolidado
    efectivas_total = fact["es_cita_efectiva"].sum()
    ausentes_total = fact["es_ausentismo"].sum()
    tasa_total = 100 * ausentes_total / efectivas_total if efectivas_total > 0 else 0
    print(f"  {'TOTAL':<12} {ausentes_total:>5} ausentes / {efectivas_total:>5} efectivas = {tasa_total:.1f}%")

    # Efectividad de recordatorios
    print("\n── Efecto de los recordatorios por WhatsApp ──")
    efectivas = fact[fact["es_cita_efectiva"] == 1]

    con_wa = efectivas[efectivas["wa_enviado"] == 1]
    sin_wa = efectivas[efectivas["wa_enviado"] == 0]

    if len(con_wa) > 0:
        tasa_con = 100 * con_wa["es_ausentismo"].sum() / len(con_wa)
    else:
        tasa_con = 0
    if len(sin_wa) > 0:
        tasa_sin = 100 * sin_wa["es_ausentismo"].sum() / len(sin_wa)
    else:
        tasa_sin = 0

    print(f"  Con recordatorio enviado: {tasa_con:.1f}% ausentismo ({len(con_wa):,} citas)")
    print(f"  Sin recordatorio enviado: {tasa_sin:.1f}% ausentismo ({len(sin_wa):,} citas)")

    if tasa_sin > 0:
        reduccion = tasa_sin - tasa_con
        print(f"  Diferencia: {reduccion:+.1f} puntos porcentuales")


# ════════════════════════════════════════════════════════════════════
# EJECUCIÓN PRINCIPAL
# ════════════════════════════════════════════════════════════════════

def main():
    print("=" * 60)
    print("CAPA DE CONSUMO — Modelo dimensional + métricas")
    print("=" * 60)

    CONSUMO_DIR.mkdir(parents=True, exist_ok=True)

    # ── Cargar fuentes ──
    print("\nCargando datos...")
    df = cargar_citas_limpias()
    print(f"  Citas limpias: {len(df):,} registros")

    eventos = cargar_eventos_whatsapp()
    print(f"  Eventos WhatsApp: {len(eventos):,} registros")

    # ── Cruce con WhatsApp ──
    print("\nConstruyendo resumen de WhatsApp por cita...")
    df_wa = construir_resumen_whatsapp(eventos)
    print(f"  Citas con evento WhatsApp válido: {len(df_wa):,}")

    # ── Tabla de hechos ──
    print("\nConstruyendo fact_citas...")
    fact = construir_fact_citas(df, df_wa)
    fact.to_csv(CONSUMO_DIR / "fact_citas.csv", index=False, encoding="utf-8")
    print(f"  fact_citas: {len(fact):,} filas, {len(fact.columns)} columnas")

    # ── Dimensiones ──
    print("\nConstruyendo dimensiones...")

    dim_paciente = construir_dim_paciente(df)
    dim_paciente.to_csv(CONSUMO_DIR / "dim_paciente.csv", index=False, encoding="utf-8")
    print(f"  dim_paciente: {len(dim_paciente):,} pacientes únicos")

    dim_especialidad = construir_dim_especialidad(df)
    dim_especialidad.to_csv(CONSUMO_DIR / "dim_especialidad.csv", index=False, encoding="utf-8")
    print(f"  dim_especialidad: {len(dim_especialidad)} especialidades")

    dim_sede = construir_dim_sede(df)
    dim_sede.to_csv(CONSUMO_DIR / "dim_sede.csv", index=False, encoding="utf-8")
    print(f"  dim_sede: {len(dim_sede)} sedes")

    dim_tiempo = construir_dim_tiempo(df)
    dim_tiempo.to_csv(CONSUMO_DIR / "dim_tiempo.csv", index=False, encoding="utf-8")
    print(f"  dim_tiempo: {len(dim_tiempo):,} fechas-hora únicas")

    # ── Reporte de ausentismo ──
    reportar_ausentismo(fact)

    # ── Resumen final ──
    print(f"\n{'=' * 60}")
    print("ARCHIVOS GENERADOS")
    print(f"{'=' * 60}")
    for f in sorted(CONSUMO_DIR.glob("*.csv")):
        size_kb = f.stat().st_size / 1024
        print(f"  {f.name} ({size_kb:.0f} KB)")


if __name__ == "__main__":
    main()
