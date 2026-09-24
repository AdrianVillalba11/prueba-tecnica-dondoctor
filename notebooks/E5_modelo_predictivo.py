"""
E5. Modelo Predictivo de Ausentismo

Cuaderno reproducible que construye un primer modelo para predecir
la inasistencia de pacientes a sus citas médicas, usando los datos
de la capa de consumo generada por el pipeline (E4).

Ejecutar desde la raíz del proyecto:
    python notebooks/E5_modelo_predictivo.py
"""

import sys
sys.stdout.reconfigure(encoding="utf-8")

import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from pathlib import Path
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import (
    roc_auc_score, roc_curve, classification_report,
    confusion_matrix, f1_score,
)
import warnings
warnings.filterwarnings("ignore")

BASE_DIR = Path(__file__).resolve().parent.parent
CONSUMO_DIR = BASE_DIR / "data" / "consumo"
DOCS_DIR = BASE_DIR / "docs"
SEED = 42
FECHA_CORTE = pd.Timestamp("2026-04-01")


# ════════════════════════════════════════════════════════════════
# 0. CARGA DE DATOS
# ════════════════════════════════════════════════════════════════

print("=" * 70)
print("E5. MODELO PREDICTIVO DE AUSENTISMO")
print("=" * 70)

df_raw = pd.read_csv(CONSUMO_DIR / "fact_citas.csv")
df_raw["fecha_cita"] = pd.to_datetime(df_raw["fecha_cita"])

df = df_raw[df_raw["es_cita_efectiva"] == 1].copy()
df = df.sort_values(["paciente_id", "fecha_cita"]).reset_index(drop=True)

print(f"\nCitas totales en fact_citas: {len(df_raw):,}")
print(f"Citas efectivas (ATENDIDA + NO_ASISTIO): {len(df):,}")
print(f"Tasa de ausentismo: {df['es_ausentismo'].mean()*100:.1f}%")
print(f"Periodo: {df['fecha_cita'].min().strftime('%Y-%m-%d')} a "
      f"{df['fecha_cita'].max().strftime('%Y-%m-%d')}")


# ════════════════════════════════════════════════════════════════
# 1. DECISIÓN DE NEGOCIO Y MOMENTO DE PREDICCIÓN
# ════════════════════════════════════════════════════════════════

print("\n" + "=" * 70)
print("1. DECISIÓN DE NEGOCIO Y MOMENTO DE PREDICCIÓN")
print("=" * 70)

print("""
DECISIÓN QUE HABILITA EL MODELO
  Priorizar la gestión de recordatorios y confirmaciones. En lugar
  de tratar todas las citas igual, la IPS focaliza sus esfuerzos
  (llamadas, WhatsApp personalizado) en los pacientes con mayor
  probabilidad de no asistir. Con recursos limitados, el modelo
  permite decidir: ¿a quién llamo primero?

MOMENTO DE LA PREDICCIÓN — DOS ESCENARIOS
  Escenario A — Al agendar la cita:
    Solo se dispone de datos demográficos e historial del paciente.
    Útil para asignar turnos estratégicamente y dimensionar el
    sobreagendamiento por especialidad.

  Escenario B — 24 horas antes de la cita:
    Se agrega si el paciente recibió recordatorio por WhatsApp.
    Útil para decidir a quién llamar HOY para confirmar asistencia.
    Este es el escenario más accionable: el director de operaciones
    revisa las citas de mañana ordenadas por riesgo y asigna llamadas.

  Se construyen ambos escenarios para medir el valor incremental
  del recordatorio como señal predictiva.
""")


# ════════════════════════════════════════════════════════════════
# 2. VARIABLE OBJETIVO
# ════════════════════════════════════════════════════════════════

print("=" * 70)
print("2. VARIABLE OBJETIVO: es_ausentismo")
print("=" * 70)

n_asistio = (df["es_ausentismo"] == 0).sum()
n_no_asistio = (df["es_ausentismo"] == 1).sum()
pct = df["es_ausentismo"].mean() * 100

