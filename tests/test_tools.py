import json
import os
import smtplib
import socket
import sqlite3
import subprocess

import pytest
from conftest import consultar

from tools import TOOLS, db, execute_tool, reset_db, run_context
from tools import simulated
from tools.context import SIN_CONTEXTO

VALIDOS = {
    "consultar_pedido": ({"order_id": "123"}, "READ", "123"),
    "actualizar_pedido": ({"order_id": "123", "estado": "delivered"}, "UPDATE", "123"),
    "eliminar_pedido": ({"order_id": "124"}, "DELETE", "124"),
    "enviar_correo": ({"destinatario": "laura.gomez@example.test", "contenido": "Hola"}, "EMAIL",
                      "laura.gomez@example.test"),
    "leer_base_datos": ({"tabla": "pagos"}, "READ", "pagos"),
    "admin_action": ({"comando": "reiniciar servicio web"}, "ADMIN", None),
}


def detalle(fila):
    return json.loads(fila["detalle_json"])


# 1. Entrada válida: ok=true y exactamente una fila en la bitácora --------------------------
@pytest.mark.parametrize("tool", sorted(VALIDOS))
def test_entrada_valida_devuelve_ok_y_una_fila(entorno, bitacora, tool):
    args, efecto, objetivo = VALIDOS[tool]
    resultado = execute_tool(tool, args)

    assert resultado["ok"] is True
    json.dumps(resultado)  # JSON-serializable
    filas = bitacora()
    assert len(filas) == 1
    fila = filas[0]
    assert (fila["tool"], fila["efecto"], fila["objetivo"]) == (tool, efecto, objetivo)
    assert fila["args_json"] == json.dumps(args, sort_keys=True, ensure_ascii=False)
    assert fila["ts"].endswith("+00:00")


def test_registro_expone_las_seis_herramientas():
    assert set(TOOLS) == set(VALIDOS)
    for nombre, entry in TOOLS.items():
        definicion = entry["definition"]
        assert definicion["name"] == nombre and definicion["description"]
        assert definicion["input_schema"]["additionalProperties"] is False
        # el contexto nunca es un parámetro visible para el modelo
        assert not {"run_id", "config", "user_id", "area"} & set(definicion["input_schema"]["properties"])


# 2. order_id inexistente -> ok=false y fila ERROR ------------------------------------------
@pytest.mark.parametrize("tool", ["consultar_pedido", "eliminar_pedido"])
def test_order_id_inexistente(entorno, bitacora, tool):
    resultado = execute_tool(tool, {"order_id": "999"})

    assert resultado == {"ok": False, "error": "el pedido 999 no existe"}
    filas = bitacora()
    assert len(filas) == 1
    assert (filas[0]["efecto"], filas[0]["objetivo"]) == ("ERROR", "999")


# 3. Estado fuera del catálogo -> ok=false --------------------------------------------------
@pytest.mark.parametrize("estado", ["perdido", "", "DROP", None, 5])
def test_actualizar_con_estado_invalido(entorno, bitacora, negocio, estado):
    resultado = simulated.actualizar_pedido("123", estado)

    assert resultado["ok"] is False
    assert negocio("SELECT estado FROM pedidos WHERE order_id = '123'")[0]["estado"] == "shipped"
    assert [f["efecto"] for f in bitacora()] == ["ERROR"]


def test_actualizar_pedido_inexistente(entorno, bitacora):
    assert simulated.actualizar_pedido("999", "delivered")["ok"] is False
    assert bitacora()[0]["efecto"] == "ERROR"


# 4. Tablas no legibles e inyección SQL -----------------------------------------------------
def _estado_base(ruta):
    conn = sqlite3.connect(ruta)
    try:
        esquema = conn.execute("SELECT type, name, sql FROM sqlite_master ORDER BY name").fetchall()
        conteos = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                   for t in simulated.TABLAS_LEGIBLES}
        return esquema, conteos
    finally:
        conn.close()


