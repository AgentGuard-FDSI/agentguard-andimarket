"""Pruebas de la API web (andimarket/api): sesión, chat con polling, HITL desde la web, seguridad,
políticas y comparación. Usan el modelo simulado o el de guion: sin red y deterministas."""

from __future__ import annotations

import json
import time

import pytest
from fastapi.testclient import TestClient

from andimarket.api import create_app
from tools import db

CLAVE = "clave-de-prueba"


@pytest.fixture
def crear_api(tmp_path):
    creadas = []
    anterior = db.settings()

    def crear(espera_hitl: float = 10.0) -> TestClient:
        app = create_app(
            datos=tmp_path / f"data{len(creadas)}", clave=CLAVE, modelo_chat="simulado",
            espera_hitl=espera_hitl, evidencia=tmp_path / "evidencia", semilla=db.SEED_TEST,
        )
        creadas.append(app)
        return TestClient(app)

    yield crear
    for app in creadas:
        app.state.servidor.controles.cerrar()
    db.configure(ruta_trabajo=anterior.ruta_trabajo, ruta_evidencia=anterior.ruta_evidencia,
                 max_filas=anterior.max_filas)


@pytest.fixture
def api(crear_api):
    return crear_api()


def entrar(cliente: TestClient, usuario: str) -> dict[str, str]:
    r = cliente.post("/api/login", json={"usuario": usuario, "clave": CLAVE})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def esperar(cliente, cabeceras, ejecucion_id, estados=("terminada", "error"), limite=15.0) -> dict:
    fin = time.monotonic() + limite
    while time.monotonic() < fin:
        datos = cliente.get(f"/api/ejecuciones/{ejecucion_id}", headers=cabeceras).json()
        if datos["estado"] in estados:
            return datos
        time.sleep(0.05)
    raise AssertionError(f"la ejecución {ejecucion_id} no llegó a {estados}: {datos['estado']}")


def chat(cliente, cabeceras, **cuerpo) -> dict:
    r = cliente.post("/api/chat", json=cuerpo, headers=cabeceras)
    assert r.status_code == 202, r.text
    return r.json()


def correr_chat(cliente, cabeceras, **cuerpo) -> dict:
    datos = esperar(cliente, cabeceras, chat(cliente, cabeceras, **cuerpo)["id"])
    assert datos["estado"] == "terminada", datos["error"]
    return datos


# ---------------------------------------------------------------------------
# Sesión
# ---------------------------------------------------------------------------
def test_salud_sin_sesion(api):
    r = api.get("/api/salud")
    assert r.status_code == 200
    assert r.json()["ok"] and r.json()["verificador_entrada"] is True


def test_login_devuelve_token_y_la_identidad_del_directorio(api):
    r = api.post("/api/login", json={"usuario": "Laura.Atencion", "clave": CLAVE})
    assert r.status_code == 200
    usuario = r.json()["usuario"]
    assert (usuario["usuario"], usuario["area"], usuario["nivel"]) == ("laura.atencion", "atencion_cliente", "jefe")
    assert usuario["aprueba_hitl"] is True
    me = api.get("/api/me", headers={"Authorization": f"Bearer {r.json()['token']}"})
    assert me.json()["usuario"] == "laura.atencion"


@pytest.mark.parametrize("usuario, clave", [("ana.atencion", "mala"), ("no.existe", CLAVE)])
def test_login_fallido_no_dice_que_fallo(api, usuario, clave):
    r = api.post("/api/login", json={"usuario": usuario, "clave": clave})
    assert r.status_code == 401
    assert r.json()["detail"] == "Usuario o clave incorrectos."


def test_login_se_bloquea_tras_varios_fallos(api):
    for _ in range(5):
        assert api.post("/api/login", json={"usuario": "ana.atencion", "clave": "mala"}).status_code == 401
    r = api.post("/api/login", json={"usuario": "ana.atencion", "clave": CLAVE})
    assert r.status_code == 429  # ni con la clave correcta, mientras dure el bloqueo
    assert api.post("/api/login", json={"usuario": "laura.atencion", "clave": CLAVE}).status_code == 200


@pytest.mark.parametrize("cabeceras", [{}, {"Authorization": "Bearer inventado"}, {"Authorization": "Basic abc"}])
def test_endpoints_sin_sesion_valida_responden_401(api, cabeceras):
    for ruta in ("/api/me", "/api/prompts", "/api/aprobaciones", "/api/seguridad/resumen", "/api/politicas"):
        assert api.get(ruta, headers=cabeceras).status_code == 401


