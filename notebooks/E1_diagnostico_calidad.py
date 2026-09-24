"""
E1 — Diagnóstico y Calidad de Datos
=====================================

Este script analiza la extracción piloto de tres IPS clientes de DonDoctor
y los eventos de WhatsApp. El objetivo es entender qué tenemos, qué problemas
hay, y qué tan confiables son estos datos para calcular el ausentismo.

La extracción fue realizada el 30 de junio de 2026 a las 23:59 (hora Colombia).

Fuentes analizadas:
  - ips_norte_citas.csv    → Citas de la IPS Norte (CSV con coma)
  - ips_sur_citas.csv      → Citas de la IPS Sur (CSV con coma)
  - ips_occidente_citas.csv → Citas de la IPS Occidente (CSV con punto y coma)
  - whatsapp_eventos.jsonl  → Eventos de recordatorios por WhatsApp (JSON Lines)

Ejecutar desde la raíz del proyecto:
    python notebooks/E1_diagnostico_calidad.py
"""

import pandas as pd
import json
import sys
from pathlib import Path
from collections import Counter
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = Path(__file__).resolve().parent.parent
RAW_DIR = BASE_DIR / "data" / "raw"
CLEAN_DIR = BASE_DIR / "data" / "clean"

# Fecha de corte: la extracción se hizo el 30 de junio de 2026 según el diccionario.
# Cualquier cita con fecha posterior a esta no debería tener estado terminal.
FECHA_EXTRACCION = pd.Timestamp("2026-06-30 23:59:59")

# Estados que documenta el diccionario de datos oficial
ESTADOS_DOCUMENTADOS = {"PENDIENTE", "CONFIRMADA", "ATENDIDA", "NO_ASISTIO", "CANCELADA"}


# ════════════════════════════════════════════════════════════════════
# PARTE 1: PERFILAMIENTO
#
# Antes de buscar problemas, necesitamos saber qué tenemos:
# cuántos registros, qué campos, qué tan completos están,
# y cómo se distribuyen los valores clave.
# ════════════════════════════════════════════════════════════════════

print("=" * 70)
print("PARTE 1: PERFILAMIENTO DE FUENTES")
print("=" * 70)


# ── 1.1 Carga de datos ──────────────────────────────────────────────
# Cada IPS viene de un SQL Server diferente. Cargamos los archivos raw
# (sin transformar) para perfilar exactamente lo que nos entregaron.
# Nota: Occidente usa punto y coma como separador — si no se especifica,
# pandas lo lee como una sola columna.

df_norte = pd.read_csv(RAW_DIR / "ips_norte_citas.csv", encoding="utf-8")
df_sur = pd.read_csv(RAW_DIR / "ips_sur_citas.csv", encoding="utf-8")
df_occidente = pd.read_csv(
    RAW_DIR / "ips_occidente_citas.csv", sep=";", encoding="utf-8"
)

with open(RAW_DIR / "whatsapp_eventos.jsonl", "r", encoding="utf-8") as f:
    eventos_wa = [json.loads(line) for line in f]


# ── 1.1 Volumen ─────────────────────────────────────────────────────
# Lo primero: ¿cuántos datos tenemos de cada fuente?

print("\n── 1.1 Volumen por fuente ──")
print(f"  IPS Norte:          {len(df_norte):>6,} filas, {len(df_norte.columns)} columnas")
print(f"  IPS Sur:            {len(df_sur):>6,} filas, {len(df_sur.columns)} columnas")
print(f"  IPS Occidente:      {len(df_occidente):>6,} filas, {len(df_occidente.columns)} columnas")
print(f"  WhatsApp eventos:   {len(eventos_wa):>6,} registros")
print(f"  Total citas:        {len(df_norte) + len(df_sur) + len(df_occidente):>6,}")


# ── 1.2 Comparación de esquemas ─────────────────────────────────────
# Cada IPS tiene su propio SQL Server. Si los esquemas no coinciden,
# no podemos consolidar directamente. Comparamos columna por columna.

print("\n── 1.2 Comparación de esquemas ──")
print(f"\n  Norte ({len(df_norte.columns)} cols): {list(df_norte.columns)}")
print(f"\n  Sur ({len(df_sur.columns)} cols):   {list(df_sur.columns)}")
print(f"    ⚠ Sur tiene 2 columnas extra: documento_identidad y telefono")
print(f"      Estas contienen datos personales reales (cédula y celular)")
print(f"\n  Occidente ({len(df_occidente.columns)} cols): {list(df_occidente.columns)}")
print(f"    ⚠ Occidente usa nombres completamente diferentes:")
print(f"      id_cita (vs cita_id), genero (vs sexo), estado_cita (vs estado), etc.")