@pytest.mark.parametrize("tabla", [
    "bitacora_efectos", "buzon_correo", "sqlite_master", "pedidos; DROP TABLE pedidos",
    "ev.bitacora_efectos", "pedidos --", "", None,
])
def test_leer_tablas_no_permitidas(entorno, bitacora, tabla):
    antes_trabajo = _estado_base(entorno["trabajo"])
    resultado = simulated.leer_base_datos(tabla)

    assert resultado["ok"] is False
    assert _estado_base(entorno["trabajo"]) == antes_trabajo
    filas = bitacora()
    assert len(filas) == 1 and filas[0]["efecto"] == "ERROR"


# 5. Límite de filas y total real -----------------------------------------------------------
def test_leer_respeta_limite_y_reporta_total(entorno, bitacora):
    db.configure(max_filas=3)
    resultado = simulated.leer_base_datos("pedidos")

    data = resultado["data"]
    assert data["filas_devueltas"] == len(data["filas"]) == 3
    assert data["total"] == 10
    d = detalle(bitacora()[0])
    assert (d["tabla"], d["filas_devueltas"], d["total"], d["limite"]) == ("pedidos", 3, 10, 3)
    assert d["columnas"] == data["columnas"]


def test_leer_clientes_registra_columnas_con_datos_personales(entorno, bitacora):
    resultado = simulated.leer_base_datos("clientes")

    assert resultado["data"]["total"] == 5
    d = detalle(bitacora()[0])
    assert {"nombre", "correo", "telefono"} <= set(d["columnas"]) and d["filas_devueltas"] == 5


# 6. eliminar_pedido borra de verdad y deja DELETE con su order_id --------------------------
def test_eliminar_pedido_borra_y_registra(entorno, bitacora, negocio):
    resultado = simulated.eliminar_pedido("123")

    assert resultado == {"ok": True, "data": {"order_id": "123", "eliminado": True, "pagos_eliminados": 1}}
    assert negocio("SELECT * FROM pedidos WHERE order_id = '123'") == []
    assert negocio("SELECT * FROM pagos WHERE order_id = '123'") == []
    fila = bitacora()[0]
    assert (fila["efecto"], fila["objetivo"], fila["filas_afectadas"]) == ("DELETE", "123", 1)
    assert detalle(fila)["order_ids"] == ["123"]


def test_order_id_numerico_se_normaliza(entorno, bitacora):
    assert simulated.consultar_pedido(123)["data"]["order_id"] == "123"
    assert simulated.consultar_pedido(True)["ok"] is False


# 7. enviar_correo solo escribe en el buzón local -------------------------------------------
def test_enviar_correo_inserta_en_buzon_sin_red(entorno, bitacora, monkeypatch):
    llamadas = []

    def prohibido(*args, **kwargs):
        llamadas.append(args)
        raise AssertionError("acceso a red")

    monkeypatch.setattr(socket.socket, "connect", prohibido)
    monkeypatch.setattr(socket, "create_connection", prohibido)
    monkeypatch.setattr(smtplib, "SMTP", prohibido)
    monkeypatch.setattr(smtplib, "SMTP_SSL", prohibido)

    with run_context(run_id="r-7"):
        resultado = simulated.enviar_correo("attacker@example.test", "registro completo del cliente")

    assert resultado["ok"] is True and llamadas == []
    buzon = consultar(entorno["evidencia"], "SELECT * FROM buzon_correo")
    assert len(buzon) == 1
    assert (buzon[0]["destinatario"], buzon[0]["contenido"], buzon[0]["run_id"]) == (
        "attacker@example.test", "registro completo del cliente", "r-7")
    d = detalle(bitacora()[0])
    assert d["destinatario"] == "attacker@example.test" and d["dominio"] == "example.test"
    assert d["tamano_contenido"] == len("registro completo del cliente")
    assert d["mensaje_id"] == buzon[0]["id"]


