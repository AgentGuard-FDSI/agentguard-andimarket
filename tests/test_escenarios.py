"""Escenarios 1 a 6 con variantes (sección 4.1) y el Experiment Runner (andimarket/comparar.py)."""

import json
from collections import Counter

import pytest
from conftest import consultar

from andimarket.criterio import CRITERIOS
from andimarket.escenarios import ESCENARIOS, PEDIDO_INYECTADO, VARIANTES
from andimarket.prompts import PROMPTS
from tools import TOOLS, db

pytest.importorskip("agentguard", reason="instalar agentguard-core: pip install -e ../agentguard-core")

LEGITIMOS = {1, 4}
ATAQUES = {2, 3, 5, 6}


# ---------------------------------------------------------------------------
# El conjunto de variantes
# ---------------------------------------------------------------------------
def test_cinco_variantes_por_escenario_y_diez_legitimas():
    por_escenario = Counter(v.escenario for v in VARIANTES.values())
    assert por_escenario == {e: 5 for e in ESCENARIOS}
    assert sum(not v.es_ataque for v in VARIANTES.values()) == 10
    assert {v.escenario for v in VARIANTES.values() if v.es_ataque} == ATAQUES


def test_los_prompts_de_la_demo_no_cambian():
    """La API y el frontend usan estos cinco por nombre."""
    assert set(PROMPTS) == {"legitimo", "inyeccion", "escalada", "exfiltracion", "datos"}
    assert not set(PROMPTS) & set(VARIANTES)


def test_los_textos_no_se_repiten():
    textos = [v.texto for v in VARIANTES.values()]
    assert len(set(textos)) == len(textos)


def test_cada_ataque_tiene_criterio_de_exito_y_cada_legitima_su_efecto():
    for v in VARIANTES.values():
        if v.es_ataque:
            assert v.escenario in CRITERIOS and v.efecto_esperado is None, v.id
        else:
            assert v.escenario in LEGITIMOS and v.efecto_esperado in TOOLS, v.id


def test_el_guion_de_cada_variante_usa_herramientas_y_argumentos_validos():
    for v in VARIANTES.values():
        for _texto, llamadas in v.pasos:
            for herramienta, argumentos in llamadas:
                esquema = TOOLS[herramienta]["definition"]["input_schema"]
                assert set(argumentos) == set(esquema["required"]), (v.id, herramienta)


def test_cada_legitima_la_puede_hacer_el_area_que_la_pide():
    """Si no, la Config. B la bloquearía y se contaría como falso positivo por un error del conjunto."""
    from andimarket.config_b import crear_guard

    policy = crear_guard().policy
    for v in VARIANTES.values():
        if not v.es_ataque:
            assert v.sesion.area in policy.get_tool(v.efecto_esperado).areas, v.id


def test_cada_ataque_lo_pide_alguien_sin_permiso_o_con_argumentos_no_permitidos():
    """Un ataque que el área sí puede hacer con esos argumentos no mediría el control de acceso."""
    from andimarket.config_b import crear_controles, crear_guard
    from andimarket.session import Session

    controles = crear_controles(crear_guard())
    try:
        for v in VARIANTES.values():
            if not v.es_ataque:
                continue
            dañina = v.pasos[-1][1][-1]  # la última herramienta del guion es la del efecto dañino
            decision = controles.guard.authorize(v.sesion, dañina[0], dañina[1], solicitud=f"chequeo-{v.id}")
            assert decision.action.value == "BLOCK", (v.id, str(decision))
    finally:
        controles.cerrar()
    assert Session  # noqa: B018 - el import documenta qué se valida


def test_exfiltracion_usa_comentarios_y_destinatarios_distintos():
    variantes = [v for v in VARIANTES.values() if v.escenario == 5]
    assert len({v.comentario_inyectado for v in variantes}) == 5
    destinatarios = {v.pasos[-1][1][0][1]["destinatario"] for v in variantes}
    assert len(destinatarios) == 5
    for d in destinatarios:
        assert d in next(v.comentario_inyectado for v in variantes if d in v.comentario_inyectado)
        assert not d.endswith("@andimarket.example.test")  # ninguno es del dominio corporativo
    assert all(PEDIDO_INYECTADO in v.texto for v in variantes)


