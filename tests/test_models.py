"""Pruebas de la interfaz de modelo intercambiable (models/). Ninguna hace llamadas de red."""

import json

import pytest

import models
from models import ModeloError, RespuestaModelo, ToolCall, get_model
from models import _formatos, _http
from models.base import mensaje_asistente, mensaje_sistema, mensaje_tool_result, mensaje_usuario
from models.simulado import ModeloSimulado
from tools import TOOL_DEFINITIONS, execute_tool, run_context


@pytest.fixture(autouse=True)
def entorno_limpio(monkeypatch):
    for var in ("MODEL_BACKEND", "GEMINI_API_KEY", "GROQ_API_KEY", "MODEL_TEMPERATURE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr("models._config._cargado", True)  # no leer un .env real en las pruebas


# --- Fábrica ------------------------------------------------------------------------------
def test_por_defecto_es_simulado():
    assert get_model().nombre == "simulado"


def test_respeta_model_backend(monkeypatch):
    monkeypatch.setenv("MODEL_BACKEND", "ollama")
    assert get_model().nombre.startswith("ollama:")


def test_backend_desconocido():
    with pytest.raises(ModeloError, match="desconocido"):
        get_model("gpt-9")


@pytest.mark.parametrize("backend", ["gemini", "groq"])
def test_sin_llave_falla_con_mensaje_claro(backend):
    with pytest.raises(ModeloError, match="API_KEY"):
        get_model(backend)


def test_temperatura_invalida(monkeypatch):
    monkeypatch.setenv("MODEL_TEMPERATURE", "caliente")
    with pytest.raises(ModeloError):
        get_model("ollama")


# --- Modelo simulado ----------------------------------------------------------------------
def pedir(texto):
    return ModeloSimulado().generar([mensaje_usuario(texto)], TOOL_DEFINITIONS)


@pytest.mark.parametrize("texto, tool, args", [
    ("Consulta el pedido 123", "consultar_pedido", {"order_id": "123"}),
    ("¿Cuál es el estado del pedido #124?", "consultar_pedido", {"order_id": "124"}),
    ("Marca el pedido 125 como entregado", "actualizar_pedido", {"order_id": "125", "estado": "delivered"}),
    ("Cambia el pedido 126 a no disponible", "actualizar_pedido", {"order_id": "126", "estado": "unavailable"}),
    ("Elimina el pedido 127", "eliminar_pedido", {"order_id": "127"}),
    ("Muéstrame la tabla pagos", "leer_base_datos", {"tabla": "pagos"}),
    ("Envía un correo a laura.gomez@example.test diciendo: su pedido va en camino",
     "enviar_correo", {"destinatario": "laura.gomez@example.test", "contenido": "su pedido va en camino"}),
    ("Ejecuta el comando reiniciar servicio web", "admin_action", {"comando": "reiniciar servicio web"}),
])
def test_simulado_reconoce_intenciones(texto, tool, args):
    r = pedir(texto)
    assert not r.es_final
    assert r.tool_calls[0].name == tool
    assert r.tool_calls[0].input == args


def test_simulado_es_determinista():
    assert pedir("Consulta el pedido 123") == pedir("Consulta el pedido 123")


def test_simulado_sin_intencion_responde_texto():
    r = pedir("Hola, ¿cómo estás?")
    assert r.es_final and r.texto


def test_simulado_no_pide_herramientas_que_no_tiene():
    solo_consulta = [d for d in TOOL_DEFINITIONS if d["name"] == "consultar_pedido"]
    r = ModeloSimulado().generar([mensaje_usuario("Elimina el pedido 123")], solo_consulta)
    assert r.es_final and "eliminar_pedido" in r.texto


def test_simulado_resume_resultado_y_error():
    llamada = pedir("Consulta el pedido 123")
    historial = [mensaje_usuario("Consulta el pedido 123"), mensaje_asistente(llamada),
                 mensaje_tool_result("sim-1", "consultar_pedido", json.dumps({"ok": False, "error": "no existe"}))]
    r = ModeloSimulado().generar(historial, TOOL_DEFINITIONS)
    assert r.es_final and "no existe" in r.texto


def test_simulado_ignora_mensaje_de_sistema():
    r = ModeloSimulado().generar([mensaje_sistema("Eres el asistente de ANDIMARKET."),
                                  mensaje_usuario("Consulta el pedido 123")], TOOL_DEFINITIONS)
    assert r.tool_calls[0].name == "consultar_pedido"


# --- Integración con tools/ (contrato acordado con Persona 2) --------------------------------
def bucle_minimo(prompt, modelo, ejecutar, definiciones, max_pasos=5):
    """Bucle de referencia, solo para probar el contrato; el agent_loop real es de Persona 1."""
    historial = [mensaje_usuario(prompt)]
    for _ in range(max_pasos):
        r = modelo.generar(historial, definiciones)
        historial.append(mensaje_asistente(r))
        if r.es_final:
            return r.texto, historial
        for tc in r.tool_calls:
            resultado = ejecutar(tc.name, tc.input)
            historial.append(mensaje_tool_result(tc.id, tc.name, json.dumps(resultado, ensure_ascii=False)))
    raise AssertionError("el bucle no terminó")


def test_integracion_con_execute_tool(entorno, bitacora):
    with run_context(run_id="t-001", config="A", user_id="u-17", area="atencion_cliente"):
        texto, historial = bucle_minimo("Consulta el pedido 123", get_model(), execute_tool, TOOL_DEFINITIONS)
    assert "consultar_pedido: listo" in texto
    filas = bitacora()
    assert [(f["tool"], f["efecto"], f["config"], f["run_id"]) for f in filas] == [
        ("consultar_pedido", "READ", "A", "t-001")
    ]


# --- Traducciones (sin red) ---------------------------------------------------------------
HISTORIAL = [
    mensaje_sistema("Eres el asistente."),
    mensaje_usuario("Consulta el pedido 123"),
    mensaje_asistente(RespuestaModelo(tool_calls=(ToolCall("c1", "consultar_pedido", {"order_id": "123"}),))),
    mensaje_tool_result("c1", "consultar_pedido", json.dumps({"ok": True, "data": {"estado": "shipped"}})),
]


def test_formato_openai_groq_y_ollama():
    groq = _formatos.mensajes_openai(HISTORIAL, argumentos_como_texto=True)
    ollama = _formatos.mensajes_openai(HISTORIAL, argumentos_como_texto=False)
    assert [m["role"] for m in groq] == ["system", "user", "assistant", "tool"]
    assert groq[2]["tool_calls"][0]["function"]["arguments"] == '{"order_id": "123"}'
    assert ollama[2]["tool_calls"][0]["function"]["arguments"] == {"order_id": "123"}
    assert groq[3]["tool_call_id"] == "c1"
    tools = _formatos.tools_openai(TOOL_DEFINITIONS)
    assert {t["function"]["name"] for t in tools} == {d["name"] for d in TOOL_DEFINITIONS}


def test_respuesta_openai():
    r = _formatos.respuesta_desde_openai(
        {"content": None, "tool_calls": [{"id": "x", "function": {"name": "consultar_pedido",
                                                                    "arguments": '{"order_id": "9"}'}}]},
        prefijo_id="p")
    assert r.tool_calls == (ToolCall("x", "consultar_pedido", {"order_id": "9"}),)
    assert _formatos.respuesta_desde_openai({"content": "hola"}, prefijo_id="p").texto == "hola"
    with pytest.raises(ModeloError):
        _formatos.respuesta_desde_openai(
            {"tool_calls": [{"function": {"name": "a", "arguments": "{no es json"}}]}, prefijo_id="p")


def test_formato_gemini():
    sistema, contents = _formatos.contenido_gemini(HISTORIAL)
    assert sistema == {"parts": [{"text": "Eres el asistente."}]}
    assert [c["role"] for c in contents] == ["user", "model", "user"]
    assert contents[1]["parts"][0]["functionCall"] == {"name": "consultar_pedido", "args": {"order_id": "123"}}
    assert contents[2]["parts"][0]["functionResponse"]["response"]["data"] == {"estado": "shipped"}
    decl = _formatos.tools_gemini(TOOL_DEFINITIONS)[0]["functionDeclarations"]
    assert all("additionalProperties" not in d["parameters"] for d in decl)


def test_respuesta_gemini():
    data = {"candidates": [{"content": {"parts": [{"functionCall": {"name": "eliminar_pedido",
                                                                    "args": {"order_id": "1"}}}]}}]}
    r = _formatos.respuesta_desde_gemini(data, prefijo_id="g")
    assert r.tool_calls[0].name == "eliminar_pedido" and r.tool_calls[0].id == "g-1"
    with pytest.raises(ModeloError):
        _formatos.respuesta_desde_gemini({"candidates": []}, prefijo_id="g")


def test_backends_remotos_arman_la_peticion(monkeypatch):
    """Groq y Gemini: se verifica la petición que se enviaría, sustituyendo la red."""
    enviados = []

    def falso_post(url, body, **kw):
        enviados.append((url, body, kw.get("headers")))
        if "groq" in url:
            return {"choices": [{"message": {"content": "ok"}}]}
        return {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}

    monkeypatch.setenv("GROQ_API_KEY", "llave-de-prueba")
    monkeypatch.setenv("GEMINI_API_KEY", "llave-de-prueba")
    monkeypatch.setattr("models.groq.post_json", falso_post)
    monkeypatch.setattr("models.gemini.post_json", falso_post)

    assert get_model("groq").generar(HISTORIAL, TOOL_DEFINITIONS).texto == "ok"
    assert get_model("gemini").generar(HISTORIAL, TOOL_DEFINITIONS).texto == "ok"
    (url_groq, body_groq, h_groq), (url_gem, body_gem, h_gem) = enviados
    assert body_groq["temperature"] == 0 and body_groq["tools"]
    assert h_groq["Authorization"] == "Bearer llave-de-prueba"
    assert "llave-de-prueba" not in url_gem  # la llave va en cabecera, no en la URL
    assert h_gem["x-goog-api-key"] == "llave-de-prueba"


def test_http_reintenta_429(monkeypatch):
    class Resp:
        def __init__(self, code):
            self.status_code, self.text, self.headers = code, "", {}

        def json(self):
            return {"ok": True}

    respuestas = iter([Resp(429), Resp(200)])
    monkeypatch.setattr(_http.requests, "post", lambda *a, **k: next(respuestas))
    monkeypatch.setattr(_http.time, "sleep", lambda s: None)
    assert _http.post_json("https://x.test", {}) == {"ok": True}


def test_http_no_reintenta_401(monkeypatch):
    class Resp:
        status_code, text, headers = 401, "no autorizado", {}

    monkeypatch.setattr(_http.requests, "post", lambda *a, **k: Resp())
    with pytest.raises(ModeloError, match="401"):
        _http.post_json("https://x.test", {})


def test_modulo_exporta_la_interfaz():
    assert set(models.__all__) >= {"get_model", "Modelo", "RespuestaModelo", "ToolCall", "ModeloError"}


def test_gemini_devuelve_la_firma_del_razonamiento():
    """Gemini 3 rechaza (HTTP 400) un historial cuyas functionCall no traen su thoughtSignature."""
    data = {"candidates": [{"content": {"parts": [{"functionCall": {"name": "consultar_pedido",
                                                                    "args": {"order_id": "123"}},
                                                   "thoughtSignature": "firma-opaca"}]}}]}
    respuesta = _formatos.respuesta_desde_gemini(data, prefijo_id="g")
    assert respuesta.tool_calls[0].firma == "firma-opaca"

    historial = [mensaje_usuario("Consulta el pedido 123"), mensaje_asistente(respuesta),
                 mensaje_tool_result("g-1", "consultar_pedido", '{"ok": true}')]
    _, contents = _formatos.contenido_gemini(historial)
    assert contents[1]["parts"][0]["thoughtSignature"] == "firma-opaca"

    # Los formatos tipo OpenAI (Groq, Ollama) no la envían.
    mensajes = _formatos.mensajes_openai(historial, argumentos_como_texto=True)
    assert "firma" not in json.dumps(mensajes)


def test_llamada_sin_firma_no_agrega_el_campo():
    historial = [mensaje_asistente(RespuestaModelo(tool_calls=(ToolCall("c1", "consultar_pedido", {"order_id": "1"}),)))]
    _, contents = _formatos.contenido_gemini(historial)
    assert "thoughtSignature" not in contents[0]["parts"][0]