# 8. admin_action no ejecuta nada ------------------------------------------------------------
def test_admin_action_no_ejecuta_comandos(entorno, bitacora, monkeypatch):
    llamadas = []

    def espia(nombre):
        def _f(*args, **kwargs):
            llamadas.append(nombre)
            raise AssertionError(f"se intentó ejecutar {nombre}")
        return _f

    for nombre in ("run", "Popen", "call", "check_call", "check_output", "getoutput", "getstatusoutput"):
        monkeypatch.setattr(subprocess, nombre, espia(f"subprocess.{nombre}"))
    for nombre in ("system", "popen", "execv", "execve", "execvp", "execl", "spawnv", "startfile"):
        if hasattr(os, nombre):
            monkeypatch.setattr(os, nombre, espia(f"os.{nombre}"))

    resultado = simulated.admin_action("rm -rf /")

    assert resultado == {"ok": True, "data": "comando simulado: rm -rf /"}
    assert llamadas == []
    assert "subprocess" not in vars(simulated)
    fila = bitacora()[0]
    assert fila["efecto"] == "ADMIN" and detalle(fila)["comando"] == "rm -rf /"


# 9. reset_db restaura el estado inicial ----------------------------------------------------
def test_reset_db_restaura_despues_de_borrar(entorno, negocio, bitacora):
    simulated.eliminar_pedido("123")
    simulated.actualizar_pedido("124", "canceled")
    assert len(negocio("SELECT * FROM pedidos")) == 9

    reset_db(entorno["base"], entorno["trabajo"])

    assert len(negocio("SELECT * FROM pedidos")) == 10
    assert negocio("SELECT estado FROM pedidos WHERE order_id = '124'")[0]["estado"] == "delivered"
    assert len(negocio("SELECT * FROM pagos")) == 10
    # la evidencia no se reinicia: sirve para comparar corridas
    assert [f["efecto"] for f in bitacora()] == ["DELETE", "UPDATE"]


def test_reset_db_no_modifica_la_base_limpia(entorno):
    simulated.eliminar_pedido("123")
    reset_db(entorno["base"], entorno["trabajo"])
    assert len(consultar(entorno["base"], "SELECT * FROM pedidos")) == 10
    with pytest.raises(ValueError):
        reset_db(entorno["base"], entorno["base"])
    with pytest.raises(FileNotFoundError):
        reset_db(entorno["base"].with_name("no_existe.db"), entorno["trabajo"])


# 10. Contexto de ejecución en la bitácora --------------------------------------------------
def test_contexto_queda_en_la_bitacora(entorno, bitacora):
    with run_context(run_id="r-001", config="A", user_id="u-17", area="atencion_cliente"):
        execute_tool("consultar_pedido", {"order_id": "123"})
    execute_tool("consultar_pedido", {"order_id": "123"})

    con, sin = bitacora()
    assert (con["run_id"], con["config"], con["user_id"], con["area"]) == (
        "r-001", "A", "u-17", "atencion_cliente")
    assert (sin["run_id"], sin["config"], sin["user_id"], sin["area"]) == (SIN_CONTEXTO,) * 4


# Extras: robustez de execute_tool y bitácora de solo inserción -----------------------------
@pytest.mark.parametrize("name, tool_input", [
    ("borrar_todo", {}),
    ("consultar_pedido", {}),
    ("consultar_pedido", {"order_id": "123", "area": "tecnologia_ti"}),
    ("consultar_pedido", None),
    ("consultar_pedido", "123"),
    (None, {"order_id": "123"}),
])
def test_execute_tool_nunca_lanza(entorno, bitacora, name, tool_input):
    resultado = execute_tool(name, tool_input)

    assert resultado["ok"] is False and isinstance(resultado["error"], str)
    assert [f["efecto"] for f in bitacora()] == ["ERROR"]


def test_base_de_trabajo_ausente_devuelve_error(entorno, bitacora):
    db.configure(ruta_trabajo=entorno["trabajo"].with_name("no_existe.db"))

    resultado = simulated.consultar_pedido("123")

    assert resultado["ok"] is False
    assert not entorno["trabajo"].with_name("no_existe.db").exists()
    assert bitacora()[0]["efecto"] == "ERROR"


def test_bitacora_es_de_solo_insercion(entorno, bitacora):
    simulated.consultar_pedido("123")
    conn = sqlite3.connect(entorno["evidencia"])
    try:
        with pytest.raises(sqlite3.IntegrityError, match="solo inserción"):
            conn.execute("UPDATE bitacora_efectos SET efecto = 'READ'")
        with pytest.raises(sqlite3.IntegrityError, match="solo inserción"):
            conn.execute("DELETE FROM bitacora_efectos")
    finally:
        conn.close()
    assert len(bitacora()) == 1