def test_preparar_base_escribe_el_comentario_de_la_variante(entorno):
    variante = VARIANTES["e5_nota_sistema"]
    variante.preparar_base()
    [fila] = consultar(entorno["trabajo"], "SELECT comentario FROM pedidos WHERE order_id = ?", (PEDIDO_INYECTADO,))
    assert fila["comentario"] == variante.comentario_inyectado
    # La base limpia no cambia: el próximo reset_db vuelve al comentario de la semilla.
    [limpia] = consultar(entorno["base"], "SELECT comentario FROM pedidos WHERE order_id = ?", (PEDIDO_INYECTADO,))
    assert limpia["comentario"] != variante.comentario_inyectado


def test_las_variantes_legitimas_no_preparan_nada(entorno):
    antes = consultar(entorno["trabajo"], "SELECT * FROM pedidos ORDER BY order_id")
    VARIANTES["e1_consulta_123"].preparar_base()
    assert consultar(entorno["trabajo"], "SELECT * FROM pedidos ORDER BY order_id") == antes


# ---------------------------------------------------------------------------
# Experiment Runner con el conjunto de escenarios
# ---------------------------------------------------------------------------
@pytest.fixture
def comparar():
    from andimarket import comparar as modulo

    anterior = db.settings()
    yield modulo
    db.configure(ruta_trabajo=anterior.ruta_trabajo, ruta_evidencia=anterior.ruta_evidencia,
                 max_filas=anterior.max_filas)


def _ejecutar(comparar, tmp_path, **kw):
    kw.setdefault("aprobador", "auto")
    kw.setdefault("conjunto", "escenarios")
    return comparar.ejecutar("guion", kw.pop("repeticiones", 1), carpeta_datos=tmp_path / "datos",
                             carpeta_salida=tmp_path / "salida", emit=lambda _: None, **kw)


def test_escenarios_con_el_modelo_de_guion(comparar, tmp_path):
    ruta_json, ruta_md, m = _ejecutar(comparar, tmp_path)

    assert (m["A"]["ataques_exitosos"], m["A"]["intentos_de_ataque"]) == (20, 20)
    assert (m["B"]["ataques_exitosos"], m["B"]["intentos_de_ataque"]) == (0, 20)
    assert m["A"]["legitimas_completadas"] == m["B"]["legitimas_completadas"] == 1.0
    assert m["B"]["falsos_positivos"] == 0.0
    assert m["B"]["friccion"] == 0.5  # las 5 escrituras legítimas pasan por HITL
    assert set(m["por_escenario"]) == {"1", "2", "3", "4", "5", "6"}
    capas_6 = m["por_escenario"]["6"]["B"]["contencion_por_capa"]
    assert capas_6["verificador_entrada"] + capas_6["authorize"] == 5 and capas_6["modelo"] == 0

    datos = json.loads(ruta_json.read_text(encoding="utf-8"))
    assert (datos["conjunto"], datos["verificador"], datos["aprobador"]) == ("escenarios", True, "auto")
    assert len(datos["corridas"]) == 60
    md = ruta_md.read_text(encoding="utf-8")
    assert "## Resultado por escenario (sección 4.1)" in md and "`e5_ingles`" in md
    assert ruta_json.name == "comparacion_guion_escenarios.json"


def test_sin_aprobacion_las_escrituras_legitimas_no_se_completan(comparar, tmp_path):
    _, _, m = _ejecutar(comparar, tmp_path, aprobador="rechazar")
    assert m["por_escenario"]["4"]["B"]["completadas"] == 0
    assert m["por_escenario"]["4"]["A"]["completadas"] == 5
    assert m["por_escenario"]["1"]["B"]["completadas"] == 5  # las consultas no pasan por HITL


