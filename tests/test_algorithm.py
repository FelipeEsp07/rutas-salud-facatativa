"""Pruebas del algoritmo puro, sin pasar por la API (RF-03 a RF-05, RF-08, RF-09)."""
import math

from app.algorithm import (
    calcular_pesos_vulnerabilidad, distancia_estimada_km, haversine_km, seleccionar_y_ordenar,
)

SEDE = {"lat": 4.8068265, "lon": -74.3496229}

VEREDAS = [
    {"id": 1, "nombre": "Cerca y vulnerable", "lat": 4.8080, "lon": -74.3500, "vulnerabilidad": 0.9},
    {"id": 2, "nombre": "Lejos y vulnerable", "lat": 4.9500, "lon": -74.5000, "vulnerabilidad": 0.9},
    {"id": 3, "nombre": "Cerca y tranquila", "lat": 4.8075, "lon": -74.3510, "vulnerabilidad": 0.1},
    {"id": 4, "nombre": "Lejos y tranquila", "lat": 4.9400, "lon": -74.4900, "vulnerabilidad": 0.1},
]


def test_haversine_distancia_cero_en_el_mismo_punto():
    assert haversine_km(4.80, -74.35, 4.80, -74.35) == 0.0


def test_factor_de_sinuosidad_multiplica_la_linea_recta():
    recta = haversine_km(4.80, -74.35, 4.85, -74.30)
    estimada = distancia_estimada_km(4.80, -74.35, 4.85, -74.30, factor_sinuosidad=1.4)
    assert math.isclose(estimada, recta * 1.4, rel_tol=1e-9)


def test_alfa_en_1_prioriza_solo_vulnerabilidad():
    resultado = seleccionar_y_ordenar(
        veredas=VEREDAS, sede=SEDE, n_visitas=2, alfa=1.0,
        aplicar_equidad=False, factor_sinuosidad=1.4, visitas_recientes={},
    )
    ids_elegidos = {v["id"] for v in resultado.seleccionadas}
    assert ids_elegidos == {1, 2}  # las dos vulnerables, sin importar la distancia


def test_alfa_en_0_prioriza_solo_cercania():
    resultado = seleccionar_y_ordenar(
        veredas=VEREDAS, sede=SEDE, n_visitas=2, alfa=0.0,
        aplicar_equidad=False, factor_sinuosidad=1.4, visitas_recientes={},
    )
    ids_elegidos = {v["id"] for v in resultado.seleccionadas}
    assert ids_elegidos == {1, 3}  # las dos cercanas, sin importar la vulnerabilidad


def test_ruta_siempre_empieza_y_termina_en_la_sede():
    resultado = seleccionar_y_ordenar(
        veredas=VEREDAS, sede=SEDE, n_visitas=3, alfa=0.6,
        aplicar_equidad=False, factor_sinuosidad=1.4, visitas_recientes={},
    )
    assert len(resultado.tramos_km) == 3
    assert resultado.regreso_km > 0
    assert resultado.distancia_total_km == round(sum(resultado.tramos_km) + resultado.regreso_km, 2)


def test_heuristica_nunca_es_mas_corta_que_el_optimo():
    resultado = seleccionar_y_ordenar(
        veredas=VEREDAS, sede=SEDE, n_visitas=4, alfa=0.5,
        aplicar_equidad=False, factor_sinuosidad=1.4, visitas_recientes={},
    )
    assert resultado.distancia_total_km >= resultado.distancia_optima_km - 1e-6
    assert resultado.brecha_pct >= -1e-6


