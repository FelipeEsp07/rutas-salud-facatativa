# Consideraciones éticas y limitaciones

## Cómo se evita que el índice estigmatice a una comunidad

1. **Indicadores de acceso, no etiquetas de pobreza.** El índice simulado se construye
   con variables que describen dificultad de *acceso* a la salud (población adulta
   mayor, gestantes y menores de 5 años, porcentaje de vía sin pavimentar, días sin
   visita del EBS), nunca con categorías que etiqueten a la comunidad como "pobre" o
   "de riesgo". La comunicación pública usa la palabra "prioridad", no "riesgo".

2. **El canal público no expone el puntaje.** `GET /veredas/publico` devuelve ubicación
   pero no el índice de vulnerabilidad de cada vereda. Solo el canal autenticado
   (`GET /veredas`, para el coordinador del EBS) lo muestra. La respuesta de
   `POST /rutas` tampoco incluye el puntaje interno de selección, solo el orden final.

3. **Falacia ecológica.** El índice describe a la vereda como unidad geográfica, no a
   cada persona o familia dentro de ella. Usarlo para decidir sobre un individuo
   concreto —por ejemplo, negarle o priorizarle un servicio— sería un error de
   inferencia: el promedio de un área no se puede atribuir a cada residente.

4. **Sesgo de exclusión sistemática.** Un algoritmo de pura maximización de puntaje
   deja siempre afuera a las veredas con menor vulnerabilidad o más lejanas, aunque
   lleven meses sin visita. El **factor de equidad** (RF-08) corrige esto: penaliza a
   las veredas visitadas en las últimas jornadas, para que la atención rote. El
   registro de auditoría permite medir, con el tiempo, cuántas veces quedó cada
   vereda sin visitar.

5. **Transparencia y explicabilidad.** La fórmula de puntaje es simple y pública:
   `puntaje = alfa * vulnerabilidad + (1 - alfa) * cercanía - penalización_equidad`.
   No es una caja negra: cualquier persona puede reproducir el cálculo a mano con los
   datos de `/veredas` y los parámetros registrados en la auditoría.

6. **Supervisión humana y decisión final.** La respuesta de `/rutas` incluye
   explícitamente que es una *sugerencia de apoyo a la decisión*. El coordinador del
   EBS puede modificar o rechazar el orden propuesto; el sistema no actúa de forma
   autónoma.

7. **Trazabilidad sin datos personales.** La auditoría registra el cliente OAuth que
   solicitó la ruta (el sistema del EBS), no pacientes ni personas. No se almacena
   ningún dato de historia clínica.

## Limitaciones del modelo con datos simulados

- **Datos inventados.** El índice de vulnerabilidad de cada vereda es simulado para
  esta demostración. No se validó contra fuentes oficiales (SISBEN, DANE, Secretaría
  de Salud de Cundinamarca) ni fue revisado por un comité de ética o un experto en
  salud pública. No debe usarse para decisiones reales.

- **Distancia aproximada.** Se usa la distancia en línea recta (Haversine) multiplicada
  por un factor fijo de sinuosidad (1.4 por defecto). Esto es una simplificación: no
  conoce el trazado real de las vías rurales, el relieve del terreno, el estado de la
  vía (destapada, en mal estado) ni condiciones climáticas que puedan alargar o
  imposibilitar el recorrido.

- **Sin restricciones operativas reales.** El modelo no considera ventanas de tiempo
  de atención, capacidad del equipo (número de pacientes que puede atender en el día),
  disponibilidad de insumos, ni interrupciones del recorrido.

- **Alcance explícitamente fuera del reto.** No hay integración con sistemas de
  historia clínica ni con GPS en tiempo real; el valor del prototipo está en la
  arquitectura y en la lógica de priorización, no en la precisión operativa.

## Marco normativo de referencia

- Marco Ético para la Inteligencia Artificial en Colombia (2021)
- CONPES 4144 de 2025 — Política Nacional de Inteligencia Artificial
- Circular Invima 0018 de 2026 (sistemas de alto impacto, evaluación de impacto
  algorítmico, supervisión humana reforzada)
- Organización Mundial de la Salud (2021) — *Ethics and governance of artificial
  intelligence for health*
- Ley 1581 de 2012 — Protección de datos personales (Colombia)