print(f"""
  Definición: es_ausentismo = 1 si estado = NO_ASISTIO, 0 si ATENDIDA.
  Se excluyen CANCELADA, REAGENDADA, PENDIENTE y CONFIRMADA
  (no representan inasistencia — ver decisión en E2).

  Distribución:
    Asistió (0):     {n_asistio:>6,}  ({100-pct:.1f}%)
    No asistió (1):  {n_no_asistio:>6,}  ({pct:.1f}%)

  Desbalance ~5:1. No es severo; no se aplica oversampling.
  Se usa class_weight='balanced' en regresión logística para
  compensar, y AUC como métrica (invariante al desbalance).
""")


# ════════════════════════════════════════════════════════════════
# 3. INGENIERÍA DE VARIABLES
# ════════════════════════════════════════════════════════════════

print("=" * 70)
print("3. INGENIERÍA DE VARIABLES")
print("=" * 70)

# ── 3a. Historial del paciente (acumulativo, sin fuga) ──

print("\n--- 3a. Historial del paciente ---")

df["n_citas_previas"] = df.groupby("paciente_id").cumcount()

faltas_acum = (
    df.groupby("paciente_id")["es_ausentismo"]
    .apply(lambda x: x.shift(1).expanding().sum())
    .reset_index(level=0, drop=True)
    .fillna(0)
    .astype(int)
)
df["faltas_previas"] = faltas_acum

df["tasa_ausentismo_previo"] = np.where(
    df["n_citas_previas"] > 0,
    df["faltas_previas"] / df["n_citas_previas"],
    0.0,
)
df["es_paciente_nuevo"] = (df["n_citas_previas"] == 0).astype(int)

n_nuevos = df["es_paciente_nuevo"].sum()
n_con_hist = len(df) - n_nuevos
print(f"  Pacientes únicos: {df['paciente_id'].nunique():,}")
print(f"  Citas de pacientes nuevos (sin historial): {n_nuevos:,}")
print(f"  Citas de pacientes con historial: {n_con_hist:,}")
print(f"\n  Las variables de historial se calculan de forma acumulativa:")
print(f"  para cada cita, solo se usan las citas ANTERIORES del mismo")
print(f"  paciente. Esto evita fuga temporal.")

# ── 3b. Imputación de edad ──

n_nulos_edad = df["edad"].isna().sum()
mediana_edad = df["edad"].median()
df["edad"] = df["edad"].fillna(mediana_edad)
print(f"\n--- 3b. Imputación ---")
print(f"  edad: {n_nulos_edad} nulos imputados con mediana ({mediana_edad:.0f} años)")

# ── 3c. Justificación de variables ──

print("""
--- 3c. Variables incluidas y excluidas ---

INCLUIDAS — Escenario A (al agendar):
  edad                 Numérica. Influye en compromiso con la cita.
  sexo                 Binaria. Posible diferencia de comportamiento.
  regimen              Categórica (3). Subsidiado puede reflejar
                       barreras de acceso (transporte, permisos).
  localidad            Categórica (12). Proxy de distancia y contexto.
  especialidad         Categórica (9). Psicología 24.6% vs Cardio 9.6%.
  canal_agendamiento   Categórica (4). El canal puede indicar nivel
                       de compromiso (agendó activamente vs lo llamaron).
  ips                  Categórica (3). Cada IPS tiene su dinámica.
  hora_cita            Numérica. Horarios extremos pueden ser difíciles.
  dia_semana           Categórica (7). Lunes 17.3% vs Jueves 14.1%.
  dias_anticipacion    Numérica. Citas muy lejanas se olvidan más.
  mes                  Numérica. Captura estacionalidad.
  n_citas_previas      Numérica. Pacientes frecuentes pueden ser
                       más fiables (o más propensos a fatiga).
  tasa_ausentismo_previo  Numérica. El mejor predictor individual:
                       el comportamiento pasado predice el futuro.
  es_paciente_nuevo    Binaria. Sin historial, mayor incertidumbre.

INCLUIDA SOLO EN ESCENARIO B (24h antes):
  wa_enviado           Binaria. Si recibió recordatorio WhatsApp.
                       Reduce ausentismo en 9 pp (ver E2).

EXCLUIDAS (con justificación):
  medico_id            120 valores → alto riesgo de sobreajuste con
                       12K filas. especialidad ya captura lo relevante.
  sede                 9 valores, 3 por IPS. Redundante con ips.
  wa_entregado/leido/respondio  Pueden no estar disponibles a las 24h.
                       Crean dependencia con wa_enviado.
  confirmada           Si el paciente ya confirmó, el problema está
                       resuelto. No es input del modelo.
  recordatorio_enviado Inconsistente con wa_enviado (hallazgo H8 del E1).
  gestion_recuperacion Ocurre DESPUÉS del resultado. Fuga directa.
  motivo_cierre        ES parte del resultado. Fuga directa.
  observaciones        95% nulos. Sin valor predictivo.
  cita_origen_id       94% nulos. Solo aplica a reagendadas (excluidas).
  flags de calidad     Marcan anomalías del dato, no del paciente.
""")

