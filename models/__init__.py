"""Interfaz de modelo intercambiable.

    from models import get_model
    modelo = get_model()  # MODEL_BACKEND del entorno, o "simulado" si no hay ninguno
"""

from __future__ import annotations

import os

from .base import Modelo, ModeloError, RespuestaModelo, ToolCall

BACKENDS = ("simulado", "gemini", "groq", "ollama")


def get_model(nombre: str | None = None) -> Modelo:
    """Devuelve el backend pedido explícitamente, o el de MODEL_BACKEND, o "simulado"."""
    from ._config import cargar_dotenv

    cargar_dotenv()
    nombre =(nombre or os.environ.get("MODEL_BACKEND") or "simulado").strip().lower()
    if nombre not in BACKENDS:
        raise ModeloError(f"backend de modelo desconocido: {nombre!r}; válidos: {BACKENDS}")

    if nombre == "simulado":
        from .simulado import ModeloSimulado

        return ModeloSimulado()
    if nombre == "gemini":
        from .gemini import ModeloGemini

        return ModeloGemini()
    if nombre == "groq":
        from .groq import ModeloGroq

        return ModeloGroq()
    from .ollama import ModeloOllama

    return ModeloOllama()


__all__ = ["BACKENDS", "Modelo", "ModeloError", "RespuestaModelo", "ToolCall", "get_model"]