# ── 1.3 Completitud ─────────────────────────────────────────────────
# ¿Qué porcentaje de cada columna tiene datos? Los campos con muchos
# nulos no son necesariamente un problema: motivo_cierre solo aplica
# a citas cerradas, y cita_origen_id solo aplica a reagendamientos.

print("\n── 1.3 Completitud — Campos con nulos ──")

def mostrar_nulos(df, nombre):
    """Muestra solo las columnas que tienen al menos un nulo."""
    print(f"\n  {nombre} ({len(df):,} filas):")
    total = len(df)
    tiene_nulos = False
    for col in df.columns:
        nulos = df[col].isnull().sum()
        if nulos > 0:
            tiene_nulos = True
            print(f"    {col:<25} {nulos:>5} nulos ({100*nulos/total:.1f}%)")
    if not tiene_nulos:
        print(f"    Todas las columnas están 100% completas")

mostrar_nulos(df_norte, "IPS Norte")
mostrar_nulos(df_sur, "IPS Sur")
mostrar_nulos(df_occidente, "IPS Occidente")

print("\n  Nota: motivo_cierre, observaciones y cita_origen_id tienen ~80-95%")
print("  de nulos en las 3 IPS. Esto es esperado porque solo se llenan cuando")
print("  la cita se cierra con un motivo específico o es una reprogramación.")


# ── 1.4 Distribución de estados ─────────────────────────────────────
# El estado de la cita es el campo más importante para calcular el
# ausentismo. Necesitamos saber qué valores existen y en qué proporción.
# Además, Occidente codifica los estados de forma abreviada (ATD, NAS, etc.)

print("\n── 1.4 Distribución de estados ──")

for nombre, df_temp, col_estado in [
    ("Norte", df_norte, "estado"),
    ("Sur", df_sur, "estado"),
    ("Occidente", df_occidente, "estado_cita"),
]:
    print(f"\n  {nombre}:")
    total = len(df_temp)
    for estado, count in df_temp[col_estado].value_counts().items():
        print(f"    {estado:<15} {count:>5} ({100*count/total:.1f}%)")

print("\n  Nota: Occidente usa abreviaturas → ATD=ATENDIDA, NAS=NO_ASISTIO,")
print("  CAN=CANCELADA, REP=REAGENDADA, PEN=PENDIENTE, CONF=CONFIRMADA.")
print("  El estado REAGENDADA/REP no aparece en el diccionario oficial.")


# ── 1.5 Distribución demográfica ────────────────────────────────────
# Sexo, edad y régimen son relevantes para segmentar el ausentismo
# y para el modelo predictivo (E5).

print("\n── 1.5 Distribución de sexo ──")
print(f"  Norte:     {dict(df_norte['sexo'].value_counts())}  → Codifica como M/F")
print(f"  Sur:       {dict(df_sur['sexo'].value_counts())}  → Codifica como M/F")
print(f"  Occidente: {dict(df_occidente['genero'].value_counts())}  → Codifica como Femenino/Masculino")

print("\n── 1.6 Estadísticas de edad ──")
for nombre, df_temp, col in [("Norte", df_norte, "edad"),
                              ("Sur", df_sur, "edad"),
                              ("Occidente", df_occidente, "edad_paciente")]:
    print(f"  {nombre}: min={df_temp[col].min()}, max={df_temp[col].max()}, "
          f"mediana={df_temp[col].median():.0f}, media={df_temp[col].mean():.1f}")
print("  ⚠ Las 3 IPS tienen min=-1 y max=999 (valores claramente anómalos)")

print("\n── 1.7 Distribución de régimen ──")
for nombre, df_temp, col in [("Norte", df_norte, "regimen"),
                              ("Sur", df_sur, "regimen"),
                              ("Occidente", df_occidente, "regimen_salud")]:
    print(f"  {nombre}: {dict(df_temp[col].value_counts())}")

print("\n── 1.8 Canales de agendamiento ──")
for nombre, df_temp in [("Norte", df_norte), ("Sur", df_sur), ("Occidente", df_occidente)]:
    print(f"  {nombre}: {dict(df_temp['canal_agendamiento'].value_counts())}")


# ── 1.9 Rango temporal ──────────────────────────────────────────────
# La extracción fue el 30/jun/2026. Esperamos citas desde ~jul/2025
# (un año de datos) hasta esa fecha. Citas posteriores son futuras
# al momento de la extracción.

print("\n── 1.9 Rango temporal de las citas ──")
for nombre, df_temp, col in [("Norte", df_norte, "fecha_cita"),
                              ("Sur", df_sur, "fecha_cita"),
                              ("Occidente", df_occidente, "fecha_hora_cita")]:
    fechas = pd.to_datetime(df_temp[col])
    print(f"  {nombre}: {fechas.min()} → {fechas.max()}")
