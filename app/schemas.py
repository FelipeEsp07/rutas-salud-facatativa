"""Esquemas Pydantic: validan entradas y documentan la API en /docs."""
from typing import Literal
from pydantic import BaseModel, Field


class IndicadoresSimulados(BaseModel):
    """Las 4 dimensiones de acceso que componen el índice (ver app/algorithm.py). Todas simuladas."""
    poblacion_adulta_mayor_pct: float
    gestantes_menores5_por100hogares: float
    via_sin_pavimentar_pct: float
    dias_sin_visita_ebs: float


class Vereda(BaseModel):
    id: int
    codigo_dane: str
    nombre: str
    municipio: str
    lat: float
    lon: float
    vulnerabilidad: float = Field(ge=0, le=1, description="Índice recalculado con los pesos recibidos (0-1); mayor significa menos acceso")
    indicadores_simulados: IndicadoresSimulados


class VeredaPublica(BaseModel):
    """Versión sin el índice de vulnerabilidad, para no exponer un puntaje por comunidad."""
    id: int
    codigo_dane: str
    nombre: str
    municipio: str
    lat: float
    lon: float


class PesosIndice(BaseModel):
    """
    Peso relativo de cada indicador dentro del índice de vulnerabilidad. No necesitan
    sumar 1: se normalizan entre sí (ver app/algorithm.py: calcular_pesos_vulnerabilidad).
    El valor por defecto de cada uno (25) reproduce el índice original, con las 4
    dimensiones ponderadas por igual.
    """
    peso_adulto_mayor: float = Field(default=25, ge=0, le=100, description="Población adulta mayor")
    peso_gestantes: float = Field(default=25, ge=0, le=100, description="Gestantes y menores de 5 años")
    peso_via: float = Field(default=25, ge=0, le=100, description="Vía sin pavimentar")
    peso_dias_sin_visita: float = Field(default=25, ge=0, le=100, description="Días sin visita del EBS")


class SolicitudRuta(BaseModel):
    n_visitas: int = Field(default=5, ge=1, le=14, description="Veredas a visitar en la jornada")
    alfa: float = Field(default=0.6, ge=0, le=1, description="Peso de la vulnerabilidad frente a la distancia (0=solo distancia, 1=solo vulnerabilidad)")
    aplicar_equidad: bool = Field(default=True, description="Penaliza veredas visitadas en jornadas recientes")
    factor_sinuosidad: float = Field(default=1.4, ge=1.0, le=3.0, description="Multiplica la distancia en línea recta para aproximar vías rurales")
    pesos_indice: PesosIndice = Field(default_factory=PesosIndice, description="Composición ajustable del índice de vulnerabilidad")


class ParadaRuta(BaseModel):
    orden: int
    vereda_id: int
    nombre: str
    vulnerabilidad: float
    distancia_tramo_km: float = Field(description="Distancia desde la parada anterior (o la sede, en la primera)")


class RespuestaRuta(BaseModel):
    id_ruta: str
    generado_en: str
    generado_por: str
    algoritmo_version: str
    parametros: dict
    orden_visita: list[ParadaRuta]
    distancia_regreso_km: float
    distancia_total_km: float
    distancia_optima_km: float
    brecha_vs_optimo_pct: float
    vulnerabilidad_cubierta_pct: float
    aviso_etico: str = (
        "Esta ruta es una sugerencia de apoyo a la decisión. "
        "La autorización final de la jornada corresponde al coordinador del Equipo Básico de Salud."
    )


class RegistroAuditoria(BaseModel):
    id_ruta: str
    generado_en: str
    generado_por: str
    parametros: dict
    orden_visita: list[str]
    distancia_total_km: float
    hash_entrada: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    scope: str


class SolicitudCrearUsuario(BaseModel):
    username: str = Field(min_length=3, max_length=50, pattern=r"^[a-zA-Z0-9_\.\-]+$",
                           description="Solo letras, números, guion, guion bajo y punto")
    password: str = Field(min_length=6, max_length=100)
    rol: Literal["coordinador", "administrador"] = Field(
        default="coordinador",
        description="coordinador: genera rutas y consulta veredas. administrador: además consulta la auditoría.",
    )


class RespuestaUsuario(BaseModel):
    username: str
    rol: str
    scopes: list[str]
    creado_en: str
