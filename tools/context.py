"""Contexto de ejecución de una corrida (run_id, config, user_id, area).

No son parámetros de las herramientas: el modelo nunca los ve ni los puede cambiar. El runner
los fija antes de cada corrida y las herramientas los copian a la bitácora de efectos. Si no
hay contexto fijado, se registra "sin_contexto" en cada campo.

    with run_context(run_id="r-001", config="A", user_id="u-17", area="atencion_cliente"):
        execute_tool("consultar_pedido", {"order_id": "123"})
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Iterator

SIN_CONTEXTO = "sin_contexto"


@dataclass(frozen=True)
class ExecutionContext:
    run_id: str = SIN_CONTEXTO
    config: str = SIN_CONTEXTO
    user_id: str = SIN_CONTEXTO
    area: str = SIN_CONTEXTO


_current: ContextVar[ExecutionContext] = ContextVar("andimarket_execution_context")


def _texto(valor: object) -> str:
    return SIN_CONTEXTO if valor is None or valor == "" else str(valor)


def set_context(
    *, run_id: object = None, config: object = None, user_id: object = None, area: object = None
) -> Token:
    """Fija el contexto actual y devuelve el token para restaurar el anterior."""
    return _current.set(
        ExecutionContext(
            run_id=_texto(run_id), config=_texto(config), user_id=_texto(user_id), area=_texto(area)
        )
    )


def reset_context(token: Token) -> None:
    _current.reset(token)


def get_context() -> ExecutionContext:
    return _current.get(ExecutionContext())


@contextmanager
def run_context(
    *, run_id: object = None, config: object = None, user_id: object = None, area: object = None
) -> Iterator[ExecutionContext]:
    token = set_context(run_id=run_id, config=config, user_id=user_id, area=area)
    try:
        yield get_context()
    finally:
        reset_context(token)