print(f"  Fecha de extracción: {FECHA_EXTRACCION}")
print("  ⚠ Las 3 IPS tienen citas hasta agosto 2026, es decir, hay citas")
print("  programadas a futuro (después de la extracción). Eso es normal.")
print("  Lo anómalo es que algunas de esas citas futuras tengan estado ATENDIDA.")


# ── 1.10 Perfilamiento de WhatsApp ──────────────────────────────────
# Los eventos de WhatsApp registran el ciclo de vida de cada mensaje
# de recordatorio: enviado → entregado → leído → respuesta.
# El campo contexto.ref_cita vincula el evento con una cita específica.

print("\n── 1.10 Perfilamiento de eventos WhatsApp ──")

tipos = Counter(e["tipo"] for e in eventos_wa)
print(f"  Tipos de evento:")
for tipo, count in sorted(tipos.items(), key=lambda x: -x[1]):
    print(f"    {tipo:<12} {count:>6} ({100*count/len(eventos_wa):.1f}%)")

ips_dist = Counter(e["contexto"].get("ips") for e in eventos_wa)
print(f"\n  Por IPS:")
for ips, count in sorted(ips_dist.items(), key=lambda x: -x[1]):
    print(f"    {ips:<12} {count:>6}")

con_ref = sum(1 for e in eventos_wa if "ref_cita" in e.get("contexto", {}))
print(f"\n  Vinculación con citas:")
print(f"    Con ref_cita:  {con_ref:>6} ({100*con_ref/len(eventos_wa):.1f}%)")
print(f"    Sin ref_cita:  {len(eventos_wa)-con_ref:>6} ({100*(len(eventos_wa)-con_ref)/len(eventos_wa):.1f}%)")

ts_min = min(e["ts"] for e in eventos_wa)
ts_max = max(e["ts"] for e in eventos_wa)
print(f"\n  Rango temporal: {datetime.fromtimestamp(ts_min/1000)} → {datetime.fromtimestamp(ts_max/1000)}")

# Respuestas de pacientes — útil para entender confirmaciones
respuestas = [e for e in eventos_wa if e["tipo"] == "respuesta"]
cuerpos = Counter(e["mensaje"].get("cuerpo", "") for e in respuestas)
print(f"\n  Respuestas de pacientes ({len(respuestas)} total), textos más frecuentes:")
for texto, count in cuerpos.most_common(5):
    print(f"    \"{texto}\" → {count} veces")


# ════════════════════════════════════════════════════════════════════
# PARTE 2: HALLAZGOS
#
# Cada hallazgo sigue la estructura:
#   - Qué encontramos (descripción)
#   - Cuántos registros afecta (evidencia cuantitativa)
#   - Por qué importa para el negocio (impacto)
#   - Qué hacer al respecto (tratamiento propuesto)
# ════════════════════════════════════════════════════════════════════

print("\n" + "=" * 70)
print("PARTE 2: HALLAZGOS DE CALIDAD")
print("=" * 70)

# Usamos el consolidado (ya unificado) para los análisis cruzados
df = pd.read_csv(CLEAN_DIR / "citas_consolidado.csv", encoding="utf-8")
df["fecha_cita"] = pd.to_datetime(df["fecha_cita"])
df["fecha_creacion"] = pd.to_datetime(df["fecha_creacion"])
df["fecha_actualizacion"] = pd.to_datetime(df["fecha_actualizacion"])


# ── HALLAZGO 1 ──────────────────────────────────────────────────────
# Las 3 IPS vienen de SQL Servers independientes. Cada una nombra sus
# columnas distinto, codifica estados distinto, y hasta usa un separador
# de CSV diferente. Sin homologación, no se pueden comparar.

print("\n── H1: Esquemas heterogéneos entre IPS ──")
print("  Problema: Cada IPS estructura sus datos de forma diferente.")
print("  Ejemplos concretos:")
print("    ┌────────────────┬──────────────────┬──────────────────┐")
print("    │ Concepto       │ Norte / Sur       │ Occidente        │")
print("    ├────────────────┼──────────────────┼──────────────────┤")
print("    │ ID cita        │ cita_id           │ id_cita          │")
print("    │ Fecha cita     │ fecha_cita        │ fecha_hora_cita  │")
print("    │ Estado         │ ATENDIDA          │ ATD              │")
print("    │ Sexo           │ F / M             │ Femenino / Masc. │")
print("    │ Separador CSV  │ coma (,)          │ punto y coma (;) │")
print("    │ Formato fecha  │ 2026-03-14 13:40  │ 2026-03-14T13:40 │")
print("    └────────────────┴──────────────────┴──────────────────┘")
print(f"  Registros afectados: {len(df_occidente):,} (toda la IPS Occidente)")
print("  Impacto: Imposible consolidar o comparar IPS sin transformación previa.")
print("  Tratamiento: Resuelto en src/unificar_datos.py con mapeo de columnas,")
print("  estados y valores de sexo a un esquema canónico.")


