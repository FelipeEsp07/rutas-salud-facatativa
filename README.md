# Rutas de Atención Rural — Facatativá

Microservicio que calcula una ruta de atención priorizada para un Equipo Básico de
Salud (EBS) que debe visitar veredas rurales de Facatativá (Cundinamarca), combinando
un índice de vulnerabilidad **simulado** con la distancia a la sede de salud.

Construido para el **Ciclo de Investigación** de la Maratón de Programación con
Impacto Social — LCUP/CCPL, Universidad de Cundinamarca.

> **Datos simulados.** El índice de vulnerabilidad de cada vereda es inventado para
> esta demostración académica. No representa la situación real de ninguna comunidad.
> Ver el endpoint `/etica`.

## Requerimientos cubiertos

| ID | Requerimiento | Dónde |
|---|---|---|
| RF-01 | Datos de las 14 veredas y la sede de salud | `data/veredas.json`, `app/data.py` |
| RF-02 | Solicitar ruta indicando cuántas veredas visitar (por defecto 5) | `POST /rutas` |
| RF-03 | Selección por vulnerabilidad y distancia (parámetro `alfa`) | `app/algorithm.py: seleccionar_y_ordenar` |
| RF-04 | Orden de visita sede → veredas → sede, minimizando desplazamiento | vecino más cercano en `app/algorithm.py` |
| RF-05 | Distancia estimada (línea recta × factor de sinuosidad) | `app/algorithm.py: distancia_estimada_km` |
| RF-06 | Orden, distancias y parámetros en la respuesta (sin exponer el índice por vereda en el canal público) | `RespuestaRuta` en `app/schemas.py` |
| RF-07 | Auditoría: quién, cuándo, con qué parámetros, qué resultado; consultable | `app/database.py`, `GET /auditoria` |
| RF-08 | Factor de equidad: penaliza veredas visitadas en jornadas recientes | `contar_visitas_recientes` + `aplicar_equidad` |
| RF-09 | Comparación contra el óptimo exacto (fuerza bruta) | `_mejor_orden_fuerza_bruta` |
| RF-10 | Consultar veredas con ubicación y vulnerabilidad | `GET /veredas` |
| RNF-01 | OAuth 2.0 (client_credentials) con scopes | `app/security.py`, `POST /token` |
| RNF-02 | Auditoría de solo inserción | `app/database.py` (no hay UPDATE/DELETE) |

## Cómo correrlo

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux/Mac
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

Abrir `http://127.0.0.1:8000/docs` para la documentación interactiva (Swagger).

## Probar el flujo completo

1. **Pedir un token** (cliente de ejemplo en `.env.example`):

   ```bash
   curl -X POST http://127.0.0.1:8000/token \
     -d "grant_type=client_credentials&username=ebs-facatativa-01&password=secreto-demo-123"
   ```

2. **Generar una ruta** con el token recibido:

   ```bash
   curl -X POST http://127.0.0.1:8000/rutas \
     -H "Authorization: Bearer <token>" \
     -H "Content-Type: application/json" \
     -d "{\"n_visitas\": 5, \"alfa\": 0.6}"
   ```

3. **Consultar la auditoría** de esa ruta:

   ```bash
   curl http://127.0.0.1:8000/auditoria -H "Authorization: Bearer <token>"
   ```

4. **Repetir el paso 2** varias veces: con `aplicar_equidad: true` (el valor por
   defecto), las veredas ya visitadas bajan de prioridad en la siguiente jornada.

## Pruebas

```bash
pytest -v
```

`tests/test_algorithm.py` prueba el algoritmo puro (sin red): que `alfa=1` prioriza
solo vulnerabilidad, que `alfa=0` prioriza solo cercanía, que la ruta nunca es más
corta que el óptimo, y que el factor de equidad cambia la selección. `tests/test_api.py`
prueba el flujo completo por HTTP: OAuth 2.0, generación de rutas, scopes insuficientes
y reconstrucción desde la auditoría.

## Despliegue (gratis, en Render)

1. Crear una cuenta en [render.com](https://render.com) (no pide tarjeta para el plan gratuito).
2. En el Dashboard: **New → Blueprint** → conectar este repositorio de GitHub.
3. Render detecta `render.yaml` y crea el servicio solo (usa el `Dockerfile`, plan
   `free`, y genera un `JWT_SECRET_KEY` aleatorio). Clic en **Apply**.
4. A los pocos minutos queda publicado en una URL como
   `https://rutas-salud-facatativa.onrender.com/app/`.

**Limitaciones del plan gratuito** (documentadas, no son un error):
- El servicio se "duerme" tras 15 minutos sin tráfico; la primera petición después
  tarda ~1 minuto en responder mientras arranca de nuevo.
- El sistema de archivos no es persistente: la base de auditoría (SQLite) se
  reinicia vacía cada vez que el servicio se reinicia o se vuelve a desplegar. Para
  un uso real habría que pasar a PostgreSQL (basta con cambiar `DATABASE_URL`,
  Render también ofrece una base Postgres gratuita por 30 días) o añadir un disco
  persistente en un plan pago.

## Arquitectura

```
Cliente EBS ──(OAuth2 client_credentials)──> /token ──> JWT (30 min, con scopes)
                                                            │
Cliente EBS ──(Bearer JWT)──> POST /rutas ─────────────────┘
                                   │
                    ┌──────────────┴───────────────┐
                    │ 1. Selección (vulnerabilidad  │
                    │    + cercanía − equidad)      │
                    │ 2. Orden (vecino más cercano) │
                    │ 3. Comparación vs. óptimo     │
                    └──────────────┬───────────────┘
                                   │
                         guarda en auditoría (SQLite,
                         solo inserción) antes de responder
```

Dos servicios lógicos separables (autorización y rutas) sobre un mismo proceso FastAPI
para esta demostración; `DATABASE_URL` permite pasar de SQLite a PostgreSQL sin tocar
código, como correspondería en un despliegue real de microservicios.

## Limitaciones declaradas

- El índice de vulnerabilidad es simulado, no validado.
- La distancia es una estimación (línea recta × 1.4), no usa datos reales de vías,
  relieve ni clima.
- No hay ventanas de tiempo ni capacidad del equipo de salud.
- No se integra con historia clínica ni GPS en tiempo real (fuera del alcance del reto).

Ver el endpoint `/etica` para el detalle de las consideraciones éticas.
