"""
Tests de calidad de datos — Reglas R1 a R9.

Estas pruebas validan que los datos de salida del pipeline cumplen las
reglas de calidad definidas en el diagnóstico E1. Se ejecutan contra los
archivos que produce el pipeline (data/clean/ y data/consumo/), no contra
los datos crudos.

Objetivo: si alguien re-ejecuta el pipeline con datos nuevos (otra
extracción, otra IPS), estos tests detectan automáticamente si los datos
de salida tienen problemas de calidad antes de que lleguen a producción.

Ejecutar desde la raíz del proyecto:
    pytest tests/test_calidad.py -v
"""

import pandas as pd
import pytest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
CLEAN_DIR = BASE_DIR / "data" / "clean"
CONSUMO_DIR = BASE_DIR / "data" / "consumo"

# ── Esquema canónico: las 21 columnas que debe tener citas_limpias.csv
# (20 del negocio + 'ips' de trazabilidad + 2 flags de calidad = 23)
COLUMNAS_CANONICAS = [
    "cita_id", "paciente_id", "edad", "sexo", "regimen", "localidad",
    "especialidad", "medico_id", "sede", "canal_agendamiento",
    "fecha_creacion", "fecha_cita", "fecha_actualizacion", "estado",
    "recordatorio_enviado", "confirmada", "gestion_recuperacion",
    "motivo_cierre", "observaciones", "cita_origen_id", "ips",
    "flag_anomalia_temporal", "flag_fecha_creacion_posterior",
]

# Estados válidos después de la homologación
ESTADOS_VALIDOS = {
    "PENDIENTE", "CONFIRMADA", "ATENDIDA",
    "NO_ASISTIO", "CANCELADA", "REAGENDADA",
}

# Campos que no pueden tener nulos (sin ellos la cita no es analizable)
CAMPOS_OBLIGATORIOS = ["cita_id", "paciente_id", "fecha_cita", "estado", "especialidad"]

# Columnas que no deben existir en la capa limpia (datos personales)
COLUMNAS_PROHIBIDAS = ["documento_identidad", "telefono", "cedula", "celular"]

# La extracción se hizo el 30/jun/2026; citas posteriores no pueden ser terminales
FECHA_EXTRACCION = pd.Timestamp("2026-06-30 23:59:59")
ESTADOS_TERMINALES = {"ATENDIDA", "NO_ASISTIO"}


# ════════════════════════════════════════════════════════════════════
# FIXTURES
# ════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def df_limpias():
    """Carga citas_limpias.csv una sola vez para todos los tests."""
    path = CLEAN_DIR / "citas_limpias.csv"
    assert path.exists(), f"No se encontró {path}. Ejecutar primero el pipeline."
    df = pd.read_csv(path, encoding="utf-8")
    df["fecha_cita"] = pd.to_datetime(df["fecha_cita"])
    df["fecha_creacion"] = pd.to_datetime(df["fecha_creacion"])
    return df


@pytest.fixture(scope="module")
def df_fact():
    """Carga fact_citas.csv una sola vez para todos los tests."""
    path = CONSUMO_DIR / "fact_citas.csv"
    assert path.exists(), f"No se encontró {path}. Ejecutar primero el pipeline."
    return pd.read_csv(path, encoding="utf-8")


# ════════════════════════════════════════════════════════════════════
# R1 — ESQUEMA CANÓNICO
# Toda fuente debe mapearse al esquema de 23 columnas estándar.
# ════════════════════════════════════════════════════════════════════

class TestR1EsquemaCanonico:

    def test_columnas_presentes(self, df_limpias):
        """Todas las columnas canónicas deben existir."""
        faltantes = set(COLUMNAS_CANONICAS) - set(df_limpias.columns)
        assert not faltantes, f"Columnas faltantes: {faltantes}"

    def test_sin_columnas_extra(self, df_limpias):
        """No debe haber columnas fuera del esquema canónico."""
        extras = set(df_limpias.columns) - set(COLUMNAS_CANONICAS)
        assert not extras, f"Columnas no reconocidas: {extras}"

    def test_ips_con_tres_valores(self, df_limpias):
        """Deben existir exactamente 3 IPS: Norte, Sur, Occidente."""
        ips_esperadas = {"Norte", "Sur", "Occidente"}
        ips_reales = set(df_limpias["ips"].unique())
        assert ips_reales == ips_esperadas, f"IPS encontradas: {ips_reales}"


# ════════════════════════════════════════════════════════════════════
# R2 — PRIVACIDAD
# La capa limpia no debe contener datos personales directos.
# ════════════════════════════════════════════════════════════════════

