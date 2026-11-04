"""
Microservicio de priorización de rutas de atención rural — Facatativá, Cundinamarca.
Ciclo de Investigación, Maratón de Programación LCUP/CCPL — Universidad de Cundinamarca.

Cubre la delimitación del reto:
- RF-01..RF-10: datos precargados, selección por vulnerabilidad + distancia, orden por
  vecino más cercano, distancias estimadas, auditoría, factor de equidad, comparación
  contra el óptimo y consulta de veredas.
- OAuth 2.0 (client_credentials) + registro de auditoría de solo inserción.
- Documentación de las consideraciones éticas: ver docstrings y /etica.
"""
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, Form, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from app import algorithm, data
from app.database import (
    calcular_hash_entrada, contar_visitas_recientes, crear_usuario, guardar_registro,
    inicializar_bd, listar_registros, obtener_registro, obtener_sesion, obtener_usuario_por_username,
)
from app.schemas import (
    ParadaRuta, RegistroAuditoria, RespuestaRuta, RespuestaUsuario, SolicitudCrearUsuario,
    SolicitudRuta, TokenResponse, Vereda, VeredaPublica,
)
from app.security import SCOPES_POR_ROL, autenticar_cliente, emitir_token, hash_password, requiere_scope

ALGORITMO_VERSION = "heuristica-v1.0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    inicializar_bd()
    yield


