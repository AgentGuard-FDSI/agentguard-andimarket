"""Backend Gemini (Google AI Studio, cuota gratuita sin tarjeta).

Variables: GEMINI_API_KEY (obligatoria), GEMINI_MODEL (opcional), MODEL_TEMPERATURE.
El nombre del modelo gratuito disponible cambia con el tiempo: se configura por variable y
se reporta en cada corrida (sección 4 de la propuesta).
"""

from __future__ import annotations

from itertools import count
from typing import Any

from . import _config
from ._formatos import contenido_gemini, respuesta_desde_gemini, tools_gemini
from ._http import post_json
from .base import RespuestaModelo

URL = "https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent"
MODELO_POR_DEFECTO = "gemini-3.8-flash"


class ModeloGemini:
    def __init__(self) -> None:
        self._llave = _config.requerida("GEMINI_API_KEY", "gemini")
        self.modelo = _config.opcional("GEMINI_MODEL", MODELO_POR_DEFECTO)
        self.temperatura = _config.temperatura()
        self.nombre = f"gemini:{self.modelo}"
        self._turno = count(1)

    def generar(self, historial: list[dict[str, Any]], tool_definitions: list[dict[str, Any]]) -> RespuestaModelo:
        sistema, contents = contenido_gemini(historial)
        body: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {"temperature": self.temperatura},
        }
        if tool_definitions:
            body["tools"] = tools_gemini(tool_definitions)
        if sistema:
            body["systemInstruction"] = sistema
        data = post_json(
            URL.format(modelo=self.modelo),
            body,
            headers={"x-goog-api-key": self._llave},  # en cabecera, nunca en la URL (no queda en logs)
            proveedor="Gemini",
        )
        return respuesta_desde_gemini(data, prefijo_id=f"gem-{next(self._turno)}")