class TestR2Privacidad:

    def test_sin_columnas_sensibles_limpias(self, df_limpias):
        """No deben existir columnas con datos personales en citas_limpias."""
        encontradas = set(df_limpias.columns) & set(COLUMNAS_PROHIBIDAS)
        assert not encontradas, (
            f"Datos personales detectados en capa limpia: {encontradas}. "
            f"Ley 1581/2012 — eliminar antes de publicar."
        )

    def test_sin_columnas_sensibles_fact(self, df_fact):
        """No deben existir columnas con datos personales en fact_citas."""
        encontradas = set(df_fact.columns) & set(COLUMNAS_PROHIBIDAS)
        assert not encontradas, (
            f"Datos personales detectados en capa de consumo: {encontradas}."
        )


# ════════════════════════════════════════════════════════════════════
# R3 — RANGO DE EDAD
# La edad debe estar entre 0 y 120 años (o ser nula).
# ════════════════════════════════════════════════════════════════════

class TestR3RangoEdad:

    def test_sin_edades_negativas(self, df_limpias):
        """No deben existir edades menores a 0."""
        edades_validas = df_limpias["edad"].dropna()
        negativas = edades_validas[edades_validas < 0]
        assert len(negativas) == 0, (
            f"{len(negativas)} registros con edad negativa. "
            f"Valores: {negativas.unique().tolist()}"
        )

    def test_sin_edades_imposibles(self, df_limpias):
        """No deben existir edades mayores a 120."""
        edades_validas = df_limpias["edad"].dropna()
        imposibles = edades_validas[edades_validas > 120]
        assert len(imposibles) == 0, (
            f"{len(imposibles)} registros con edad > 120. "
            f"Valores: {imposibles.unique().tolist()}"
        )


# ════════════════════════════════════════════════════════════════════
# R4 — UNICIDAD DE CITA
# Cada cita_id debe aparecer una sola vez.
# ════════════════════════════════════════════════════════════════════

class TestR4UnicidadCita:

    def test_sin_duplicados_cita_id(self, df_limpias):
        """No deben existir cita_id duplicados después de la deduplicación."""
        duplicados = df_limpias[df_limpias["cita_id"].duplicated(keep=False)]
        n_dup = duplicados["cita_id"].nunique()
        assert n_dup == 0, (
            f"{n_dup} cita_id duplicados encontrados. "
            f"Ejemplos: {duplicados['cita_id'].unique()[:5].tolist()}"
        )


# ════════════════════════════════════════════════════════════════════
# R5 — CATÁLOGO DE ESTADOS
# Solo se aceptan los 6 estados homologados.
# ════════════════════════════════════════════════════════════════════

class TestR5CatalogoEstados:

    def test_estados_validos(self, df_limpias):
        """Todos los estados deben pertenecer al catálogo homologado."""
        estados_reales = set(df_limpias["estado"].unique())
        invalidos = estados_reales - ESTADOS_VALIDOS
        assert not invalidos, (
            f"Estados fuera del catálogo: {invalidos}. "
            f"Catálogo válido: {ESTADOS_VALIDOS}"
        )

    def test_sin_abreviaturas_occidente(self, df_limpias):
        """No deben quedar abreviaturas sin homologar (ATD, NAS, CAN, etc.)."""
        abreviaturas = {"ATD", "NAS", "CAN", "REP", "PEN", "CONF"}
        encontradas = set(df_limpias["estado"].unique()) & abreviaturas
        assert not encontradas, (
            f"Abreviaturas sin homologar de Occidente: {encontradas}"
        )


# ════════════════════════════════════════════════════════════════════
# R6 — ORDEN TEMPORAL
# fecha_creacion debe ser anterior o igual a fecha_cita.
# Los que violen esto deben estar marcados con flag.
# ════════════════════════════════════════════════════════════════════

class TestR6OrdenTemporal:

    def test_violaciones_marcadas_con_flag(self, df_limpias):
        """Registros con fecha_creacion > fecha_cita deben tener flag=1."""
        violaciones = df_limpias[df_limpias["fecha_creacion"] > df_limpias["fecha_cita"]]
        sin_flag = violaciones[violaciones["flag_fecha_creacion_posterior"] != 1]
        assert len(sin_flag) == 0, (
            f"{len(sin_flag)} registros con fecha_creacion > fecha_cita "
            f"que NO tienen flag_fecha_creacion_posterior=1."
        )

    def test_flag_no_marca_registros_correctos(self, df_limpias):
        """Registros con orden temporal correcto no deben tener flag=1."""
        correctos = df_limpias[df_limpias["fecha_creacion"] <= df_limpias["fecha_cita"]]
        mal_marcados = correctos[correctos["flag_fecha_creacion_posterior"] == 1]
        assert len(mal_marcados) == 0, (
            f"{len(mal_marcados)} registros con orden correcto "
            f"marcados incorrectamente con flag=1."
        )


