"""Elección del modelo de una corrida, compartida por la Config. A, la Config. B y el experimento.

* "guion" (por defecto): el modelo de guion de cada prompt (andimarket/prompts.py). Determinista y
  sin red; reproduce siempre el ataque. Es el de la demostración en vivo.
* "simulado", "gemini", "groq", "ollama": los backends del paquete `models`. Los remotos leen su
  llave de las variables de entorno o del `.env` local (ver .env.example).

Cada corrida recibe un modelo nuevo, para que ninguna herede estado de la anterior.
"""

from __future__ import annotations

from models import BACKENDS, get_model
from models.base import Modelo

from andimarket.prompts import Prompt

MODELOS = ("guion", *BACKENDS)


def crear_modelo(nombre: str, prompt: Prompt) -> Modelo:
    if nombre == "guion":
        return prompt.modelo()
    return get_model(nombre)


def nombre_de(modelo: Modelo) -> str:
    """Nombre que se reporta en la evidencia, p. ej. "guion" o "gemini:gemini-2.5-flash"."""
    return str(getattr(modelo, "nombre", type(modelo).__name__))