# ── HALLAZGO 2 ──────────────────────────────────────────────────────
# IPS Sur incluye número de cédula y teléfono celular. Esto es un dato
# personal sensible protegido por la Ley 1581 de 2012 en Colombia.
# Las otras dos IPS no envían estos campos.

print("\n── H2: Datos personales expuestos en IPS Sur ──")
print("  Problema: IPS Sur incluye documento_identidad (cédula) y teléfono")
print("  del paciente. Norte y Occidente no traen estos campos.")
n_docs = df_sur["documento_identidad"].notna().sum()
n_tels = df_sur["telefono"].notna().sum()
print(f"  Evidencia:")
print(f"    documento_identidad: {n_docs:,} registros con valor (100%)")
print(f"    telefono:            {n_tels:,} registros con valor (100%)")
print(f"    Ejemplo: cédula={df_sur['documento_identidad'].iloc[0]}, "
      f"tel={df_sur['telefono'].iloc[0]}")
print("  Impacto: Riesgo legal (Ley 1581/2012 de protección de datos personales).")
print("  Estos campos NO deben almacenarse en un data warehouse sin autorización")
print("  del titular ni controles de acceso adecuados.")
print("  Tratamiento: Eliminados en la capa limpia. Se debe alertar al equipo de")
print("  TI de IPS Sur para que revise su extracción.")


# ── HALLAZGO 3 ──────────────────────────────────────────────────────
# La edad debería estar entre 0 (recién nacido) y ~110 años.
# Encontramos valores de -1 y 999, que parecen ser convenciones del
# sistema para "no informado" o "no aplica".

print("\n── H3: Edades anómalas (-1 y 999) ──")
anomalas = df[(df["edad"] < 0) | (df["edad"] > 120)]
print(f"  Problema: Hay {len(anomalas)} registros con edades imposibles.")
print(f"  Valores encontrados: {sorted(anomalas['edad'].unique().tolist())}")
print(f"  Distribución por IPS:")
for ips in ["Norte", "Sur", "Occidente"]:
    n = len(anomalas[anomalas["ips"] == ips])
    total_ips = len(df[df["ips"] == ips])
    # Cuántos son -1 y cuántos son 999
    n_neg = len(anomalas[(anomalas["ips"] == ips) & (anomalas["edad"] == -1)])
    n_999 = len(anomalas[(anomalas["ips"] == ips) & (anomalas["edad"] == 999)])
    print(f"    {ips}: {n} registros ({n_neg} con edad=-1, {n_999} con edad=999)")
print(f"  Porcentaje del total: {100*len(anomalas)/len(df):.2f}%")
print("  Impacto: Distorsiona la edad promedio (la infla por los 999) y afecta")
print("  cualquier segmentación por grupo etario o modelo predictivo.")
print("  Tratamiento: Reemplazar por nulo (NaN). Preguntar al dueño del dato")
print("  si -1 significa 'no informado' para documentarlo formalmente.")


# ── HALLAZGO 4 ──────────────────────────────────────────────────────
# Un cita_id debería ser único: una cita = un registro.
# En Norte encontramos 197 IDs que aparecen duplicados. Algunos tienen
# estados diferentes (ej: uno dice CONFIRMADA y otro ATENDIDA), lo que
# sugiere que el sistema guarda versiones históricas del registro.

print("\n── H4: Duplicados de cita_id en IPS Norte ──")
dupes_norte = df_norte[df_norte["cita_id"].duplicated(keep=False)].sort_values("cita_id")
n_ids_dupes = dupes_norte["cita_id"].nunique()

# Clasificar: ¿cuántos tienen estados diferentes vs. son exactamente iguales?
dupes_diff_estado = 0
for cid, group in dupes_norte.groupby("cita_id"):
    if group["estado"].nunique() > 1:
        dupes_diff_estado += 1

print(f"  Problema: {n_ids_dupes} cita_id aparecen más de una vez.")
print(f"  Total filas involucradas: {len(dupes_norte)}")
print(f"  Con estados diferentes entre copias: {dupes_diff_estado}")
print(f"  Con mismo estado (duplicados exactos): {n_ids_dupes - dupes_diff_estado}")