# ════════════════════════════════════════════════════════════════════
# R7 — COHERENCIA ESTADO-FECHA
# Citas futuras (> fecha extracción) con estado terminal deben
# estar marcadas con flag_anomalia_temporal.
# ════════════════════════════════════════════════════════════════════

class TestR7CoherenciaEstadoFecha:

    def test_futuras_terminales_marcadas(self, df_limpias):
        """Citas futuras con ATENDIDA/NO_ASISTIO deben tener flag=1."""
        futuras_terminales = df_limpias[
            (df_limpias["fecha_cita"] > FECHA_EXTRACCION)
            & (df_limpias["estado"].isin(ESTADOS_TERMINALES))
        ]
        sin_flag = futuras_terminales[futuras_terminales["flag_anomalia_temporal"] != 1]
        assert len(sin_flag) == 0, (
            f"{len(sin_flag)} citas futuras con estado terminal "
            f"que NO tienen flag_anomalia_temporal=1."
        )

    def test_flag_no_marca_citas_pasadas(self, df_limpias):
        """Citas pasadas con estado terminal NO deben tener flag=1."""
        pasadas_terminales = df_limpias[
            (df_limpias["fecha_cita"] <= FECHA_EXTRACCION)
            & (df_limpias["estado"].isin(ESTADOS_TERMINALES))
        ]
        mal_marcadas = pasadas_terminales[pasadas_terminales["flag_anomalia_temporal"] == 1]
        assert len(mal_marcadas) == 0, (
            f"{len(mal_marcadas)} citas pasadas con estado terminal "
            f"marcadas incorrectamente como anomalía temporal."
        )


# ════════════════════════════════════════════════════════════════════
# R8 — INTEGRIDAD REFERENCIAL WHATSAPP
# fact_citas debe conservar todas las citas de citas_limpias (left join).
# Los campos wa_* solo pueden valer 0 o 1.
#
# Nota: la jerarquía lógica de WhatsApp (enviado → entregado → leído)
# NO se valida aquí porque el sistema fuente no siempre registra todos
# los eventos intermedios. Hay 1,646 citas con wa_leido=1 pero
# wa_entregado=0, y 2,201 con wa_entregado=1 pero wa_enviado=0.
# Esto es una inconsistencia del dato fuente (H8), no del pipeline.
# ════════════════════════════════════════════════════════════════════

class TestR8IntegridadWhatsApp:

    def test_fact_conserva_todas_las_citas(self, df_limpias, df_fact):
        """fact_citas debe tener el mismo número de filas que citas_limpias."""
        assert len(df_fact) == len(df_limpias), (
            f"fact_citas tiene {len(df_fact)} filas vs "
            f"citas_limpias tiene {len(df_limpias)}. "
            f"El left join no debe perder ni duplicar filas."
        )

    def test_wa_campos_binarios(self, df_fact):
        """Los campos wa_* solo deben contener 0 o 1."""
        campos_wa = ["wa_enviado", "wa_entregado", "wa_leido", "wa_respondio"]
        for campo in campos_wa:
            valores = set(df_fact[campo].unique())
            assert valores <= {0, 1}, (
                f"Campo '{campo}' tiene valores inesperados: {valores - {0, 1}}"
            )

    def test_sin_duplicados_en_fact(self, df_fact):
        """fact_citas no debe tener cita_id duplicados (el join no debe multiplicar)."""
        duplicados = df_fact[df_fact["cita_id"].duplicated()]
        assert len(duplicados) == 0, (
            f"{len(duplicados)} cita_id duplicados en fact_citas. "
            f"El cruce con WhatsApp no debe generar duplicados."
        )


# ════════════════════════════════════════════════════════════════════
# R9 — COMPLETITUD OBLIGATORIA
# Los campos clave no pueden tener nulos.
# ════════════════════════════════════════════════════════════════════

class TestR9CompletitudObligatoria:

    @pytest.mark.parametrize("campo", CAMPOS_OBLIGATORIOS)
    def test_campo_sin_nulos(self, df_limpias, campo):
        """Los campos obligatorios no deben tener valores nulos."""
        n_nulos = df_limpias[campo].isna().sum()
        assert n_nulos == 0, (
            f"Campo '{campo}' tiene {n_nulos} nulos "
            f"({100 * n_nulos / len(df_limpias):.2f}% del total)."
        )