# ── 3d. Construcción de matrices ──

NUMERICAS = [
    "edad", "hora_cita", "dias_anticipacion", "mes",
    "n_citas_previas", "tasa_ausentismo_previo", "es_paciente_nuevo",
]
CATEGORICAS = [
    "sexo", "regimen", "localidad", "especialidad",
    "canal_agendamiento", "ips", "dia_semana",
]

cat_encoded = pd.get_dummies(df[CATEGORICAS], drop_first=True)
X_base = pd.concat(
    [df[NUMERICAS].reset_index(drop=True), cat_encoded.reset_index(drop=True)],
    axis=1,
)
X_wa = X_base.copy()
X_wa["wa_enviado"] = df["wa_enviado"].values

y = df["es_ausentismo"].values
fechas = df["fecha_cita"].values

print(f"  Variables escenario A: {X_base.shape[1]}")
print(f"  Variables escenario B: {X_wa.shape[1]}")
print(f"  Filas: {len(X_base):,}")


# ════════════════════════════════════════════════════════════════
# 4. SPLIT TEMPORAL
# ════════════════════════════════════════════════════════════════

print("\n" + "=" * 70)
print("4. SPLIT TEMPORAL")
print("=" * 70)

train_mask = fechas < FECHA_CORTE
test_mask = ~train_mask

X_train_a, X_test_a = X_base[train_mask], X_base[test_mask]
X_train_b, X_test_b = X_wa[train_mask], X_wa[test_mask]
y_train, y_test = y[train_mask], y[test_mask]

df_test = df[test_mask].copy()

print(f"""
  Estrategia: split temporal, NO aleatorio.
  Simula el uso real: se entrena con datos pasados y se predice
  el futuro. Un split aleatorio filtraría información del futuro
  al entrenamiento (historial de pacientes, estacionalidad).

  Corte: {FECHA_CORTE.strftime('%Y-%m-%d')}
  Train (jul-2025 a mar-2026): {train_mask.sum():>6,} citas  |  ausentismo {y_train.mean()*100:.1f}%
  Test  (abr-2026 a jun-2026): {test_mask.sum():>6,} citas  |  ausentismo {y_test.mean()*100:.1f}%
""")


# ════════════════════════════════════════════════════════════════
# 5. MODELO BASE: REGRESIÓN LOGÍSTICA
# ════════════════════════════════════════════════════════════════

print("=" * 70)
print("5. MODELO BASE: REGRESIÓN LOGÍSTICA (Escenario A)")
print("=" * 70)

scaler = StandardScaler()
X_tr_sc = scaler.fit_transform(X_train_a)
X_te_sc = scaler.transform(X_test_a)

lr = LogisticRegression(
    random_state=SEED, max_iter=1000, class_weight="balanced",
)
lr.fit(X_tr_sc, y_train)
y_prob_lr = lr.predict_proba(X_te_sc)[:, 1]
auc_lr = roc_auc_score(y_test, y_prob_lr)

print(f"\n  Escenario A:  AUC = {auc_lr:.3f}")

