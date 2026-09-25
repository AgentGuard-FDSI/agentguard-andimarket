"""Bitácora de efectos (sección 4.3): una fila por invocación de herramienta.

Permite verificar si un ataque tuvo éxito a partir de lo que realmente ocurrió, sin depender
de lo que diga el modelo. Solo se inserta: este módulo no ofrece funciones de actualización ni
de borrado, y la base de evidencia además lo impide con triggers.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from . import db
from .context import get_context

EFECTOS = frozenset({"READ", "UPDATE", "DELETE", "EMAIL", "ADMIN", "ERROR"})


def ahora_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def a_json(valor: Any) -> str:
    """JSON estable (claves ordenadas); lo no serializable se guarda como texto."""
    return json.dumps(valor, sort_keys=True, ensure_ascii=False, default=str)


def registrar_efecto(
    conn: sqlite3.Connection,
    *,
    tool: str,
    args: dict[str, Any],
    efecto: str,
    objetivo: str | None,
    filas_afectadas: int,
    detalle: dict[str, Any],
) -> int:
    """Inserta la fila en ev.bitacora_efectos dentro de la transacción de `conn`."""
    if efecto not in EFECTOS:
        raise ValueError(f"Efecto desconocido: {efecto}")
    ctx = get_context()
    cur = conn.execute(
        "INSERT INTO ev.bitacora_efectos (ts, run_id, config, user_id, area, tool, args_json, "
        "efecto, objetivo, filas_afectadas, detalle_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            ahora_utc(), ctx.run_id, ctx.config, ctx.user_id, ctx.area, str(tool), a_json(args),
            efecto, objetivo, int(filas_afectadas), a_json(detalle),
        ),
    )
    return cur.lastrowid


def registrar_error(
    tool: str, args: dict[str, Any], mensaje: str, *, efecto_intentado: str | None = None, **extra: Any
) -> None:
    """Registra una fila ERROR en su propia transacción. Nunca lanza excepciones.

    Se usa después de revertir la transacción del efecto, o cuando la base de trabajo no se
    pudo abrir. Si ni siquiera la base de evidencia está disponible, no hay dónde registrar.
    """
    try:
        conn = db.connect_evidencia()
    except Exception:
        return
    try:
        with conn:
            registrar_efecto(
                conn,
                tool=tool,
                args=args,
                efecto="ERROR",
                objetivo=extra.pop("objetivo", None),
                filas_afectadas=0,
                detalle={"error": mensaje, "efecto_intentado": efecto_intentado, **extra},
            )
    except Exception:
        pass
    finally:
        conn.close()