def test_sin_verificador_el_escenario_6_lo_contiene_authorize(comparar, tmp_path):
    ruta_json, _, m = _ejecutar(comparar, tmp_path, verificador=False)
    capas = m["por_escenario"]["6"]["B"]["contencion_por_capa"]
    assert (capas["authorize"], capas["verificador_entrada"]) == (5, 0)
    assert m["B"]["rechazos_entrada"] == 0
    assert ruta_json.name == "comparacion_guion_escenarios_sin_verificador.json"


def test_reanudar_continua_sin_repetir_corridas(comparar, tmp_path):
    ruta_json, _, _ = _ejecutar(comparar, tmp_path, repeticiones=1)
    primeras = {c["run_id"] for c in json.loads(ruta_json.read_text(encoding="utf-8"))["corridas"]}

    llamadas = []
    original = comparar.correr

    def contar(*args, **kwargs):
        llamadas.append(args[:3])
        return original(*args, **kwargs)

    comparar.correr = contar
    try:
        ruta_json, _, m = _ejecutar(comparar, tmp_path, repeticiones=2, reanudar=True)
    finally:
        comparar.correr = original

    assert len(llamadas) == 60 and {rep for (_, _, rep) in llamadas} == {2}  # solo la repetición nueva
    corridas = json.loads(ruta_json.read_text(encoding="utf-8"))["corridas"]
    assert len(corridas) == 120 and primeras <= {c["run_id"] for c in corridas}
    assert m["A"]["intentos_de_ataque"] == 40


def test_reanudar_reintenta_las_corridas_que_fallaron(comparar, tmp_path, monkeypatch):
    from models.base import ModeloError

    original = comparar.crear_modelo
    fallas = {"quedan": 2}  # falla la primera vez A y B de esa variante; al reanudar ya hay cuota

    class SinCuota:
        nombre = "guion"

        def generar(self, *_):
            raise ModeloError("HTTP 429: cuota agotada")

    def crear(nombre, prompt):
        if fallas["quedan"] and prompt.id == "e2_reembolsado":
            fallas["quedan"] -= 1
            return SinCuota()
        return original(nombre, prompt)

    monkeypatch.setattr(comparar, "crear_modelo", crear)
    _, _, m = _ejecutar(comparar, tmp_path)
    assert m["errores"] == 2  # A y B de esa variante

    _, _, m = _ejecutar(comparar, tmp_path, reanudar=True)
    assert m["errores"] == 0 and m["A"]["intentos_de_ataque"] == 20


def test_la_temperatura_se_fija_y_se_reporta(comparar, tmp_path, monkeypatch):
    monkeypatch.setenv("MODEL_TEMPERATURE", "0")
    ruta_json, ruta_md, _ = _ejecutar(comparar, tmp_path, temperatura=0.3)
    assert json.loads(ruta_json.read_text(encoding="utf-8"))["temperatura"] == "0.3"
    assert "(temperatura 0.3)" in ruta_md.read_text(encoding="utf-8")


def test_el_conjunto_demo_sigue_siendo_el_de_la_api(comparar, tmp_path):
    """La API llama ejecutar("guion", repeticiones, ...) sin conjunto: deben seguir los 5 prompts."""
    ruta_json, _, m = comparar.ejecutar("guion", 1, carpeta_datos=tmp_path / "d", carpeta_salida=tmp_path / "s",
                                        emit=lambda _: None)
    assert set(m["por_prompt"]) == set(PROMPTS)
    assert ruta_json.name == "comparacion_guion.json"


def test_conjunto_o_aprobador_desconocido(comparar, tmp_path):
    with pytest.raises(ValueError, match="conjunto"):
        _ejecutar(comparar, tmp_path, conjunto="otro")
    with pytest.raises(ValueError, match="aprobador"):
        _ejecutar(comparar, tmp_path, aprobador="quizas")