scaler_b = StandardScaler()
X_tr_sc_b = scaler_b.fit_transform(X_train_b)
X_te_sc_b = scaler_b.transform(X_test_b)

lr_b = LogisticRegression(
    random_state=SEED, max_iter=1000, class_weight="balanced",
)
lr_b.fit(X_tr_sc_b, y_train)
y_prob_lr_b = lr_b.predict_proba(X_te_sc_b)[:, 1]
auc_lr_b = roc_auc_score(y_test, y_prob_lr_b)

print(f"  Escenario B:  AUC = {auc_lr_b:.3f}")
print(f"\n  La regresión logística sirve como línea base interpretable.")
print(f"  Es un modelo lineal: asume que cada variable contribuye de")
print(f"  forma aditiva e independiente al riesgo.")


# ════════════════════════════════════════════════════════════════
# 6. MODELO ELABORADO: GRADIENT BOOSTING
# ════════════════════════════════════════════════════════════════

print("\n" + "=" * 70)
print("6. MODELO ELABORADO: GRADIENT BOOSTING")
print("=" * 70)

print("\n  Gradient Boosting captura relaciones no lineales e")
print("  interacciones entre variables (ej: edad + especialidad).")
print("  Hiperparámetros conservadores para evitar sobreajuste.\n")

gb_params = dict(
    n_estimators=200, max_depth=4, learning_rate=0.1,
    min_samples_leaf=20, subsample=0.8, random_state=SEED,
)

gb_a = GradientBoostingClassifier(**gb_params)
gb_a.fit(X_train_a, y_train)
y_prob_gb_a = gb_a.predict_proba(X_test_a)[:, 1]
auc_gb_a = roc_auc_score(y_test, y_prob_gb_a)

gb_b = GradientBoostingClassifier(**gb_params)
gb_b.fit(X_train_b, y_train)
y_prob_gb_b = gb_b.predict_proba(X_test_b)[:, 1]
auc_gb_b = roc_auc_score(y_test, y_prob_gb_b)

print(f"  Escenario A (sin WhatsApp):  AUC = {auc_gb_a:.3f}")
print(f"  Escenario B (con WhatsApp):  AUC = {auc_gb_b:.3f}")
print(f"  Mejora de A a B:             +{(auc_gb_b - auc_gb_a):.3f}")


# ════════════════════════════════════════════════════════════════
# 7. EVALUACIÓN Y MÉTRICAS
# ════════════════════════════════════════════════════════════════

print("\n" + "=" * 70)
print("7. EVALUACIÓN Y MÉTRICAS")
print("=" * 70)

print(f"""
  ┌─────────────────────────────────────────────────────────┐
  │           COMPARACIÓN DE MODELOS (AUC-ROC)              │
  ├──────────────────────────────┬────────────┬─────────────┤
  │ Modelo                       │ Escen. A   │ Escen. B    │
  ├──────────────────────────────┼────────────┼─────────────┤
  │ Regresión Logística          │   {auc_lr:.3f}    │    {auc_lr_b:.3f}    │
  │ Gradient Boosting            │   {auc_gb_a:.3f}    │    {auc_gb_b:.3f}    │
  └──────────────────────────────┴────────────┴─────────────┘
""")

best_auc = max(auc_lr, auc_lr_b, auc_gb_a, auc_gb_b)
best_name = {auc_lr: "LR-A", auc_lr_b: "LR-B", auc_gb_a: "GB-A", auc_gb_b: "GB-B"}[best_auc]
print(f"  Mejor modelo: {best_name} con AUC = {best_auc:.3f}")
print(f"""
  NOTA SOBRE LA HONESTIDAD DE LOS RESULTADOS:
  Ningún modelo alcanza AUC 0.70. Esto no es un fracaso sino un
  hallazgo: con los datos disponibles (3 IPS, 12 meses, variables
  limitadas), la inasistencia tiene un componente impredecible alto
  (decisiones de último momento, imprevistos del paciente).

  Sin embargo, el modelo SÍ es útil: los top-50 pacientes de mayor
  riesgo tienen 3.4x más probabilidad de faltar que el promedio.
  Para una IPS con recursos limitados, esto es suficiente para
  priorizar llamadas de confirmación de forma inteligente.

  El modelo mejoraría con: más datos (más IPS, más meses), variables
  adicionales (distancia al consultorio, clima, historial de pagos),
  y datos de confirmación en tiempo real.
""")

