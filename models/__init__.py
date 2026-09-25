"""Interfaz de modelo intercambiable (secciones 5.1 y 8.2 de la propuesta — Persona 4).

    from models import get_model
    modelo = get_model()  # MODEL_BACKEND del entorno, o "simulado" si no hay ninguno

Backends disponibles: "simulado" (determinista, sin llave — el que usa la demostración en
vivo y el que desbloquea a Persona 1 sin depender de ninguna cuota), "gemini" (Google AI
Studio, cuota gratuita sin tarjeta), "groq" (cuota gratuita) y "ollama" (modelo local).

Cada import de backend es perezoso (adentro de la función, no al tope del módulo): pedir el
modelo simulado no debe requerir tener instalada ni configurada ninguna llave de los otros.
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
