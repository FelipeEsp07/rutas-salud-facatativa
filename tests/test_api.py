"""Pruebas de integración de la API: OAuth 2.0, generación de rutas y auditoría."""
import os
import tempfile

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch):
    """Usa una base de datos SQLite temporal distinta en cada ejecución de pruebas."""
    db_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    db_file.close()
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file.name}")

    from app.config import get_settings
    get_settings.cache_clear()

    import importlib
    from app import database
    importlib.reload(database)

    from app import main
    importlib.reload(main)

    with TestClient(main.app) as c:
        yield c

    # En Windows, SQLite mantiene el archivo abierto hasta liberar el engine.
    database._engine.dispose()
    try:
        os.unlink(db_file.name)
    except PermissionError:
        pass


def obtener_token(client, scope=None):
    data = {"grant_type": "client_credentials", "username": "ebs-facatativa-01", "password": "secreto-demo-123"}
    if scope:
        data["scope"] = scope
    resp = client.post("/token", data=data)
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def test_token_rechaza_credenciales_invalidas(client):
    resp = client.post("/token", data={
        "grant_type": "client_credentials", "username": "ebs-facatativa-01", "password": "clave-incorrecta",
    })
    assert resp.status_code == 401


def test_token_valido_entrega_scopes(client):
    token = obtener_token(client)
    resp = client.get("/veredas", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    veredas = resp.json()
    assert len(veredas) == 14
    assert "vulnerabilidad" in veredas[0]


def test_veredas_sin_token_es_rechazado(client):
    resp = client.get("/veredas")
    assert resp.status_code == 401


def test_veredas_publico_no_expone_vulnerabilidad(client):
    resp = client.get("/veredas/publico")
    assert resp.status_code == 200
    veredas = resp.json()
    assert len(veredas) == 14
    assert "vulnerabilidad" not in veredas[0]


def test_generar_ruta_devuelve_cinco_paradas_por_defecto(client):
    token = obtener_token(client)
    resp = client.post("/rutas", json={}, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["orden_visita"]) == 5
    assert body["distancia_total_km"] > 0
    assert body["brecha_vs_optimo_pct"] >= 0


def test_generar_ruta_rechaza_mas_veredas_de_las_que_existen(client):
    token = obtener_token(client)
    resp = client.post("/rutas", json={"n_visitas": 99}, headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 422


def test_ruta_generada_queda_en_auditoria(client):
    token = obtener_token(client)
    resp = client.post("/rutas", json={"n_visitas": 3}, headers={"Authorization": f"Bearer {token}"})
    id_ruta = resp.json()["id_ruta"]

    resp_auditoria = client.get(f"/auditoria/{id_ruta}", headers={"Authorization": f"Bearer {token}"})
    assert resp_auditoria.status_code == 200
    registro = resp_auditoria.json()
    assert registro["generado_por"] == "ebs-facatativa-01"
    assert len(registro["orden_visita"]) == 3


def test_token_con_scope_insuficiente_no_puede_leer_auditoria(client):
    token = obtener_token(client, scope="rutas:generar")
    resp = client.get("/auditoria", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 403


def test_endpoint_de_etica_disponible_sin_autenticacion(client):
    resp = client.get("/etica")
    assert resp.status_code == 200
    assert "limitaciones" in resp.json()


def test_veredas_incluye_indicadores_simulados(client):
    token = obtener_token(client)
    resp = client.get("/veredas", headers={"Authorization": f"Bearer {token}"})
    vereda = resp.json()[0]
    assert set(vereda["indicadores_simulados"]) == {
        "poblacion_adulta_mayor_pct", "gestantes_menores5_por100hogares",
        "via_sin_pavimentar_pct", "dias_sin_visita_ebs",
    }


def test_veredas_respeta_los_pesos_recibidos(client):
    token = obtener_token(client)
    headers = {"Authorization": f"Bearer {token}"}
    por_defecto = client.get("/veredas", headers=headers).json()
    solo_via = client.get(
        "/veredas?peso_adulto_mayor=0&peso_gestantes=0&peso_via=100&peso_dias_sin_visita=0",
        headers=headers,
    ).json()
    vulnerabilidad_default = [v["vulnerabilidad"] for v in por_defecto]
    vulnerabilidad_solo_via = [v["vulnerabilidad"] for v in solo_via]
    assert vulnerabilidad_default != vulnerabilidad_solo_via


def test_generar_ruta_usa_los_mismos_pesos_que_veredas(client):
    """La vulnerabilidad que ve el coordinador en /veredas debe ser la misma que usa /rutas."""
    token = obtener_token(client)
    headers = {"Authorization": f"Bearer {token}"}
    pesos_extremos = {"peso_adulto_mayor": 0, "peso_gestantes": 0, "peso_via": 100, "peso_dias_sin_visita": 0}

    veredas = client.get(
        "/veredas?peso_adulto_mayor=0&peso_gestantes=0&peso_via=100&peso_dias_sin_visita=0",
        headers=headers,
    ).json()
    vulnerabilidad_por_id = {v["id"]: v["vulnerabilidad"] for v in veredas}

    resp = client.post(
        "/rutas",
        json={"n_visitas": 5, "pesos_indice": pesos_extremos},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    for parada in resp.json()["orden_visita"]:
        assert parada["vulnerabilidad"] == vulnerabilidad_por_id[parada["vereda_id"]]
