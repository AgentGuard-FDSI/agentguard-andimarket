import ast
import json
from pathlib import Path

import pytest

from andimarket.config_a import guardar_evidencia, run_config_a
from andimarket.prompts import PROMPTS
from tests.fake_tools import FakeToolbox


def _correr(id_prompt, toolbox=None):
    return run_config_a(PROMPTS[id_prompt], toolbox or FakeToolbox(), emit=lambda _: None)


@pytest.mark.parametrize("id_prompt", sorted(PROMPTS))
def test_config_a_ejecuta_todo_lo_que_el_modelo_pide(id_prompt):
    toolbox = FakeToolbox()
    _correr(id_prompt, toolbox)
    pedidas = [(c.name, c.arguments) for _, llamadas in PROMPTS[id_prompt].pasos for c in llamadas]
    assert toolbox.llamadas == pedidas


def test_ataques_ejecutan_herramientas_fuera_del_alcance_del_area():
    assert "eliminar_pedido" in [r.name for r in _correr("inyeccion").trace]
    assert "admin_action" in [r.name for r in _correr("escalada").trace]


def test_la_ejecucion_es_determinista():
    a = _correr("inyeccion")
    b = _correr("inyeccion")
    assert [(r.name, r.arguments) for r in a.trace] == [(r.name, r.arguments) for r in b.trace]


def test_la_evidencia_se_guarda_en_json(tmp_path):
    resultado = _correr("escalada")
    ruta = guardar_evidencia(PROMPTS["escalada"], resultado, tmp_path)
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    assert datos["herramientas_ejecutadas"][0]["herramienta"] == "admin_action"


def test_config_a_no_importa_agentguard():
    raiz = Path(__file__).resolve().parent.parent / "andimarket"
    for archivo in [raiz / "config_a.py", raiz / "agent" / "loop.py"]:
        for nodo in ast.walk(ast.parse(archivo.read_text(encoding="utf-8"))):
            nombres = []
            if isinstance(nodo, ast.Import):
                nombres = [a.name for a in nodo.names]
            elif isinstance(nodo, ast.ImportFrom):
                nombres = [nodo.module or ""]
            assert not any(n.split(".")[0] == "agentguard" for n in nombres), archivo
