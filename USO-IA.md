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

## Nivel de intervención humana

Todas las decisiones de diseño, arquitectura y análisis fueron revisadas, cuestionadas y validadas antes de incorporarse. El código generado fue revisado, modificado cuando fue necesario, y ejecutado para verificar resultados. La IA fue una herramienta de productividad, no un sustituto del criterio profesional.
