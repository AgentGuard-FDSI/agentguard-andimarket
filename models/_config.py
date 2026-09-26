"""Configuración de los backends: variables de entorno y un lector mínimo de `.env`.

Las llaves de los modelos gratuitos nunca van en el repositorio (sección 5.1): se leen de
variables de entorno o de un archivo `.env` local, que está en el .gitignore. El lector no
sobrescribe variables ya definidas en el entorno, así que una variable exportada en la
terminal siempre gana sobre el `.env`.

No se usa python-dotenv para no agregar una dependencia por diez líneas.
"""

from __future__ import annotations

import os
from pathlib import Path

from .base import ModeloError

_cargado = False


def cargar_dotenv(ruta: str | Path = ".env") -> None:
    """Carga `ruta` una sola vez por proceso, si existe. Formato: CLAVE=valor por línea."""
    global _cargado
    if _cargado:
        return
    _cargado = True
    archivo = Path(ruta)
    if not archivo.is_file():
        return
    for linea in archivo.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, valor = linea.split("=", 1)
        clave, valor = clave.strip(), valor.strip().strip('"').strip("'")
        if clave and clave not in os.environ:
            os.environ[clave] = valor


def requerida(nombre: str, backend: str) -> str:
    valor = os.environ.get(nombre, "").strip()
    if not valor:
        raise ModeloError(
            f"El backend '{backend}' necesita la variable {nombre}. Cópiala de .env.example a tu "
            f".env local (que no se versiona) o usa MODEL_BACKEND=simulado."
        )
    return valor


def opcional(nombre: str, por_defecto: str) -> str:
    return os.environ.get(nombre, "").strip() or por_defecto


def temperatura() -> float:
    """Temperatura fija por corrida (sección 4): la misma en Config. A y Config. B."""
    valor = opcional("MODEL_TEMPERATURE", "0")
    try:
        t = float(valor)
    except ValueError:
        raise ModeloError(f"MODEL_TEMPERATURE debe ser un número; se recibió {valor!r}") from None
    if not 0 <= t <= 2:
        raise ModeloError("MODEL_TEMPERATURE debe estar entre 0 y 2")
    return t