# Mostrar un ejemplo concreto para que se entienda el problema
ejemplo = dupes_norte.groupby("cita_id").filter(
    lambda x: x["estado"].nunique() > 1
).head(4)[["cita_id", "estado", "fecha_cita", "fecha_actualizacion"]]
print(f"\n  Ejemplo — misma cita con 2 estados diferentes:")
print(f"  {ejemplo.to_string(index=False)}")
print(f"\n  Lectura: NOR-182102 aparece como CONFIRMADA (21/abr) y luego como")
print(f"  ATENDIDA (22/abr). Probablemente el paciente confirmó y luego asistió,")
print(f"  pero el sistema guardó ambas versiones en vez de actualizar.")
print("  Impacto: Infla el conteo de citas (+395 filas) y puede contar la misma")
print("  cita como asistida Y como otro estado simultáneamente.")
print("  Sur y Occidente no tienen este problema (0 duplicados).")
print("  Tratamiento: Conservar el registro con la fecha_actualizacion más reciente")
print("  (es la última versión). Si son idénticos, eliminar la copia.")


# ── HALLAZGO 5 ──────────────────────────────────────────────────────
# El diccionario de datos dice que los estados posibles son:
# PENDIENTE, CONFIRMADA, ATENDIDA, NO_ASISTIO, CANCELADA.
# Pero en los datos aparece un sexto estado: REAGENDADA (o REP en Occidente).
# Esto es crítico porque no sabemos cómo contarlo para el ausentismo.

print("\n── H5: Estado REAGENDADA no documentado ──")
estados_reales = set(df["estado"].unique())
no_documentados = estados_reales - ESTADOS_DOCUMENTADOS
reagendadas = len(df[df["estado"] == "REAGENDADA"])
print(f"  Problema: Existe un estado que no aparece en el diccionario de datos.")
print(f"  Estados documentados: {sorted(ESTADOS_DOCUMENTADOS)}")
print(f"  Estados en los datos: {sorted(estados_reales)}")
print(f"  No documentado: {no_documentados}")
print(f"  Registros con REAGENDADA: {reagendadas} ({100*reagendadas/len(df):.1f}% del total)")
print(f"  Distribución por IPS:")
for ips in ["Norte", "Sur", "Occidente"]:
    n = len(df[(df["estado"] == "REAGENDADA") & (df["ips"] == ips)])
    print(f"    {ips}: {n}")
print("  Impacto: La definición de ausentismo depende de esto. Si REAGENDADA")
print("  se cuenta como NO_ASISTIO, el ausentismo sube. Si se excluye del")
print("  denominador (como las cancelaciones), baja. Es la diferencia entre")
print("  el 12% de Comercial y el 17% de Operaciones.")
print("  Tratamiento: Preguntar al dueño del dato. Mientras tanto, calcular")
print("  el ausentismo con y sin REAGENDADA para mostrar el rango.")


# ── HALLAZGO 6 ──────────────────────────────────────────────────────
# La extracción fue el 30/jun/2026. Hay citas programadas para julio
# y agosto, lo cual es normal (citas agendadas a futuro). Lo anómalo
# es que 67 de esas citas futuras ya están marcadas como ATENDIDA.

print("\n── H6: Citas futuras con estado ATENDIDA ──")
futuras = df[df["fecha_cita"] > FECHA_EXTRACCION]
futuras_atendidas = futuras[futuras["estado"] == "ATENDIDA"]
print(f"  Problema: Hay citas con fecha posterior a la extracción (30/jun/2026)")
print(f"  que ya tienen estado ATENDIDA. Una cita que aún no ha ocurrido no")
print(f"  puede haber sido atendida.")
print(f"  Citas futuras totales: {len(futuras)}")
print(f"  De esas, marcadas ATENDIDA: {len(futuras_atendidas)}")
print(f"  Desglose por IPS:")
for ips in ["Norte", "Sur", "Occidente"]:
    n = len(futuras_atendidas[futuras_atendidas["ips"] == ips])
    print(f"    {ips}: {n}")

# ¿Qué tan lejos en el futuro están?
if len(futuras_atendidas) > 0:
    dias_futuro = (futuras_atendidas["fecha_cita"] - FECHA_EXTRACCION).dt.days
    print(f"  Días en el futuro: min={dias_futuro.min()}, max={dias_futuro.max()}, "
          f"mediana={dias_futuro.median():.0f}")

print("  Impacto: Si se incluyen en el cálculo de ausentismo, inflan la tasa")
print("  de citas atendidas de forma incorrecta.")
print("  Tratamiento: Excluir citas con fecha posterior a la extracción de las")
print("  métricas de ausentismo. Preguntar si hay un desfase de zona horaria.")