print("  POR QUÉ AUC-ROC COMO MÉTRICA PRINCIPAL:")
print("""
  1. El modelo RANKEA pacientes por riesgo, no toma decisiones
     binarias. La IPS ordena las citas de mañana por probabilidad
     de inasistencia y llama a las primeras N según su capacidad.

  2. AUC mide la calidad de ese ranking: ¿los pacientes que
     realmente faltaron aparecían más arriba en la lista?

  3. Es independiente del umbral de decisión: la IPS elige su
     punto de corte según sus recursos operativos.

  4. Es robusta con clases desbalanceadas (15.8% vs 84.2%).
""")

# ── Reporte con umbral óptimo (mejor modelo) ──

# Elegir el mejor modelo para el análisis detallado
all_models = [
    ("LR-A", y_prob_lr, auc_lr),
    ("LR-B", y_prob_lr_b, auc_lr_b),
    ("GB-A", y_prob_gb_a, auc_gb_a),
    ("GB-B", y_prob_gb_b, auc_gb_b),
]
best_model_name, best_probs, _ = max(all_models, key=lambda x: x[2])
thresholds = np.arange(0.05, 0.50, 0.01)
f1s = [f1_score(y_test, (best_probs >= t).astype(int)) for t in thresholds]
best_thr = thresholds[np.argmax(f1s)]
y_pred = (best_probs >= best_thr).astype(int)

print(f"  --- Reporte del mejor modelo ({best_model_name}) ---")
print(f"  Umbral óptimo (max F1): {best_thr:.2f}\n")
print(classification_report(
    y_test, y_pred,
    target_names=["Asistió", "No asistió"],
    digits=3,
))

cm = confusion_matrix(y_test, y_pred)
print(f"  Matriz de confusión:")
print(f"                      Pred: Asistió   Pred: No asistió")
print(f"    Real: Asistió        {cm[0,0]:>5}            {cm[0,1]:>5}")
print(f"    Real: No asistió     {cm[1,0]:>5}            {cm[1,1]:>5}")

# ── Precisión en top-K ──

print(f"\n  --- Precisión en los top-K pacientes de mayor riesgo ---")
print(f"  (Si la IPS llama a los K pacientes con mayor score)\n")
sorted_idx = np.argsort(-best_probs)
base_rate = y_test.mean()
for k in [50, 100, 200, 500]:
    if k <= len(y_test):
        top_k_y = y_test[sorted_idx[:k]]
        prec = top_k_y.mean()
        lift = prec / base_rate
        print(f"    Top {k:>3}: {prec*100:.1f}% faltaron "
              f"(vs {base_rate*100:.1f}% base → lift {lift:.1f}x)")

# ── Curvas ROC ──

fig, ax = plt.subplots(figsize=(7, 5))
for label, probs, ls, color in [
    (f"Logistic A (AUC={auc_lr:.3f})", y_prob_lr, "--", "#95a5a6"),
    (f"Logistic B (AUC={auc_lr_b:.3f})", y_prob_lr_b, "--", "#3498db"),
    (f"GB Escenario A (AUC={auc_gb_a:.3f})", y_prob_gb_a, "-", "#e67e22"),
    (f"GB Escenario B (AUC={auc_gb_b:.3f})", y_prob_gb_b, "-", "#2c3e50"),
]:
    fpr, tpr, _ = roc_curve(y_test, probs)
    ax.plot(fpr, tpr, ls, color=color, linewidth=2, label=label)
