# Handoff: tester-qa
Última actualización: 2026-11-04

## Resumen
Validación manual end-to-end con Playwright (navegador real) del frontend rediseñado en
http://127.0.0.1:8010/app/ — modo claro/oscuro, vista Coordinación/Pública, generación de ruta,
slider en vivo, responsive móvil. No se corrió suite automatizada porque no se encontró carpeta de
tests para el frontend (ver "Bloqueado por").

## Contrato / interfaz expuesta o consumida
No aplica (rol de QA, no expone contrato). Endpoints consumidos por el frontend, verificados por
red: `POST /token`, `GET /veredas/geometria`, `GET /veredas`, `GET /veredas/publico`,
`GET /auditoria?limite=10`, `POST /rutas` — todos devolvieron 200 OK en las corridas probadas.

## Decisiones y supuestos
- No existía `.claude/handoffs/` en este proyecto (se creó esta carpeta y este archivo). No había
  handoffs previos de bases-de-datos, frontend, backend ni calidad-codigo.md que leer, así que esta
  validación se basó únicamente en lo que el usuario describió como contrato esperado y en el
  comportamiento observable de la UI, no en un contrato documentado formalmente.
- Se asumió que "Cargando veredas…" debe desaparecer visualmente (opacity/display), no
  necesariamente eliminarse del DOM/árbol de accesibilidad.

## Bloqueado por / dependo de
- No se encontró ningún handoff de bases-de-datos, desarrollador-frontend, desarrollador-backend ni
  revisor-calidad-codigo en este repositorio. Si este proyecto sigue el flujo secuencial del equipo,
  falta documentar esos handoffs; no pude contrastar el comportamiento observado contra un contrato
  escrito, solo contra lo que el usuario pidió verificar directamente.
- No se encontró una suite de tests de frontend (Playwright/Jest) dentro de `frontend/` para correr
  de forma automatizada; solo hay `tests/` en la raíz, que parecen ser tests de backend (no se
  ejecutaron en esta ronda porque el alcance pedido era validación manual en navegador).

## Pendientes (TODO)
- Confirmar con desarrollador-frontend si el overlay "Cargando veredas…" debería tener
  `display:none` (o `aria-hidden`) en vez de solo `opacity:0`, para no quedar expuesto al árbol de
  accesibilidad / lectores de pantalla una vez cargó el mapa.
- Confirmar si en la vista "Pública" el KPI "Vulnerabilidad cubierta" (panel inferior del mapa)
  también debería ocultarse u ofuscarse, ya que el contrato dice que esa vista "oculta el índice de
  vulnerabilidad" pero el KPI numérico se mantiene visible con el mismo valor (35%) que en vista
  Coordinación.
- No se logró provocar un toast de error de forma natural (todas las llamadas a la API
  respondieron 200 en las pruebas); falta una ronda específica de pruebas de error (servidor caído,
  token inválido) si se quiere validar visualmente ese componente.
- Pendiente correr la suite de tests de backend (`tests/`) y cualquier test de frontend si se agrega
  en el futuro, como parte de la ronda QA completa.

## Estado de pruebas
Probado manualmente con Playwright MCP (navegador real), viewport 1280x900 y 390x844, modo claro y
`prefers-color-scheme: dark`:
- Carga inicial: sin errores de consola, sin peticiones fallidas (todas 200 OK).
- Overlay "Cargando veredas…" desaparece visualmente tras cargar (opacity 0 + pointer-events none,
  confirmado por computed style).
- Mapa muestra polígonos de veredas coloreados por índice de prioridad (verificado con captura).
- Indicador de conexión cambia a "Conectado a la API" con punto verde.
- Iconos SVG de encabezados renderizan a 14x14px, sin distorsión.
- Slider "Peso de la vulnerabilidad (α)" actualiza el valor numérico en vivo con interacción real
  de usuario (clic + flechas), no solo con eventos sintéticos.
- Botón "Generar ruta · POST /rutas": petición exitosa, KPIs (distancia total, óptimo, brecha,
  vulnerabilidad cubierta) se llenan, itinerario con paradas H/1-5/H numeradas aparece, tabla de
  auditoría agrega una fila nueva al tope. No se logró capturar el frame exacto del spinner (la
  respuesta fue más rápida que el intervalo de captura), pero el estado final es correcto.
- Vista "Pública": mapa cambia a tono neutro sin gradiente de índice, sin errores en consola.
- Modo oscuro: fondo oscuro consistente, texto con buen contraste (ej. RGB 231,237,228 sobre fondo
  RGB 18,23,20), sin fondos blancos quemados ni bordes invisibles detectados.
- Móvil 390x844: panel lateral se apila arriba del contenido, `scrollWidth === clientWidth` (390),
  confirmado sin scroll horizontal.

## Capturas de pantalla (rutas absolutas)
- C:\Users\espin\VSCODE\rutas-salud-facatativa\.playwright-mcp\01-vista-inicial.png
- C:\Users\espin\VSCODE\rutas-salud-facatativa\.playwright-mcp\02-generando-ruta-spinner.png (resultado ya cargado, no el frame del spinner)
- C:\Users\espin\VSCODE\rutas-salud-facatativa\.playwright-mcp\03-vista-publica.png
- C:\Users\espin\VSCODE\rutas-salud-facatativa\.playwright-mcp\04-modo-oscuro.png
- C:\Users\espin\VSCODE\rutas-salud-facatativa\.playwright-mcp\05-movil.png

## Defectos encontrados
1. **Menor / accesibilidad** — El overlay "Cargando veredas…" se oculta visualmente con
   `opacity:0; pointer-events:none`, pero sigue en el DOM con `display:flex` y el texto
   permanece disponible para el árbol de accesibilidad después de que el mapa cargó. No es un bug
   visual (confirmado con screenshot que no se ve superpuesto), pero un lector de pantalla podría
   seguir anunciando "Cargando veredas…" tiempo después de que el contenido ya está listo.
   Repro: cargar la página, esperar a que el mapa termine de renderizar, inspeccionar
   `.map-overlay.hidden` — sigue presente en el DOM. Probable causa: frontend
   (falta `display:none` o `aria-hidden="true"` al ocultar el overlay).
2. **Observación, no confirmado como bug** — En vista "Pública" el KPI "Vulnerabilidad cubierta"
   bajo el mapa sigue mostrando el mismo valor numérico (35%) que en vista Coordinación, mientras
   que el mapa y la leyenda sí se neutralizan. Si la intención es "no exponer un puntaje por
   comunidad" en esa vista, este KPI agregado podría considerarse una fuga parcial de esa
   información. Marco esto como pregunta para frontend/backend, no como defecto confirmado, porque
   no hay un contrato escrito que diga explícitamente si el KPI debe ocultarse también.

No se encontraron bugs funcionales ni errores de consola/red (404, CORS) en ningún flujo probado.