# ── HALLAZGO 7 ──────────────────────────────────────────────────────
# Los eventos de WhatsApp deberían vincularse a una cita mediante
# contexto.ref_cita. Pero el 29.5% no tiene ese campo, y un 1.9%
# tiene referencias corruptas (prefijo XXX- en vez de NOR-/SUR-/OCC-).

print("\n── H7: Referencias rotas en eventos WhatsApp ──")
refs_xxx = [e for e in eventos_wa
            if e.get("contexto", {}).get("ref_cita", "").startswith("XXX-")]
sin_ref = [e for e in eventos_wa
           if "ref_cita" not in e.get("contexto", {})]

# ¿Las refs válidas sí matchean con citas existentes?
refs_validas = set()
for e in eventos_wa:
    ref = e.get("contexto", {}).get("ref_cita")
    if ref and not ref.startswith("XXX-"):
        refs_validas.add(ref)

citas_ids = set(df["cita_id"].unique())
refs_que_existen = refs_validas & citas_ids
refs_huerfanas = refs_validas - citas_ids

print(f"  Problema: No todos los eventos de WhatsApp se pueden vincular a una cita.")
print(f"  Eventos totales: {len(eventos_wa):,}")
print(f"  Con ref_cita corrupta (XXX-): {len(refs_xxx):,} ({100*len(refs_xxx)/len(eventos_wa):.1f}%)")
print(f"  Sin ref_cita:                 {len(sin_ref):,} ({100*len(sin_ref)/len(eventos_wa):.1f}%)")
print(f"  Total no vinculables:         {len(refs_xxx)+len(sin_ref):,} ({100*(len(refs_xxx)+len(sin_ref))/len(eventos_wa):.1f}%)")
print(f"\n  Verificación de integridad referencial:")
print(f"    Refs válidas únicas:        {len(refs_validas):,}")
print(f"    Que existen en citas:       {len(refs_que_existen):,} ({100*len(refs_que_existen)/max(len(refs_validas),1):.1f}%)")
print(f"    Huérfanas (no matchean):    {len(refs_huerfanas):,}")
print("  Nota positiva: todas las refs válidas matchean al 100% con citas reales.")
print("  Impacto: El 31% de los eventos no se puede usar para medir si el")
print("  recordatorio por WhatsApp reduce el ausentismo.")
print("  Tratamiento: Usar solo eventos con match confirmado. Preguntar qué")
print("  significa XXX- y por qué hay eventos sin ref_cita.")


# ── HALLAZGO 8 ──────────────────────────────────────────────────────
# Las citas tienen un campo recordatorio_enviado (1/0). Cruzamos
# ese campo contra los eventos reales de WhatsApp para verificar
# si son consistentes.

print("\n── H8: Inconsistencia entre recordatorio_enviado y eventos WhatsApp ──")
citas_con_flag = set(df[df["recordatorio_enviado"] == 1]["cita_id"])
citas_con_evento = set()
for e in eventos_wa:
    ref = e.get("contexto", {}).get("ref_cita")
    if ref and not ref.startswith("XXX-"):
        citas_con_evento.add(ref)

solo_flag = citas_con_flag - citas_con_evento
solo_evento = citas_con_evento - citas_con_flag
en_ambos = citas_con_flag & citas_con_evento

print(f"  Cruce entre la flag en citas y los eventos reales de WhatsApp:")
print(f"    Citas con recordatorio_enviado=1:   {len(citas_con_flag):,}")
print(f"    Citas con evento WhatsApp real:      {len(citas_con_evento):,}")
print(f"    Coinciden (en ambas fuentes):        {len(en_ambos):,}")
print(f"    Solo en flag (dice enviado, no hay evento): {len(solo_flag)}")
print(f"    Solo en WhatsApp (hay evento, flag=0):      {len(solo_evento)}")
print("  Impacto: Hay 402 citas que dicen que se envió recordatorio pero no")
print("  existe el evento correspondiente en WhatsApp. La flag no es 100% confiable.")
print("  Tratamiento: Para análisis de efectividad de recordatorios, usar los")
print("  eventos de WhatsApp como fuente de verdad, no la flag.")


# ── HALLAZGO 9 ──────────────────────────────────────────────────────
# Lógicamente, una cita se crea (fecha_creacion) ANTES de que ocurra
# (fecha_cita). Si encontramos lo contrario, puede indicar un registro
# retroactivo o un error de timestamp.