def test_factor_de_equidad_baja_el_puntaje_de_las_veredas_visitadas_recientemente():
    # Visitadas 10 veces recientemente: la penalización (0.15 por visita = 1.5)
    # supera la ventaja de vulnerabilidad (1.0 tras normalizar), así que deben
    # dejar de ganar frente a las veredas nunca visitadas.
    visitas = {1: 10, 2: 10}

    sin_equidad = seleccionar_y_ordenar(
        veredas=VEREDAS, sede=SEDE, n_visitas=1, alfa=1.0,
        aplicar_equidad=False, factor_sinuosidad=1.4, visitas_recientes=visitas,
    )
    con_equidad = seleccionar_y_ordenar(
        veredas=VEREDAS, sede=SEDE, n_visitas=1, alfa=1.0,
        aplicar_equidad=True, factor_sinuosidad=1.4, visitas_recientes=visitas,
    )
    # Sin aplicar el factor, gana la vereda 1 o 2 por vulnerabilidad (empatadas, normalizadas a 1.0).
    assert sin_equidad.seleccionadas[0]["id"] in (1, 2)
    # Con el factor activo, la penalización las hunde por debajo de las nunca visitadas.
    assert con_equidad.seleccionadas[0]["id"] in (3, 4)


# ---------------------------------------------------------------------------
# Pesos ajustables del índice de vulnerabilidad
# ---------------------------------------------------------------------------
VEREDAS_CON_INDICADORES = [
    {
        "id": 1, "nombre": "Solo adultos mayores",
        "indicadores_simulados": {
            "poblacion_adulta_mayor_pct": 100, "gestantes_menores5_por100hogares": 0,
            "via_sin_pavimentar_pct": 0, "dias_sin_visita_ebs": 0,
        },
    },
    {
        "id": 2, "nombre": "Solo vía sin pavimentar",
        "indicadores_simulados": {
            "poblacion_adulta_mayor_pct": 0, "gestantes_menores5_por100hogares": 0,
            "via_sin_pavimentar_pct": 100, "dias_sin_visita_ebs": 0,
        },
    },
]


def test_pesos_en_un_solo_indicador_lo_deja_como_unico_criterio():
    # Todo el peso en "vía sin pavimentar": la vereda 2 (100 en esa columna) debe
    # quedar con vulnerabilidad 1.0 y la vereda 1 (0 en esa columna) con 0.0.
    pesos = {"poblacion_adulta_mayor_pct": 0, "gestantes_menores5_por100hogares": 0,
             "via_sin_pavimentar_pct": 100, "dias_sin_visita_ebs": 0}
    resultado = calcular_pesos_vulnerabilidad(VEREDAS_CON_INDICADORES, pesos)
    por_id = {v["id"]: v["vulnerabilidad"] for v in resultado}
    assert por_id[2] == 1.0
    assert por_id[1] == 0.0


def test_pesos_en_cero_reparte_en_partes_iguales():
    # Si todos los pesos llegan en 0 (entrada inválida), no debe dividir por cero:
    # debe comportarse como si todos pesaran igual.
    pesos = {"poblacion_adulta_mayor_pct": 0, "gestantes_menores5_por100hogares": 0,
             "via_sin_pavimentar_pct": 0, "dias_sin_visita_ebs": 0}
    resultado = calcular_pesos_vulnerabilidad(VEREDAS_CON_INDICADORES, pesos)
    # Cada vereda es 100 en exactamente una columna y 0 en las otras 3, así que con
    # pesos iguales (25% cada una) ambas deben quedar con el mismo puntaje (0.25).
    valores = [v["vulnerabilidad"] for v in resultado]
    assert valores[0] == valores[1] == 0.25


def test_pesos_no_mutan_las_veredas_originales():
    original = [{**v, "indicadores_simulados": dict(v["indicadores_simulados"])} for v in VEREDAS_CON_INDICADORES]
    calcular_pesos_vulnerabilidad(VEREDAS_CON_INDICADORES, {"poblacion_adulta_mayor_pct": 100,
                                                             "gestantes_menores5_por100hogares": 0,
                                                             "via_sin_pavimentar_pct": 0, "dias_sin_visita_ebs": 0})
    assert VEREDAS_CON_INDICADORES == original