app = FastAPI(
    title="Rutas de Atención Rural — Facatativá",
    description=(
        "Calcula una ruta priorizada para un Equipo Básico de Salud que debe visitar "
        "veredas rurales de Facatativá (Cundinamarca), combinando un índice de "
        "vulnerabilidad SIMULADO con la distancia a la sede de salud. "
        "Prototipo académico — ver /etica para las limitaciones y consideraciones éticas."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# Permite que el frontend (servido en /app, o en otro origen durante desarrollo)
# llame a esta API. En un despliegue real se restringiría a los orígenes conocidos.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# OAuth 2.0 — client_credentials (RNF-01)
# ---------------------------------------------------------------------------
@app.post("/token", response_model=TokenResponse, tags=["Autenticación"])
def obtener_token(
    grant_type: str = Form(..., description="Debe ser 'client_credentials'"),
    client_id: str = Form(..., alias="username"),
    client_secret: str = Form(..., alias="password"),
    scope: str = Form(""),
    sesion: Session = Depends(obtener_sesion),
):
    """
    Flujo OAuth 2.0 **client_credentials**: `username`/`password` llevan el
    `client_id`/`client_secret` del sistema del EBS, o el usuario y la contraseña
    de una cuenta creada con `POST /usuarios`.
    """
    if grant_type != "client_credentials":
        raise HTTPException(status_code=400, detail="grant_type debe ser 'client_credentials'")

    scopes_otorgados = autenticar_cliente(sesion, client_id, client_secret)
    scopes_solicitados = set(scope.split()) if scope else scopes_otorgados
    scopes_finales = scopes_otorgados & scopes_solicitados if scopes_solicitados else scopes_otorgados
    token, expira_en = emitir_token(client_id, scopes_finales)
    return TokenResponse(access_token=token, expires_in=expira_en, scope=" ".join(sorted(scopes_finales)))


# ---------------------------------------------------------------------------
# Usuarios (RF-09, RF-10)
# ---------------------------------------------------------------------------
@app.post("/usuarios", response_model=RespuestaUsuario, status_code=201, tags=["Usuarios"])
def registrar_usuario(solicitud: SolicitudCrearUsuario, sesion: Session = Depends(obtener_sesion)):
    """
    Crea una cuenta nueva. No requiere autenticación: es el registro inicial.

    El rol determina los permisos (RF-10):
    - **coordinador**: genera rutas y consulta veredas.
    - **administrador**: además consulta el registro de auditoría.

    La contraseña nunca se guarda en texto plano: se guarda su hash (PBKDF2-HMAC-SHA256
    con sal aleatoria), y esta respuesta nunca la incluye.
    """
    if obtener_usuario_por_username(sesion, solicitud.username):
        raise HTTPException(status_code=409, detail="Ya existe una cuenta con ese usuario.")

    usuario = crear_usuario(
        sesion,
        username=solicitud.username,
        password_hash=hash_password(solicitud.password),
        rol=solicitud.rol,
    )
    return RespuestaUsuario(
        username=usuario.username,
        rol=usuario.rol,
        scopes=sorted(SCOPES_POR_ROL.get(usuario.rol, set())),
        creado_en=usuario.creado_en.isoformat(),
    )


# ---------------------------------------------------------------------------
# Veredas (RF-01, RF-10)
# ---------------------------------------------------------------------------
@app.get("/veredas", response_model=list[Vereda], tags=["Veredas"])
def consultar_veredas(
    token=Depends(requiere_scope("rutas:generar")),
    peso_adulto_mayor: float = Query(25, ge=0, le=100),
    peso_gestantes: float = Query(25, ge=0, le=100),
    peso_via: float = Query(25, ge=0, le=100),
    peso_dias_sin_visita: float = Query(25, ge=0, le=100),
):
    """
    Consulta las veredas registradas, con su ubicación, sus indicadores y el índice de
    vulnerabilidad recalculado con los pesos recibidos (RF-10). Por defecto, las 4
    dimensiones pesan igual (25 cada una). Sirve para previsualizar el índice en el mapa
    antes de generar una ruta: el mismo cálculo es el que usa `POST /rutas`.
    """
    pesos = {
        "poblacion_adulta_mayor_pct": peso_adulto_mayor,
        "gestantes_menores5_por100hogares": peso_gestantes,
        "via_sin_pavimentar_pct": peso_via,
        "dias_sin_visita_ebs": peso_dias_sin_visita,
    }
    return algorithm.calcular_pesos_vulnerabilidad(data.obtener_veredas(), pesos)


@app.get("/veredas/publico", response_model=list[VeredaPublica], tags=["Veredas"])
def consultar_veredas_publico():
    """
    Versión pública sin autenticación ni índice de vulnerabilidad: solo ubicación.
    Evita exponer un puntaje por comunidad (ver /etica).
    """
    return data.obtener_veredas()


@app.get("/veredas/geometria", tags=["Veredas"])
def consultar_geometria():
    """
    Polígonos reales de cada vereda (por código DANE), para dibujar el mapa en el
    frontend. Es cartografía pública (Gobernación de Cundinamarca), no datos sensibles,
    así que no requiere autenticación.
    """
    return data.obtener_poligonos()


# ---------------------------------------------------------------------------
# Rutas (RF-02 a RF-09)
# ---------------------------------------------------------------------------
@app.post("/rutas", response_model=RespuestaRuta, tags=["Rutas"])
def generar_ruta(
    solicitud: SolicitudRuta,
    token=Depends(requiere_scope("rutas:generar")),
    sesion: Session = Depends(obtener_sesion),
):
    """
    Genera una ruta de atención priorizada (RF-02 a RF-06, RF-08, RF-09):

    1. Selecciona `n_visitas` veredas ponderando vulnerabilidad (`alfa`) y cercanía a la sede.
    2. Si `aplicar_equidad` es verdadero, penaliza las veredas visitadas en las 2 jornadas
       más recientes, para no concentrar siempre la atención en las mismas comunidades.
    3. Ordena la visita con vecino más cercano, sede -> veredas -> sede.
    4. Compara el resultado contra el óptimo exacto para el mismo conjunto de veredas.
    5. Registra la solicitud en la auditoría (RF-07) antes de responder.
    """
    sede = data.obtener_sede()

    if solicitud.n_visitas > len(data.obtener_veredas()):
        raise HTTPException(
            status_code=422,
            detail=f"Se solicitaron {solicitud.n_visitas} veredas pero solo hay {len(data.obtener_veredas())} registradas.",
        )

    # El índice se recalcula con los pesos recibidos, nunca con el valor fijo del JSON:
    # así la ruta siempre usa la misma vulnerabilidad que el coordinador vio en el mapa.
    pesos = {
        "poblacion_adulta_mayor_pct": solicitud.pesos_indice.peso_adulto_mayor,
        "gestantes_menores5_por100hogares": solicitud.pesos_indice.peso_gestantes,
        "via_sin_pavimentar_pct": solicitud.pesos_indice.peso_via,
        "dias_sin_visita_ebs": solicitud.pesos_indice.peso_dias_sin_visita,
    }
    veredas = algorithm.calcular_pesos_vulnerabilidad(data.obtener_veredas(), pesos)

    visitas_recientes = contar_visitas_recientes(sesion) if solicitud.aplicar_equidad else {}

    resultado = algorithm.seleccionar_y_ordenar(
        veredas=veredas,
        sede=sede,
        n_visitas=solicitud.n_visitas,
        alfa=solicitud.alfa,
        aplicar_equidad=solicitud.aplicar_equidad,
        factor_sinuosidad=solicitud.factor_sinuosidad,
        visitas_recientes=visitas_recientes,
    )

    veredas_por_id = {v["id"]: v for v in veredas}
    orden_visita = [
        ParadaRuta(
            orden=i + 1,
            vereda_id=vid,
            nombre=veredas_por_id[vid]["nombre"],
            vulnerabilidad=veredas_por_id[vid]["vulnerabilidad"],
            distancia_tramo_km=resultado.tramos_km[i],
        )
        for i, vid in enumerate(resultado.orden_ids)
    ]

    vulnerabilidad_total = sum(v["vulnerabilidad"] for v in veredas) or 1.0
    vulnerabilidad_cubierta = sum(veredas_por_id[vid]["vulnerabilidad"] for vid in resultado.orden_ids)
    vulnerabilidad_cubierta_pct = round(100 * vulnerabilidad_cubierta / vulnerabilidad_total, 2)

    id_ruta = f"R-{uuid.uuid4().hex[:8].upper()}"
    generado_en = datetime.now(timezone.utc)
    parametros = solicitud.model_dump()
    hash_entrada = calcular_hash_entrada(parametros, len(veredas))

    # RF-07: se audita antes de responder, para que la respuesta y el registro nunca se desincronicen.
    guardar_registro(
        sesion,
        id_ruta=id_ruta,
        generado_por=token.client_id,
        algoritmo_version=ALGORITMO_VERSION,
        parametros=parametros,
        orden_visita=resultado.orden_ids,
        distancia_total_km=resultado.distancia_total_km,
        distancia_optima_km=resultado.distancia_optima_km,
        hash_entrada=hash_entrada,
    )

    return RespuestaRuta(
        id_ruta=id_ruta,
        generado_en=generado_en.isoformat(),
        generado_por=token.client_id,
        algoritmo_version=ALGORITMO_VERSION,
        parametros=parametros,
        orden_visita=orden_visita,
        distancia_regreso_km=resultado.regreso_km,
        distancia_total_km=resultado.distancia_total_km,
        distancia_optima_km=resultado.distancia_optima_km,
        brecha_vs_optimo_pct=resultado.brecha_pct,
        vulnerabilidad_cubierta_pct=vulnerabilidad_cubierta_pct,
    )


# ---------------------------------------------------------------------------
# Auditoría (RF-07, RNF-02)
# ---------------------------------------------------------------------------
@app.get("/auditoria", response_model=list[RegistroAuditoria], tags=["Auditoría"])
def listar_auditoria(
    limite: int = 50,
    token=Depends(requiere_scope("auditoria:leer")),
    sesion: Session = Depends(obtener_sesion),
):
    """Lista los registros de auditoría más recientes: quién, cuándo, con qué parámetros y qué resultado."""
    registros = listar_registros(sesion, limite=limite)
    veredas_por_id = {v["id"]: v["nombre"] for v in data.obtener_veredas()}
    return [
        RegistroAuditoria(
            id_ruta=r.id_ruta,
            generado_en=r.generado_en.isoformat(),
            generado_por=r.generado_por,
            parametros=r.parametros_json,
            orden_visita=[veredas_por_id.get(vid, str(vid)) for vid in r.orden_visita_json],
            distancia_total_km=r.distancia_total_km,
            hash_entrada=r.hash_entrada,
        )
        for r in registros
    ]


@app.get("/auditoria/{id_ruta}", response_model=RegistroAuditoria, tags=["Auditoría"])
def consultar_auditoria(
    id_ruta: str,
    token=Depends(requiere_scope("auditoria:leer")),
    sesion: Session = Depends(obtener_sesion),
):
    """Reconstruye una ruta específica a partir de su registro de auditoría (RF-07)."""
    registro = obtener_registro(sesion, id_ruta)
    if not registro:
        raise HTTPException(status_code=404, detail="No existe un registro con ese id_ruta.")
    veredas_por_id = {v["id"]: v["nombre"] for v in data.obtener_veredas()}
    return RegistroAuditoria(
        id_ruta=registro.id_ruta,
        generado_en=registro.generado_en.isoformat(),
        generado_por=registro.generado_por,
        parametros=registro.parametros_json,
        orden_visita=[veredas_por_id.get(vid, str(vid)) for vid in registro.orden_visita_json],
        distancia_total_km=registro.distancia_total_km,
        hash_entrada=registro.hash_entrada,
    )


# ---------------------------------------------------------------------------
# Ética (parte de la delimitación del reto)
# ---------------------------------------------------------------------------
@app.get("/etica", tags=["Ética"])
def consideraciones_eticas():
    """Resumen de las consideraciones éticas y limitaciones del modelo."""
    return {
        "principios": [
            "El índice de vulnerabilidad describe a la vereda, no a una persona: usarlo para decidir "
            "sobre un individuo concreto sería una falacia ecológica.",
            "El índice se construye con indicadores de ACCESO (distancia, vías, población mayor, "
            "días sin visita), nunca con etiquetas de pobreza, para no estigmatizar a la comunidad.",
            "El endpoint público (/veredas/publico) no expone el puntaje de vulnerabilidad de cada vereda.",
            "El factor de equidad (RF-08) evita que el algoritmo concentre siempre la atención en las "
            "mismas veredas por tener mayor puntaje.",
            "La ruta es una sugerencia de apoyo a la decisión; la autorización final es del coordinador "
            "del Equipo Básico de Salud (supervisión humana).",
            "Todo lo generado queda en auditoría de solo inserción: se puede reconstruir qué ruta se "
            "generó, quién la solicitó y con qué parámetros.",
        ],
        "limitaciones": [
            "Los datos de vulnerabilidad son SIMULADOS para esta demostración académica.",
            "La distancia es una estimación (línea recta x factor de sinuosidad) y no usa información "
            "real de vías rurales, relieve ni condiciones climáticas.",
            "No hay ventanas de tiempo ni capacidad del equipo de salud en el modelo.",
            "El índice no ha sido validado con datos reales ni revisado por un comité de ética.",
        ],
        "marco_normativo": [
            "Marco Ético para la Inteligencia Artificial en Colombia (2021)",
            "CONPES 4144 de 2025 — Política Nacional de Inteligencia Artificial",
            "OMS (2021) — Ethics and governance of artificial intelligence for health",
            "Ley 1581 de 2012 — Protección de datos personales",
        ],
    }


@app.get("/", tags=["Información"])
def raiz():
    return {
        "servicio": "Rutas de Atención Rural — Facatativá",
        "aplicacion_web": "/app",
        "documentacion": "/docs",
        "etica": "/etica",
    }


# Frontend estático (mapa interactivo). Se monta al final para que no compita
# con las rutas de la API definidas arriba.
app.mount("/app", StaticFiles(directory="frontend", html=True), name="frontend")
