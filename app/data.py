"""Carga el JSON precargado de veredas y la sede de salud (RF-01)."""
import json
from functools import lru_cache
from pathlib import Path

from app.config import get_settings


@lru_cache
def cargar_datos() -> dict:
    settings = get_settings()
    ruta = Path(settings.data_path)
    with ruta.open(encoding="utf-8") as f:
        return json.load(f)


def obtener_veredas() -> list[dict]:
    return cargar_datos()["veredas"]


def obtener_sede() -> dict:
    return cargar_datos()["sede_salud"]


def obtener_vereda_por_id(vereda_id: int) -> dict | None:
    for v in obtener_veredas():
        if v["id"] == vereda_id:
            return v
    return None


@lru_cache
def obtener_poligonos() -> dict:
    """
    Polígonos reales de las veredas (clave: código DANE), solo para dibujar el mapa.
    No participan en el cálculo de distancias ni de prioridad: eso usa el centroide
    guardado en veredas.json.
    """
    ruta = Path("data/veredas_poligonos.json")
    with ruta.open(encoding="utf-8") as f:
        return json.load(f)
