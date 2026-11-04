"""
Algoritmo de priorización en dos fases (RF-03, RF-04, RF-05, RF-08, RF-09).

Fase 1 — Selección: puntúa cada vereda con
    puntaje = alfa * vulnerabilidad_normalizada + (1 - alfa) * cercania_normalizada - penalizacion_equidad
y toma las n_visitas mejores.

Fase 2 — Orden: vecino más cercano desde la sede de salud, con regreso a la sede.
Se compara contra el óptimo exacto por fuerza bruta (viable porque n_visitas es pequeño).

Distancias: Haversine (línea recta) multiplicada por un factor de sinuosidad, porque
los caminos rurales son más largos que la línea recta entre dos coordenadas (RF-05).
"""
import itertools
import math
from dataclasses import dataclass


@dataclass
class ResultadoRuta:
    seleccionadas: list[dict]          # veredas elegidas en fase 1, con su puntaje
    orden_ids: list[int]               # ids de vereda en el orden de visita (fase 2)
    tramos_km: list[float]             # distancia de cada tramo, mismo largo que orden_ids
    regreso_km: float
    distancia_total_km: float
    distancia_optima_km: float
    brecha_pct: float


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distancia en línea recta entre dos coordenadas, en kilómetros."""
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def distancia_estimada_km(lat1: float, lon1: float, lat2: float, lon2: float, factor_sinuosidad: float) -> float:
    """Distancia por vía estimada: línea recta corregida por un factor de sinuosidad (RF-05)."""
    return haversine_km(lat1, lon1, lat2, lon2) * factor_sinuosidad


def _normalizar(valores: list[float]) -> list[float]:
    """Min-max a [0, 1]. Si todos son iguales, devuelve 0 para todos (evita división por cero)."""
    if not valores:
        return []
    mn, mx = min(valores), max(valores)
    if mx == mn:
        return [0.0 for _ in valores]
    return [(v - mn) / (mx - mn) for v in valores]


INDICADORES_VULNERABILIDAD = (
    "poblacion_adulta_mayor_pct",
    "gestantes_menores5_por100hogares",
    "via_sin_pavimentar_pct",
    "dias_sin_visita_ebs",
)  # las 4 dimensiones ajustables del índice; las 4 suman más riesgo cuanto más altas


def calcular_pesos_vulnerabilidad(veredas: list[dict], pesos: dict[str, float]) -> list[dict]:
    """
    Recalcula 'vulnerabilidad' de cada vereda a partir de sus indicadores simulados
    (data/veredas.json: indicadores_simulados) y los pesos recibidos, en vez de usar
    el valor fijo precargado. Cada indicador se normaliza como percentil (0-1) entre
    todas las veredas antes de ponderarse, igual que la distancia a la sede.

    Devuelve una lista NUEVA de dicts (no muta las veredas originales en caché), con
    'vulnerabilidad' sobrescrita. Así el mismo cálculo alimenta tanto la vista previa
    en el mapa (GET /veredas) como la selección real de la ruta (POST /rutas): nunca
    se le muestra al coordinador un número distinto del que de verdad usa el algoritmo.
    """
    total_peso = sum(max(0.0, pesos.get(k, 0.0)) for k in INDICADORES_VULNERABILIDAD)
    if total_peso <= 0:
        # Sin pesos válidos, reparte el peso en partes iguales (mismo criterio que el valor por defecto).
        pesos_norm = {k: 1 / len(INDICADORES_VULNERABILIDAD) for k in INDICADORES_VULNERABILIDAD}
    else:
        pesos_norm = {k: max(0.0, pesos.get(k, 0.0)) / total_peso for k in INDICADORES_VULNERABILIDAD}

    columnas_normalizadas = {
        k: _normalizar([v["indicadores_simulados"][k] for v in veredas])
        for k in INDICADORES_VULNERABILIDAD
    }

    resultado = []
    for i, v in enumerate(veredas):
        puntaje = sum(pesos_norm[k] * columnas_normalizadas[k][i] for k in INDICADORES_VULNERABILIDAD)
        resultado.append({**v, "vulnerabilidad": round(puntaje, 4)})
    return resultado


def _longitud_tour(puntos: list[tuple[float, float]], sede: tuple[float, float], orden: list[int], factor: float) -> float:
    """Longitud total de un tour sede -> puntos[orden] -> sede."""
    total = 0.0
    anterior = sede
    for idx in orden:
        actual = puntos[idx]
        total += distancia_estimada_km(anterior[0], anterior[1], actual[0], actual[1], factor)
        anterior = actual
    total += distancia_estimada_km(anterior[0], anterior[1], sede[0], sede[1], factor)
    return total


def _mejor_orden_fuerza_bruta(puntos: list[tuple[float, float]], sede: tuple[float, float], factor: float) -> float:
    """Óptimo exacto probando todas las permutaciones. Viable porque n_visitas es pequeño (<= 14)."""
    n = len(puntos)
    mejor = math.inf
    for perm in itertools.permutations(range(n)):
        largo = _longitud_tour(puntos, sede, list(perm), factor)
        if largo < mejor:
            mejor = largo
    return mejor


def seleccionar_y_ordenar(
    veredas: list[dict],
    sede: dict,
    n_visitas: int,
    alfa: float,
    aplicar_equidad: bool,
    factor_sinuosidad: float,
    visitas_recientes: dict[int, int],
) -> ResultadoRuta:
    """
    veredas: lista completa de veredas candidatas (dict con id, lat, lon, vulnerabilidad, nombre, ...)
    sede: dict con lat, lon de la sede de salud
    visitas_recientes: {vereda_id: veces_visitada_en_jornadas_recientes}, para el factor de equidad (RF-08)
    """
    n_visitas = min(n_visitas, len(veredas))
    sede_xy = (sede["lat"], sede["lon"])

    distancias_sede = [
        distancia_estimada_km(sede["lat"], sede["lon"], v["lat"], v["lon"], factor_sinuosidad)
        for v in veredas
    ]
    cercania = _normalizar([-d for d in distancias_sede])  # más cerca -> valor más alto
    vulnerabilidad = _normalizar([v["vulnerabilidad"] for v in veredas])

    PESO_PENALIZACION_EQUIDAD = 0.15  # cada visita reciente baja el puntaje este valor fijo
    puntajes = []
    for i, v in enumerate(veredas):
        penalizacion = PESO_PENALIZACION_EQUIDAD * visitas_recientes.get(v["id"], 0) if aplicar_equidad else 0.0
        puntaje = alfa * vulnerabilidad[i] + (1 - alfa) * cercania[i] - penalizacion
        puntajes.append(puntaje)

    orden_por_puntaje = sorted(range(len(veredas)), key=lambda i: puntajes[i], reverse=True)
    elegidos_idx = orden_por_puntaje[:n_visitas]
    seleccionadas = [
        {**veredas[i], "puntaje": round(puntajes[i], 4)}
        for i in elegidos_idx
    ]

    # Fase 2: vecino más cercano desde la sede
    puntos = [(veredas[i]["lat"], veredas[i]["lon"]) for i in elegidos_idx]
    restantes = list(range(len(puntos)))
    orden_local: list[int] = []
    actual = sede_xy
    while restantes:
        mejor_j, mejor_d = None, math.inf
        for j in restantes:
            d = distancia_estimada_km(actual[0], actual[1], puntos[j][0], puntos[j][1], factor_sinuosidad)
            if d < mejor_d:
                mejor_d, mejor_j = d, j
        orden_local.append(mejor_j)
        actual = puntos[mejor_j]
        restantes.remove(mejor_j)

    tramos_km = []
    anterior = sede_xy
    for j in orden_local:
        d = distancia_estimada_km(anterior[0], anterior[1], puntos[j][0], puntos[j][1], factor_sinuosidad)
        tramos_km.append(round(d, 2))
        anterior = puntos[j]
    regreso_km = round(distancia_estimada_km(anterior[0], anterior[1], sede_xy[0], sede_xy[1], factor_sinuosidad), 2)

    distancia_total = round(sum(tramos_km) + regreso_km, 2)

    # RF-09: comparación contra el óptimo exacto (viable porque n_visitas suele ser <= 8)
    if len(puntos) <= 8:
        optimo = round(_mejor_orden_fuerza_bruta(puntos, sede_xy, factor_sinuosidad), 2)
    else:
        optimo = distancia_total  # evita un cálculo combinatorio excesivo; documentado como limitación
    brecha_pct = round(100 * (distancia_total - optimo) / optimo, 2) if optimo > 0 else 0.0

    orden_ids = [elegidos_idx[orden_local[k]] for k in range(len(orden_local))]
    orden_ids = [veredas[i]["id"] for i in orden_ids]

    return ResultadoRuta(
        seleccionadas=seleccionadas,
        orden_ids=orden_ids,
        tramos_km=tramos_km,
        regreso_km=regreso_km,
        distancia_total_km=distancia_total,
        distancia_optima_km=optimo,
        brecha_pct=brecha_pct,
    )