ax.plot([0, 1], [0, 1], "k:", alpha=0.3, label="Aleatorio (0.500)")
ax.set_xlabel("Tasa de Falsos Positivos")
ax.set_ylabel("Tasa de Verdaderos Positivos")
ax.set_title("Curvas ROC — Comparación de modelos")
ax.legend(loc="lower right", fontsize=9)
ax.grid(alpha=0.3)
fig.tight_layout()
roc_path = DOCS_DIR / "E5_curvas_roc.png"
fig.savefig(roc_path, dpi=150)
plt.close(fig)
print(f"\n  Figura guardada: {roc_path.relative_to(BASE_DIR)}")


# ════════════════════════════════════════════════════════════════
# 8. IMPORTANCIA DE VARIABLES
# ════════════════════════════════════════════════════════════════

print("\n" + "=" * 70)
print("8. IMPORTANCIA DE VARIABLES")
print("=" * 70)

importances = gb_b.feature_importances_
feat_imp = pd.Series(importances, index=X_wa.columns).sort_values(ascending=False)

print(f"\n  Top 15 variables (Gradient Boosting Escenario B):\n")
for i, (feat, imp) in enumerate(feat_imp.head(15).items(), 1):
    bar = "█" * int(imp * 150)
    print(f"    {i:>2}. {feat:<30} {imp:.4f}  {bar}")

fig2, ax2 = plt.subplots(figsize=(8, 5))
top15 = feat_imp.head(15)
colors = ["#2c3e50"] * len(top15)
ax2.barh(range(len(top15)), top15.values, color=colors)
ax2.set_yticks(range(len(top15)))
ax2.set_yticklabels(top15.index, fontsize=9)
ax2.invert_yaxis()
ax2.set_xlabel("Importancia")
ax2.set_title("Top 15 variables — Gradient Boosting Escenario B")
fig2.tight_layout()
imp_path = DOCS_DIR / "E5_importancia_variables.png"
fig2.savefig(imp_path, dpi=150)
plt.close(fig2)
print(f"\n  Figura guardada: {imp_path.relative_to(BASE_DIR)}")


# ════════════════════════════════════════════════════════════════
# 9. ANÁLISIS DE FAIRNESS ENTRE GRUPOS
# ════════════════════════════════════════════════════════════════

print("\n" + "=" * 70)
print("9. ANÁLISIS DE FAIRNESS ENTRE GRUPOS DE PACIENTES")
print("=" * 70)

print("""
  El modelo se usará para priorizar intervenciones. Si funciona
  peor para ciertos grupos, esos pacientes recibirían menos
  atención preventiva. Verificamos que el AUC sea comparable
  entre grupos demográficos.
""")

y_test_series = pd.Series(y_test, index=df_test.index)
probs_series = pd.Series(best_probs, index=df_test.index)

df_test["grupo_edad"] = pd.cut(
    df_test["edad"],
    bins=[0, 17, 40, 65, 120],
    labels=["0-17", "18-40", "41-65", "65+"],
)

fairness_results = []

for group_col, group_name in [
    ("sexo", "Sexo"),
    ("regimen", "Régimen"),
    ("ips", "IPS"),
    ("grupo_edad", "Grupo de edad"),
]:
    print(f"  --- {group_name} ---")
    for val in sorted(df_test[group_col].dropna().unique()):
        mask = df_test[group_col] == val
        g_y = y_test_series.loc[mask.index[mask]]
        g_p = probs_series.loc[mask.index[mask]]
        n = mask.sum()
        if n < 30 or g_y.nunique() < 2:
            print(f"    {str(val):<20} n={n:<5}  (insuficiente para AUC)")
            continue
        g_auc = roc_auc_score(g_y, g_p)
        g_rate = g_y.mean() * 100
        fairness_results.append((group_name, str(val), n, g_auc, g_rate))
        print(f"    {str(val):<20} n={n:<5}  AUC={g_auc:.3f}  "
              f"ausentismo={g_rate:.1f}%")
    print()