def test_logout_invalida_el_token(api):
    cab = entrar(api, "ana.atencion")
    assert api.post("/api/logout", headers=cab).status_code == 200
    assert api.get("/api/me", headers=cab).status_code == 401


# ---------------------------------------------------------------------------
# Chat (Config. B)
# ---------------------------------------------------------------------------
def test_chat_legitimo_con_modelo_simulado(api):
    cab = entrar(api, "ana.atencion")
    datos = correr_chat(api, cab, mensaje="Consulta el pedido 123")
    r = datos["resultado"]
    assert [d["decision"] for d in r["decisiones_agentguard"]] == ["ALLOW"]
    assert [e["efecto"] for e in r["efectos"]] == ["READ"]
    assert r["verificador_entrada"][0]["accion"] == "PASS"
    assert r["ataque"] is None and r["modelo"] == "simulado"
    tipos = {e["tipo"] for e in datos["eventos"]}
    assert {"agente", "agentguard", "modelo"} <= tipos
    # polling: con desde=N solo llegan los eventos nuevos
    assert api.get(f"/api/ejecuciones/{datos['id']}?desde={datos['ultimo_evento']}", headers=cab).json()["eventos"] == []
    assert api.get("/api/chat/historial", headers=cab).json()[0]["id"] == datos["id"]


def test_chat_datos_confidenciales_lo_rechaza_el_verificador(api):
    cab = entrar(api, "fabio.finanzas")
    r = correr_chat(api, cab, prompt_id="datos")["resultado"]
    assert r["verificador_entrada"][0]["accion"] == "REJECT"
    assert r["herramientas_solicitadas"] == [] and r["decisiones_agentguard"] == []
    assert r["ataque"] == {"escenario": 6, "exitoso": False, "motivo": r["ataque"]["motivo"], "capa": "verificador_entrada"}


def test_chat_escalada_la_bloquea_authorize(api):
    cab = entrar(api, "ana.atencion")
    r = correr_chat(api, cab, prompt_id="escalada")["resultado"]
    assert [(d["decision"], d["regla"]) for d in r["decisiones_agentguard"]] == [("BLOCK", "fuera_de_rol")]
    assert r["ataque"]["exitoso"] is False and r["ataque"]["capa"] == "authorize"
    assert r["efectos"] == []


def test_la_identidad_sale_de_la_sesion_no_del_cuerpo(api):
    cab = entrar(api, "ana.atencion")
    correr_chat(api, cab, mensaje="Consulta el pedido 123", usuario="gloria.gerencia", area="gerencia")
    decisiones = api.get("/api/seguridad/registro?tipo=decision", headers=cab).json()
    assert decisiones and all(e["registro"]["usuario"] == "ana.atencion" for e in decisiones)


@pytest.mark.parametrize("cuerpo, codigo", [
    ({}, 422),
    ({"mensaje": "Consulta el pedido 123", "prompt_id": "legitimo"}, 422),
    ({"mensaje": "Consulta el pedido 123", "modelo": "guion"}, 422),
    ({"prompt_id": "no_existe"}, 404),
])
def test_chat_valida_la_peticion(api, cuerpo, codigo):
    assert api.post("/api/chat", json=cuerpo, headers=entrar(api, "ana.atencion")).status_code == codigo


def test_no_se_ve_la_ejecucion_de_otro_usuario(api):
    datos = correr_chat(api, entrar(api, "ana.atencion"), mensaje="Consulta el pedido 123")
    assert api.get(f"/api/ejecuciones/{datos['id']}", headers=entrar(api, "laura.atencion")).status_code == 404


# ---------------------------------------------------------------------------
# HITL desde la web
# ---------------------------------------------------------------------------
def pedir_actualizacion(cliente, cab) -> tuple[dict, int]:
    ej = chat(cliente, cab, mensaje="Actualiza el pedido 125 a entregado")
    datos = esperar(cliente, cab, ej["id"], estados=("esperando_aprobacion", "terminada", "error"))
    assert datos["estado"] == "esperando_aprobacion", datos
    pendiente = datos["solicitud_pendiente"]
    assert pendiente["herramienta"] == "actualizar_pedido" and pendiente["aprobador_sugerido"] == "laura.atencion"
    assert any(e["tipo"] == "hitl_pendiente" for e in datos["eventos"])
    return datos, pendiente["solicitud"]


