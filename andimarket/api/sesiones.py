"""Inicio de sesión de la API con los usuarios del directorio de demostración y un token opaco.

Por ahora (Avance 3) la sesión es un token aleatorio (secrets.token_urlsafe) que vive en la memoria
del proceso: al reiniciar la API todos vuelven a iniciar sesión. Pasar a JWT solo cambia esta clase,
no los endpoints.

La identidad (usuario, área y nivel) sale siempre del directorio (andimarket/directorio.py), nunca de
lo que mande el cliente ni de lo que diga el prompt. Todos los usuarios de la demostración comparten
una clave, que se define con la variable de entorno ANDIMARKET_CLAVE_DEMO. El endpoint de login no
dice si falló el usuario o la clave, y tras varios fallos seguidos bloquea ese usuario un rato.
"""

from __future__ import annotations

import hmac
import secrets
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Callable

from andimarket.directorio import buscar
from andimarket.session import Session

DURACION_SEGUNDOS = 8 * 3600       # una jornada
MAX_FALLOS = 5                     # intentos fallidos seguidos por usuario...
VENTANA_FALLOS_SEGUNDOS = 300      # ...en 5 minutos, y el usuario queda bloqueado hasta que pasen


class LoginBloqueado(Exception):
    """Demasiados intentos fallidos para ese usuario; hay que esperar."""


@dataclass(frozen=True)
class SesionActiva:
    token: str
    sesion: Session
    expira: float


class Sesiones:
    def __init__(
        self,
        clave: str,
        *,
        duracion: float = DURACION_SEGUNDOS,
        reloj: Callable[[], float] = time.monotonic,
    ):
        if not clave:
            raise ValueError("la clave de la demostración no puede estar vacía")
        self._clave = clave.encode("utf-8")
        self._duracion = duracion
        self._reloj = reloj
        self._lock = threading.Lock()
        self._activas: dict[str, SesionActiva] = {}
        self._fallos: dict[str, deque[float]] = defaultdict(deque)

    def iniciar(self, usuario: str, clave: str) -> SesionActiva | None:
        """Devuelve la sesión si usuario y clave son válidos; None si no. LoginBloqueado si hay demasiados fallos."""
        clave_usuario = str(usuario or "").strip().casefold()
        ahora = self._reloj()
        with self._lock:
            fallos = self._fallos[clave_usuario]
            while fallos and ahora - fallos[0] > VENTANA_FALLOS_SEGUNDOS:
                fallos.popleft()
            if len(fallos) >= MAX_FALLOS:
                raise LoginBloqueado(clave_usuario)
            persona = buscar(clave_usuario)
            clave_ok = hmac.compare_digest(str(clave or "").encode("utf-8"), self._clave)
            if persona is None or not clave_ok:
                fallos.append(ahora)
                return None
            fallos.clear()
            self._purgar(ahora)
            activa = SesionActiva(secrets.token_urlsafe(32), persona, ahora + self._duracion)
            self._activas[activa.token] = activa
            return activa

    def validar(self, token: str | None) -> Session | None:
        if not token:
            return None
        with self._lock:
            activa = self._activas.get(token)
            if activa is None:
                return None
            if self._reloj() >= activa.expira:
                del self._activas[token]
                return None
            return activa.sesion

    def cerrar(self, token: str | None) -> None:
        with self._lock:
            self._activas.pop(token or "", None)

    def _purgar(self, ahora: float) -> None:
        for token in [t for t, a in self._activas.items() if ahora >= a.expira]:
            del self._activas[token]
