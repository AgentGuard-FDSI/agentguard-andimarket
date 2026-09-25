"""POST JSON con reintentos, compartido por los backends remotos (Gemini, Groq, Ollama).

Las cuotas gratuitas tienen límites por minuto y por día (sección 4.4 de la propuesta): ante
un 429 o un 5xx se espera y se reintenta con espera creciente, respetando Retry-After si el
proveedor lo envía. Cualquier otro error se convierte en ModeloError con un mensaje legible
y sin incluir la llave.
"""

from __future__ import annotations

import time
from typing import Any

import requests

from .base import ModeloError

REINTENTABLES = {429, 500, 502, 503, 504}


def post_json(
    url: str,
    body: dict[str, Any],
    *,
    headers: dict[str, str] | None = None,
    timeout: float = 60.0,
    reintentos: int = 3,
    espera_base: float = 2.0,
    proveedor: str = "modelo",
) -> dict[str, Any]:
    ultimo_error = ""
    for intento in range(reintentos + 1):
        try:
            resp = requests.post(url, json=body, headers=headers or {}, timeout=timeout)
        except requests.RequestException as exc:
            ultimo_error = f"no se pudo conectar con {proveedor}: {type(exc).__name__}"
        else:
            if resp.status_code < 400:
                try:
                    return resp.json()
                except ValueError:
                    raise ModeloError(f"{proveedor} respondió algo que no es JSON") from None
            ultimo_error = f"{proveedor} respondió HTTP {resp.status_code}: {resp.text[:300]}"
            if resp.status_code not in REINTENTABLES:
                raise ModeloError(ultimo_error)
            retry_after = resp.headers.get("Retry-After", "")
            if retry_after.isdigit() and intento < reintentos:
                time.sleep(min(float(retry_after), 60.0))
                continue
        if intento < reintentos:
            time.sleep(espera_base * (2**intento))
    raise ModeloError(f"{ultimo_error} (tras {reintentos} reintentos)")