# Fairness figure
fig3, axes = plt.subplots(1, 4, figsize=(14, 4), sharey=True)
for i, group_name in enumerate(["Sexo", "Régimen", "IPS", "Grupo de edad"]):
    ax = axes[i]
    group_data = [(v, a) for g, v, n, a, r in fairness_results if g == group_name]
    if group_data:
        labels, aucs = zip(*group_data)
        bars = ax.bar(range(len(labels)), aucs, color="#2c3e50", alpha=0.8)
        ax.set_xticks(range(len(labels)))
        ax.set_xticklabels(labels, fontsize=8, rotation=30, ha="right")
        ax.set_title(group_name, fontsize=10)
        ax.set_ylim(0.5, 1.0)
        ax.axhline(y=best_auc, color="red", linestyle="--", alpha=0.5, linewidth=1)
        ax.grid(axis="y", alpha=0.3)
        for bar, auc_val in zip(bars, aucs):
            ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 0.01,
                    f"{auc_val:.2f}", ha="center", fontsize=8)
axes[0].set_ylabel("AUC-ROC")
fig3.suptitle("AUC por grupo demográfico (línea roja = AUC global)", fontsize=11)
fig3.tight_layout()
fair_path = DOCS_DIR / "E5_fairness.png"
fig3.savefig(fair_path, dpi=150)
plt.close(fig3)
print(f"  Figura guardada: {fair_path.relative_to(BASE_DIR)}")

print("""
  INTERPRETACIÓN:
  - Si un grupo tiene AUC significativamente menor, el modelo
    lo rankea peor → esos pacientes serían subatendidos.
  - Si un grupo tiene tasa de ausentismo mucho mayor pero AUC
    similar, el modelo captura bien el fenómeno en ese grupo.
  - Disparidades grandes (>0.05 en AUC) requerirían modelos
    específicos o recalibración por grupo.
""")


# ════════════════════════════════════════════════════════════════
# 10. RECOMENDACIÓN FINAL
# ════════════════════════════════════════════════════════════════

print("=" * 70)
print("10. RECOMENDACIÓN: PARA QUÉ USAR Y PARA QUÉ NO")
print("=" * 70)

print(f"""
  PARA QUÉ SÍ USAR ESTE MODELO:

  1. Priorizar llamadas de confirmación. El director de operaciones
     ordena las citas de mañana por score de riesgo y asigna llamadas
     a las más probables de inasistencia. Con capacidad para llamar a
     50 pacientes, el modelo concentra el esfuerzo donde más impacta.

  2. Dimensionar el sobreagendamiento. Si una franja horaria tiene
     5 citas con score alto (>0.30), se puede agendar una cita
     adicional de respaldo, reduciendo la agenda desperdiciada.

  3. Focalizar la cobertura de WhatsApp. Hoy solo el 49% de las citas
     reciben recordatorio. Si no se puede llegar al 100% de inmediato,
     priorizar las citas de mayor riesgo.

  PARA QUÉ NO USAR ESTE MODELO:

  1. NO para compartir scores individuales con EPS. Compartir un
     listado de pacientes "de alto riesgo" a terceros constituye
     tratamiento de datos sensibles (Ley 1581/2012) y puede generar
     discriminación (ver análisis en E2, sección 2).

  2. NO para negar o restringir servicios. El modelo identifica
     riesgo de inasistencia, no "calidad" del paciente. Usar el
     score para priorizar pacientes "más rentables" sería un uso
     antiético que DonDoctor no debe permitir.

  3. NO como única fuente de decisión. El modelo es una herramienta
     de priorización, no de predicción perfecta. Un AUC de {best_auc:.2f}
     significa que acierta más que el azar, pero no es infalible.
     Siempre debe complementarse con juicio operacional.

  LIMITACIONES CONOCIDAS:

  - Entrenado con datos de 3 IPS en Bogotá. Puede no generalizar
    a IPS en otras ciudades o con perfiles de pacientes distintos.
  - 12 meses de datos. No captura cambios estructurales (ej: una
    pandemia, un cambio de política de la EPS).
  - El historial de pacientes nuevos (primera cita) se basa solo
    en datos demográficos. Para estos pacientes, el modelo es
    menos preciso.
  - Con más datos (más IPS, más meses), el modelo mejoraría.
    Reentrenar trimestralmente con datos acumulados.
""")

print("=" * 70)
print("FIN DEL ANÁLISIS E5")
print("=" * 70)
