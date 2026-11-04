"""
Registro de auditoría (RF-07, RNF-02): solo inserción, nunca se edita ni se borra.
SQLite por defecto; cambiar a PostgreSQL es solo cambiar DATABASE_URL en .env.
"""
import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import JSON, Column, DateTime, Float, Integer, String, create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from app.config import get_settings

Base = declarative_base()


class RegistroRuta(Base):
    __tablename__ = "registros_ruta"

    id = Column(Integer, primary_key=True, autoincrement=True)
    id_ruta = Column(String, unique=True, index=True, nullable=False)
    generado_en = Column(DateTime, nullable=False)
    generado_por = Column(String, nullable=False)  # client_id del token OAuth, nunca un dato de paciente
    algoritmo_version = Column(String, nullable=False)
    parametros_json = Column(JSON, nullable=False)
    orden_visita_json = Column(JSON, nullable=False)
    distancia_total_km = Column(Float, nullable=False)
    distancia_optima_km = Column(Float, nullable=False)
    hash_entrada = Column(String, nullable=False)


class Usuario(Base):
    """Cuentas creadas desde POST /usuarios (RF-09, RF-10). Guarda solo el hash de la contraseña."""
    __tablename__ = "usuarios"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    rol = Column(String, nullable=False)  # "coordinador" | "administrador"
    creado_en = Column(DateTime, nullable=False)


_settings = get_settings()
_engine = create_engine(_settings.database_url, connect_args={"check_same_thread": False} if "sqlite" in _settings.database_url else {})
SessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False)


def inicializar_bd() -> None:
    Base.metadata.create_all(_engine)


def obtener_sesion():
    sesion = SessionLocal()
    try:
        yield sesion
    finally:
        sesion.close()


def calcular_hash_entrada(parametros: dict, veredas_disponibles: int) -> str:
    """Hash reproducible de los parámetros de entrada, para poder reconstruir cada ruta (RF-07)."""
    payload = json.dumps({"parametros": parametros, "veredas_disponibles": veredas_disponibles}, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def guardar_registro(sesion: Session, *, id_ruta: str, generado_por: str, algoritmo_version: str,
                      parametros: dict, orden_visita: list[str], distancia_total_km: float,
                      distancia_optima_km: float, hash_entrada: str) -> RegistroRuta:
    registro = RegistroRuta(
        id_ruta=id_ruta,
        generado_en=datetime.now(timezone.utc),
        generado_por=generado_por,
        algoritmo_version=algoritmo_version,
        parametros_json=parametros,
        orden_visita_json=orden_visita,
        distancia_total_km=distancia_total_km,
        distancia_optima_km=distancia_optima_km,
        hash_entrada=hash_entrada,
    )
    sesion.add(registro)
    sesion.commit()
    sesion.refresh(registro)
    return registro


def listar_registros(sesion: Session, limite: int = 50) -> list[RegistroRuta]:
    return (
        sesion.query(RegistroRuta)
        .order_by(RegistroRuta.generado_en.desc())
        .limit(limite)
        .all()
    )


def obtener_registro(sesion: Session, id_ruta: str) -> RegistroRuta | None:
    return sesion.query(RegistroRuta).filter(RegistroRuta.id_ruta == id_ruta).first()


def crear_usuario(sesion: Session, *, username: str, password_hash: str, rol: str) -> Usuario:
    usuario = Usuario(
        username=username,
        password_hash=password_hash,
        rol=rol,
        creado_en=datetime.now(timezone.utc),
    )
    sesion.add(usuario)
    sesion.commit()
    sesion.refresh(usuario)
    return usuario


def obtener_usuario_por_username(sesion: Session, username: str) -> Usuario | None:
    return sesion.query(Usuario).filter(Usuario.username == username).first()


def contar_visitas_recientes(sesion: Session, n_jornadas: int = 2) -> dict[int, int]:
    """
    Cuenta cuántas veces apareció cada vereda en las últimas n_jornadas rutas generadas,
    para alimentar el factor de equidad (RF-08).
    """
    registros = (
        sesion.query(RegistroRuta)
        .order_by(RegistroRuta.generado_en.desc())
        .limit(n_jornadas)
        .all()
    )
    conteo: dict[int, int] = {}
    for registro in registros:
        for vereda_id in registro.orden_visita_json:
            conteo[vereda_id] = conteo.get(vereda_id, 0) + 1
    return conteo