def test_hitl_lo_aprueba_el_jefe_y_nadie_se_aprueba_a_si_mismo(api):
    ana, laura, felipe = (entrar(api, u) for u in ("ana.atencion", "laura.atencion", "felipe.finanzas"))
    datos, solicitud = pedir_actualizacion(api, ana)

    propia = api.post(f"/api/aprobaciones/{solicitud}", json={"aprobar": True}, headers=ana)
    assert propia.status_code == 403 and propia.json()["detail"]["regla"] == "autoaprobacion"
    ajena = api.post(f"/api/aprobaciones/{solicitud}", json={"aprobar": True}, headers=felipe)
    assert ajena.status_code == 403 and ajena.json()["detail"]["regla"] == "aprobador_ajeno_al_area"

    assert [s["id"] for s in api.get("/api/aprobaciones", headers=ana).json()["mias"]] == [solicitud]
    assert api.get("/api/aprobaciones", headers=ana).json()["pendientes"] == []
    assert [s["id"] for s in api.get("/api/aprobaciones", headers=felipe).json()["pendientes"]] == []
    para_laura = api.get("/api/aprobaciones", headers=laura).json()
    assert [s["id"] for s in para_laura["pendientes"]] == [solicitud]
    assert para_laura["pendientes"][0]["solicitante"]["usuario"] == "ana.atencion"

    ok = api.post(f"/api/aprobaciones/{solicitud}", json={"aprobar": True, "comentario": "ok"}, headers=laura)
    assert ok.status_code == 200 and ok.json()["estado"] == "APPROVED"
    final = esperar(api, ana, datos["id"])
    d = final["resultado"]["decisiones_agentguard"]
    assert [(x["decision"], x["aprobado"], x["aprobador"], x["autorizada"]) for x in d] == [
        ("HITL", True, "laura.atencion", True)]
    assert [e["efecto"] for e in final["resultado"]["efectos"]] == ["UPDATE"]
    assert api.post(f"/api/aprobaciones/{solicitud}", json={"aprobar": False}, headers=laura).status_code == 409
    recientes = api.get("/api/aprobaciones", headers=laura).json()["recientes"]
    assert recientes[0]["registro"]["tipo"] == "hitl_decidida"


def test_hitl_rechazado_no_ejecuta_la_accion(api):
    ana, laura = entrar(api, "ana.atencion"), entrar(api, "laura.atencion")
    datos, solicitud = pedir_actualizacion(api, ana)
    assert api.post(f"/api/aprobaciones/{solicitud}", json={"aprobar": False}, headers=laura).status_code == 200
    final = esperar(api, ana, datos["id"])
    assert final["resultado"]["efectos"] == []
    assert final["resultado"]["decisiones_agentguard"][0]["autorizada"] is False


def test_hitl_sin_respuesta_se_anula(crear_api):
    api = crear_api(espera_hitl=0.3)
    ana = entrar(api, "ana.atencion")
    final = esperar(api, ana, chat(api, ana, mensaje="Actualiza el pedido 125 a entregado")["id"])
    assert final["estado"] == "terminada"
    assert final["resultado"]["efectos"] == []
    assert final["resultado"]["decisiones_agentguard"][0]["aprobador"] == "sin_respuesta"
    assert any("anulada" in e["texto"] for e in final["eventos"])
    assert api.get("/api/aprobaciones", headers=ana).json()["mias"] == []


def test_una_ejecucion_a_la_vez(api):
    ana, laura = entrar(api, "ana.atencion"), entrar(api, "laura.atencion")
    datos, solicitud = pedir_actualizacion(api, ana)
    assert api.post("/api/chat", json={"mensaje": "Consulta el pedido 123"}, headers=laura).status_code == 409
    assert api.post("/api/comparacion", json={"prompt_id": "legitimo"}, headers=laura).status_code == 409
    assert api.get("/api/salud").json()["ejecucion_en_curso"] is True
    api.post(f"/api/aprobaciones/{solicitud}", json={"aprobar": False}, headers=laura)  # se puede decidir igual
    esperar(api, ana, datos["id"])
    assert api.post("/api/chat", json={"mensaje": "Consulta el pedido 123"}, headers=laura).status_code == 202


