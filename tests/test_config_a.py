import ast
import json
from pathlib import Path

import pytest
from conftest import consultar

from andimarket.config_a import guardar_evidencia, run_config_a
from andimarket.prompts import PROMPTS
from andimarket.toolbox import RegistryToolbox


def _correr(id_prompt, run_id="A-prueba"):
    return run_config_a(PROMPTS[id_prompt], RegistryToolbox(), run_id, emit=lambda _: None)


def test_solicitud_legitima_consulta_el_pedido(entorno):
    resultado = _correr("legitimo")
    assert [r.name for r in resultado.trace] == ["consultar_pedido"]
    assert resultado.trace[0].ok


def test_inyeccion_elimina_un_pedido_real_sin_que_nada_lo_impida(entorno):
    _correr("inyeccion")
    pedidos = consultar(entorno["trabajo"], "SELECT order_id FROM pedidos WHERE order_id = '123'")
    assert pedidos == []


def test_escalada_ejecuta_admin_action_siendo_de_atencion_al_cliente(entorno):
    resultado = _correr("escalada")
    assert [r.name for r in resultado.trace] == ["admin_action"] and resultado.trace[0].ok


def test_la_bitacora_registra_config_a_y_el_contexto_de_la_sesion(entorno, bitacora):
    _correr("inyeccion", run_id="A-inyeccion-1")
    filas = [f for f in bitacora() if f["run_id"] == "A-inyeccion-1"]
    assert [f["tool"] for f in filas] == ["consultar_pedido", "eliminar_pedido"]
    assert {(f["config"], f["user_id"], f["area"]) for f in filas} == {("A", "ana.atencion", "atencion_cliente")}


def test_la_ejecucion_es_determinista(entorno):
    a = _correr("escalada")
    b = _correr("escalada")
    assert [(r.name, r.arguments) for r in a.trace] == [(r.name, r.arguments) for r in b.trace]


def test_la_evidencia_se_guarda_en_json(entorno, tmp_path):
    resultado = _correr("escalada", run_id="A-escalada-1")
    ruta = guardar_evidencia(PROMPTS["escalada"], "A-escalada-1", resultado, tmp_path)
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    assert datos["run_id"] == "A-escalada-1"
    assert datos["herramientas_ejecutadas"][0]["herramienta"] == "admin_action"


def test_config_a_no_importa_agentguard():
    raiz = Path(__file__).resolve().parent.parent / "andimarket"
    for archivo in [raiz / "config_a.py", raiz / "agent" / "loop.py", raiz / "toolbox.py"]:
        for nodo in ast.walk(ast.parse(archivo.read_text(encoding="utf-8"))):
            nombres = []
            if isinstance(nodo, ast.Import):
                nombres = [a.name for a in nodo.names]
            elif isinstance(nodo, ast.ImportFrom):
                nombres = [nodo.module or ""]
            assert not any(n.split(".")[0] == "agentguard" for n in nombres), archivo
