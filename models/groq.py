"""Backend Groq (cuota gratuita; API compatible con el formato de OpenAI).

Variables: GROQ_API_KEY (obligatoria), GROQ_MODEL (opcional), MODEL_TEMPERATURE.
"""

from __future__ import annotations

from itertools import count
from typing import Any

from . import _config
from ._formatos import mensajes_openai, respuesta_desde_openai, tools_openai
from ._http import post_json
from .base import ModeloError, RespuestaModelo

URL = "https://api.groq.com/openai/v1/chat/completions"
MODELO_POR_DEFECTO = "llama-3.3-70b-versatile"


class ModeloGroq:
    def __init__(self) -> None:
        self._llave = _config.requerida("GROQ_API_KEY", "groq")
        self.modelo = _config.opcional("GROQ_MODEL", MODELO_POR_DEFECTO)
        self.temperatura = _config.temperatura()
        self.nombre = f"groq:{self.modelo}"
        self._turno = count(1)

    def generar(self, historial: list[dict[str, Any]], tool_definitions: list[dict[str, Any]]) -> RespuestaModelo:
        body: dict[str, Any] = {
            "model": self.modelo,
            "messages": mensajes_openai(historial, argumentos_como_texto=True),
            "temperature": self.temperatura,
        }
        if tool_definitions:
            body["tools"] = tools_openai(tool_definitions)
            body["tool_choice"] = "auto"
        data = post_json(URL, body, headers={"Authorization": f"Bearer {self._llave}"}, proveedor="Groq")
        try:
            mensaje = data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError):
            raise ModeloError("Groq devolvió una respuesta sin choices[0].message") from None
        return respuesta_desde_openai(mensaje, prefijo_id=f"groq-{next(self._turno)}")