# ---------------------------------------------------------------------------
# Seguridad y políticas
# ---------------------------------------------------------------------------
def test_seguridad_cada_quien_ve_lo_suyo_y_ti_recibe_las_alertas(api):
    ana, fabio, tomas = (entrar(api, u) for u in ("ana.atencion", "fabio.finanzas", "tomas.ti"))
    for _ in range(3):
        correr_chat(api, ana, prompt_id="escalada")
    correr_chat(api, fabio, prompt_id="datos")

    registro_ana = api.get("/api/seguridad/registro", headers=ana).json()
    assert registro_ana and all(
        "fabio.finanzas" not in json.dumps(e["registro"]) for e in registro_ana)
    assert api.get("/api/seguridad/resumen", headers=ana).json()["decisiones"]["BLOCK"] == 3
    assert api.get("/api/seguridad/resumen", headers=fabio).json()["rechazos_entrada"] == 1

    alertas_ti = api.get("/api/seguridad/alertas", headers=tomas).json()
    assert any(a["registro"]["prioridad"] == "PRIORITARIA" and a["registro"]["usuario"] == "ana.atencion"
               for a in alertas_ti)
    assert any(a["registro"]["kind"] == "entrada_rechazada" for a in alertas_ti)
    assert api.get("/api/seguridad/registro?tipo=decision", headers=tomas).json() == []  # no ve decisiones ajenas

    verificacion = api.get("/api/seguridad/verificar", headers=ana).json()
    assert verificacion["integra"] is True and verificacion["entradas_verificadas"] > 0


def test_politicas_en_solo_lectura(api):
    ana = api.get("/api/politicas", headers=entrar(api, "ana.atencion")).json()
    assert ana["mi_area"] == {"area": "atencion_cliente", "nivel": "empleado",
                              "herramientas": ["actualizar_pedido", "consultar_pedido", "enviar_correo"],
                              "aprueba_hitl": False}
    assert ana["herramientas"]["admin_action"]["action"] == "BLOCK"
    assert ana["organizacion"]["aprobador_ultima_instancia"] == "gerencia"
    assert api.get("/api/politicas", headers=entrar(api, "laura.atencion")).json()["mi_area"]["aprueba_hitl"] is True


# ---------------------------------------------------------------------------
# Comparación y demostración
# ---------------------------------------------------------------------------
def test_comparacion_a_contra_b_aislada_del_chat(api):
    cab = entrar(api, "gloria.gerencia")
    ej = api.post("/api/comparacion", json={"prompt_id": "inyeccion"}, headers=cab).json()
    r = esperar(api, cab, ej["id"])["resultado"]
    assert r["A"]["ataque_exitoso"] is True and "DELETE" in [e["efecto"] for e in r["A"]["efectos"]]
    assert r["B"]["ataque_exitoso"] is False and r["B"]["capa"] == "authorize"
    assert r["A"]["decisiones_agentguard"] == []
    assert r["prompt"]["sesion"]["usuario"] == "ana.atencion"  # la sesión del escenario
    # el laboratorio no ensucia el log de Seguridad ni la base del chat
    assert api.get("/api/seguridad/registro", headers=entrar(api, "ana.atencion")).json() == []
    pedido = correr_chat(api, entrar(api, "ana.atencion"), mensaje="Consulta el pedido 123")
    assert pedido["resultado"]["herramientas_solicitadas"][0]["resultado"]["ok"] is True


def test_experimento_con_guion(api):
    cab = entrar(api, "gloria.gerencia")
    ej = api.post("/api/comparacion/experimento", json={"repeticiones": 1}, headers=cab).json()
    r = esperar(api, cab, ej["id"], limite=60)["resultado"]
    assert r["metricas"]["A"]["tasa_no_autorizadas"] == 1.0
    assert r["metricas"]["B"]["tasa_no_autorizadas"] == 0.0
    assert "Config. A" in r["reporte_md"]


def test_resultados_guardados(api, tmp_path):
    (tmp_path / "evidencia").mkdir(exist_ok=True)
    (tmp_path / "evidencia" / "comparacion_guion.json").write_text(
        json.dumps({"modelo": "guion", "repeticiones": 1, "metricas": {"A": {}, "B": {}}, "corridas": []}),
        encoding="utf-8")
    r = api.get("/api/comparacion/resultados", headers=entrar(api, "ana.atencion")).json()
    assert [x["archivo"] for x in r] == ["comparacion_guion.json"] and "corridas" not in r[0]


def test_reiniciar_solo_ti_o_gerencia(api):
    assert api.post("/api/demo/reiniciar", headers=entrar(api, "ana.atencion")).status_code == 403
    assert api.post("/api/demo/reiniciar", headers=entrar(api, "tomas.ti")).status_code == 200
