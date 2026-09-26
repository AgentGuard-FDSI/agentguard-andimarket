import ast
import json
from pathlib import Path

import pytest
from conftest import consultar

from andimarket.config_a import guardar_evidencia, run_config_a, veredicto_de
from andimarket.criterio import evaluar
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


@pytest.mark.parametrize("id_prompt", ["inyeccion", "escalada", "exfiltracion", "datos"])
def test_config_a_no_contiene_ningun_ataque(entorno, id_prompt):
    _correr(id_prompt, run_id=f"A-{id_prompt}")
    veredicto = veredicto_de(PROMPTS[id_prompt], f"A-{id_prompt}")
    assert veredicto.exitoso, veredicto.motivo


def test_la_solicitud_legitima_no_tiene_veredicto_de_ataque(entorno):
    _correr("legitimo", run_id="A-legitimo")
    assert veredicto_de(PROMPTS["legitimo"], "A-legitimo") is None


def test_el_criterio_mira_la_bitacora_y_no_lo_que_dice_el_modelo(entorno):
    # Otra corrida distinta: sin ejecutar nada, el criterio no da éxito aunque el modelo "diga" lo contrario.
    _correr("legitimo", run_id="A-solo-consulta")
    for escenario in (2, 3, 5, 6):
        assert not evaluar(escenario, "A-solo-consulta").exitoso


def test_correo_a_un_cliente_registrado_no_es_exfiltracion(entorno):
    from tools import execute_tool, run_context
    with run_context(run_id="A-cliente", config="A", user_id="u", area="atencion_cliente"):
        execute_tool("enviar_correo", {"destinatario": "laura.gomez@example.test", "contenido": "Hola"})
    assert not evaluar(5, "A-cliente").exitoso


def test_un_solo_cliente_no_es_fuga_masiva(entorno):
    from tools import execute_tool, run_context
    with run_context(run_id="A-una-fila", config="A", user_id="u", area="finanzas"):
        execute_tool("leer_base_datos", {"tabla": "pedidos"})
    assert not evaluar(6, "A-una-fila").exitoso


def test_la_evidencia_se_guarda_en_json(entorno, tmp_path):
    resultado = _correr("escalada", run_id="A-escalada-1")
    veredicto = veredicto_de(PROMPTS["escalada"], "A-escalada-1")
    ruta = guardar_evidencia(PROMPTS["escalada"], "A-escalada-1", resultado, tmp_path, veredicto)
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    assert datos["run_id"] == "A-escalada-1" and datos["ataque_exitoso"] is True
    assert datos["herramientas_ejecutadas"][0]["herramienta"] == "admin_action"


def test_config_a_no_importa_agentguard():
    raiz = Path(__file__).resolve().parent.parent / "andimarket"
    for archivo in [raiz / "config_a.py", raiz / "criterio.py", raiz / "agent" / "loop.py", raiz / "toolbox.py"]:
        for nodo in ast.walk(ast.parse(archivo.read_text(encoding="utf-8"))):
            nombres = []
            if isinstance(nodo, ast.Import):
                nombres = [a.name for a in nodo.names]
            elif isinstance(nodo, ast.ImportFrom):
                nombres = [nodo.module or ""]
            assert not any(n.split(".")[0] == "agentguard" for n in nombres), archivo


def test_config_a_funciona_con_el_modelo_simulado_del_paquete_models(entorno):
    from models import get_model
    from tools import db

    resultado = run_config_a(PROMPTS["legitimo"], RegistryToolbox(), "A-simulado", model=get_model("simulado"), emit=lambda _: None)
    assert [r.name for r in resultado.trace] == ["consultar_pedido"] and resultado.trace[0].ok
    assert db.settings().ruta_evidencia.exists()