print("\n── H9: Citas creadas después de su fecha programada ──")
creacion_despues = df[df["fecha_creacion"] > df["fecha_cita"]]
print(f"  Problema: {len(creacion_despues)} registros donde fecha_creacion > fecha_cita")
print(f"  Porcentaje: {100*len(creacion_despues)/len(df):.2f}%")
print(f"  Por IPS:")
for ips in ["Norte", "Sur", "Occidente"]:
    n = len(creacion_despues[creacion_despues["ips"] == ips])
    print(f"    {ips}: {n}")

# ¿Cuántos días de diferencia?
if len(creacion_despues) > 0:
    diff_dias = (creacion_despues["fecha_creacion"] - creacion_despues["fecha_cita"]).dt.total_seconds() / 3600
    print(f"  Diferencia (horas): min={diff_dias.min():.1f}, max={diff_dias.max():.1f}, "
          f"mediana={diff_dias.median():.1f}")

print("  Impacto: Bajo. Podría ser registro retroactivo (cita de urgencia")
print("  registrada después) o desfase de timezone.")
print("  Tratamiento: Marcar para revisión, no excluir.")


# ════════════════════════════════════════════════════════════════════
# PARTE 3: RESUMEN DE HALLAZGOS
# ════════════════════════════════════════════════════════════════════

print("\n" + "=" * 70)
print("PARTE 3: TABLA RESUMEN DE HALLAZGOS")
print("=" * 70)

hallazgos = [
    ("H1", "Esquemas heterogéneos entre IPS", f"{len(df_occidente):,}", "ALTO", "Resuelto en unificación"),
    ("H2", "Datos personales en IPS Sur (cédula, tel)", f"{len(df_sur):,}", "CRÍTICO", "Eliminados en capa limpia"),
    ("H3", "Edades anómalas (-1 y 999)", f"{len(anomalas)}", "MEDIO", "Reemplazar por nulo"),
    ("H4", "Duplicados cita_id en Norte", f"{len(dupes_norte)}", "ALTO", "Deduplicar por fecha más reciente"),
    ("H5", "Estado REAGENDADA no documentado", f"{reagendadas}", "ALTO", "Consultar al dueño del dato"),
    ("H6", "Citas futuras marcadas ATENDIDA", f"{len(futuras_atendidas)}", "MEDIO", "Excluir de métricas"),
    ("H7", "Refs rotas/faltantes en WhatsApp", f"{len(refs_xxx)+len(sin_ref):,}", "ALTO", "Usar solo eventos con match"),
    ("H8", "Flag recordatorio inconsistente", f"{len(solo_flag)}", "MEDIO", "Usar WhatsApp como fuente real"),
    ("H9", "Fecha creación > fecha cita", f"{len(creacion_despues)}", "BAJO", "Marcar, no excluir"),
]

print(f"\n  {'ID':<4} {'Hallazgo':<43} {'Volumen':>8} {'Severidad':<10} {'Tratamiento'}")
print("  " + "─" * 110)
for h in hallazgos:
    print(f"  {h[0]:<4} {h[1]:<43} {h[2]:>8} {h[3]:<10} {h[4]}")


# ════════════════════════════════════════════════════════════════════
# PARTE 4: REGLAS DE CALIDAD AUTOMATIZABLES
#
# Estas reglas se implementarán como pruebas (tests/) que corran cada
# vez que se ingeste un nuevo lote. Si un lote viola una regla, el
# pipeline falla antes de contaminar la capa limpia.
# ════════════════════════════════════════════════════════════════════

print("\n" + "=" * 70)
print("PARTE 4: REGLAS DE CALIDAD")
print("=" * 70)

print("""
  Cada regla se ejecuta automáticamente al ingestar datos nuevos.
  Si falla, el pipeline se detiene antes de escribir en la capa limpia.

  R1. ESQUEMA CANÓNICO
      Toda fuente debe mapearse al esquema de 20 columnas estándar.
      → Falla si hay columnas faltantes o no reconocidas.

  R2. PRIVACIDAD
      La capa limpia no debe contener documento_identidad, teléfono,
      ni ningún identificador directo del paciente.
      → Falla si se detecta alguno.

  R3. RANGO DE EDAD
      La edad debe estar entre 0 y 120 años.
      → Registros fuera de rango se convierten a nulo, no se eliminan.

  R4. UNICIDAD DE CITA
      Cada cita_id debe aparecer una sola vez por IPS.
      → Falla si hay duplicados después de la deduplicación.

  R5. CATÁLOGO DE ESTADOS
      Solo se aceptan: PENDIENTE, CONFIRMADA, ATENDIDA, NO_ASISTIO,
      CANCELADA, REAGENDADA.
      → Falla si aparece un valor fuera del catálogo.

  R6. ORDEN TEMPORAL
      fecha_creacion debe ser anterior o igual a fecha_cita.
      → Los registros que violen esto se marcan (flag), no se eliminan.

  R7. COHERENCIA ESTADO-FECHA
      Citas con fecha_cita futura (> fecha de ejecución del pipeline)
      no pueden tener estado ATENDIDA ni NO_ASISTIO.
      → Falla si se detectan.

  R8. INTEGRIDAD REFERENCIAL WHATSAPP
      Cada ref_cita en los eventos debe existir como cita_id en alguna IPS.
      Eventos sin match se marcan como "no vinculable", no se eliminan.

  R9. COMPLETITUD OBLIGATORIA
      Los campos cita_id, paciente_id, fecha_cita, estado y especialidad
      deben tener 0% de nulos.
      → Falla si hay algún nulo en estos campos.
""")


