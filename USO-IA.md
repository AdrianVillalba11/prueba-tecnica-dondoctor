# Declaración de uso de IA

## Herramientas utilizadas

- **Claude (Anthropic):** Asistente de programación usado como apoyo durante todo el desarrollo.

## En qué se usó

- **Generación de código:** Estructura inicial de scripts Python (unificación, limpieza, consumo, modelo predictivo), generación de gráficas con matplotlib, y generación de PDFs con fpdf2.
- **Documentación:** Redacción y edición de documentos de entrega (E2 estrategia, E3 arquitectura, E6 resumen ejecutivo). Iteración sobre estructura, contenido y extensión.
- **Diagramas:** Generación del diagrama de arquitectura E3 mediante código Python/matplotlib.
- **Consultas técnicas:** Validación de sintaxis de pandas (cumcount, expanding), consulta de parámetros de sklearn.
- **Revisión:** Verificación de que cada entregable cumple los requisitos de la prueba técnica.

## En qué NO se usó

- **Interpretación de datos:** Los hallazgos de calidad, la lectura de las métricas de ausentismo y las conclusiones del modelo predictivo son interpretación propia sobre los resultados reales.
- **Diseño de arquitectura:** La selección de Fabric, el patrón Medallion, el dimensionamiento (F2, RLS, workload isolation) y las decisiones de qué NO implementar son criterio propio.
- **Selección de variables del modelo:** La ingeniería de features (historial acumulativo, split temporal, dos escenarios) fue diseñada con criterio propio sobre el dominio.
- **Decisiones de negocio:** Las posiciones sobre servicios de Comercial, la definición de ausentismo y la priorización del tablero operacional son criterio propio basado en la experiencia.
- **Video:** La grabación y explicación del video E6 son enteramente propias.
- **Ejecución:** Todos los scripts fueron ejecutados localmente sobre los datos reales del piloto. Los resultados (métricas, gráficas, hallazgos) provienen de la ejecución real, no fueron fabricados.

## Ejemplo de algo que la IA propuso y corregí

Para el modelo predictivo (E5), la IA propuso un conjunto de modelos y configuraciones iniciales. Revisé la propuesta, seleccioné los modelos que tenían sentido para el problema (Regresión Logística como base y Gradient Boosting como alternativa) y descarté los que no aportaban dado el volumen de datos y la naturaleza del problema. La decisión de qué modelos usar y cómo configurarlos fue mía.

## Ejemplo de algo que resolví sin IA

El proceso de limpieza de datos (E4) lo definí yo: identifiqué qué transformaciones aplicar, en qué orden y con qué criterio. La lógica de negocio detrás de cada corrección (cómo tratar las edades anómalas, qué hacer con los duplicados, cómo marcar las anomalías temporales) viene de entender el dominio, no de una sugerencia de la IA. La IA no aporta en decidir si una edad de 999 debe ser nula o imputada, eso requiere conocer el contexto clínico.

## Nivel de intervención humana

Todas las decisiones de diseño, arquitectura y análisis fueron revisadas, cuestionadas y validadas antes de incorporarse. El código generado fue revisado, modificado cuando fue necesario, y ejecutado para verificar resultados. La IA fue una herramienta de productividad, no un sustituto del criterio profesional.