# ════════════════════════════════════════════════════════════════════
# PARTE 5: PREGUNTAS AL DUEÑO DEL DATO
#
# Máximo 8 preguntas, priorizadas por impacto en el cálculo del
# ausentismo y en la confiabilidad de las métricas.
# Redactadas como las enviaríamos realmente al equipo de TI.
# ════════════════════════════════════════════════════════════════════

print("=" * 70)
print("PARTE 5: PREGUNTAS AL DUEÑO DEL DATO (máx. 8, priorizadas)")
print("=" * 70)

print("""
  Priorizadas por impacto en la métrica de ausentismo:

  1. REAGENDADA — ¿qué significa exactamente?
     En los datos aparece un estado REAGENDADA que no está en el
     diccionario. Necesito saber: ¿la cita original se cierra como
     NO_ASISTIO, como CANCELADA, o queda en un estado neutro?
     ¿Se genera un nuevo cita_id para la cita reprogramada?
     Impacto: Define cómo calcular el ausentismo. (Ref: H5)

  2. DEFINICIÓN DE AUSENTISMO — ¿hay una oficial?
     Gerencia dice una cosa, Comercial otra, Operaciones otra.
     ¿Se calcula como NO_ASISTIO / total_citas, o se excluyen
     cancelaciones y reagendamientos del denominador?
     Impacto: Es la diferencia entre reportar 12% o 17%. (Ref: Acta)

  3. EDADES -1 Y 999 — ¿qué representan?
     Hay 274 registros con edad=-1 o edad=999 distribuidos en las
     3 IPS. ¿Son convenciones del sistema para "no informada"?
     ¿Existe un catálogo de valores especiales?
     Impacto: Necesario para segmentar y para el modelo predictivo. (Ref: H3)

  4. DATOS PERSONALES EN IPS SUR — ¿fue intencional?
     La extracción de IPS Sur incluye documento_identidad (cédula)
     y teléfono del paciente. Norte y Occidente no los traen.
     ¿Fue un error de la extracción o es intencional?
     ¿Existe autorización para almacenar estos datos en un DWH?
     Impacto: Riesgo legal bajo Ley 1581/2012. (Ref: H2)

  5. DUPLICADOS EN IPS NORTE — ¿es la extracción o el sistema?
     Hay 197 cita_id que aparecen duplicados. Algunos tienen estados
     distintos (ej: NOR-182102 aparece como CONFIRMADA y como ATENDIDA).
     ¿El sistema fuente guarda versiones históricas del registro?
     ¿O es un error de la extracción?
     Impacto: +395 filas fantasma que inflan las métricas. (Ref: H4)

  6. CITAS FUTURAS ATENDIDAS — ¿desfase de zona horaria?
     Hay 67 citas con fecha posterior al 30/jun/2026 (fecha de
     extracción) marcadas como ATENDIDA. ¿Es posible que las fechas
     estén en otra zona horaria, o es un error del sistema fuente?
     Impacto: Métricas sobre datos temporalmente imposibles. (Ref: H6)

  7. WHATSAPP: REF_CITA FALTANTE Y CORRUPTA — ¿por qué?
     El 29.5% de los eventos no tiene ref_cita, y el 1.9% tiene
     referencias con prefijo XXX- (en vez de NOR-/SUR-/OCC-).
     ¿Los eventos sin ref_cita son de otros clientes no incluidos?
     ¿Qué significa el prefijo XXX-?
     Impacto: No podemos medir efectividad de recordatorios. (Ref: H7)

  8. ESQUEMA DE OCCIDENTE — ¿sistema diferente?
     Occidente usa separador distinto, nombres de campos diferentes,
     estados abreviados y formato ISO para fechas. ¿Tiene otro sistema?
     ¿Se espera que futuros clientes también tengan esquemas propios?
     Impacto: Define si el pipeline debe ser configurable por cliente. (Ref: H1)
""")

print("=" * 70)
print("FIN DEL DIAGNÓSTICO E1")
print("=" * 70)
