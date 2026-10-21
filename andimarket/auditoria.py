"""Audit log de las decisiones de AgentGuard en la Config. B.

Cada llamada a herramienta que pasa por AgentGuard deja exactamente una fila en
ev.audit_logs (base de evidencia, que no se reinicia entre corridas): quién (usuario, área,
nivel, de la sesión), qué (herramienta y argumentos), qué decidió AgentGuard (acción, regla,
motivo), el resultado de la aprobación si fue HITL y si la acción se envió a ejecutar.

El contexto de la corrida (run_id, config) se toma de tools.context, igual que la bitácora de
efectos, para poder cruzar ambas tablas por run_id.

Avance 3: además de esta tabla, cada decisión se encadena con SHA-256 en el AuditChain de
agentguard-core (andimarket/controles.py), y el verificador de entrada deja su fila en
ev.verificador_entrada.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from tools import db
from tools.context import get_context
from tools.effects import a_json, ahora_utc


def registrar_decision(
    *,
    session: Any,
    tool: str,
    arguments: Any,
    decision: Any,
    aprobacion: Any | None,
    autorizada: bool,
) -> int:
    """Inserta la decisión en ev.audit_logs y devuelve el id de la fila. Lanza excepción si falla."""
    ctx = get_context()
    datos = decision.to_dict()
    conn = db.connect_evidencia()
    try:
        with conn:
            cur = conn.execute(
                "INSERT INTO ev.audit_logs (ts, run_id, config, usuario, area, nivel, tool, args_json, "
                "decision, regla, motivo, aprobado, aprobador, autorizada) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    ahora_utc(), ctx.run_id, ctx.config,
                    str(getattr(session, "usuario", "")), str(getattr(session, "area", "")),
                    str(getattr(session, "nivel", "")),
                    str(tool), a_json(arguments),
                    datos["action"], datos["rule"], datos["reason"],
                    None if aprobacion is None else int(bool(aprobacion.approved)),
                    None if aprobacion is None else str(aprobacion.approver),
                    int(bool(autorizada)),
                ),
            )
            return cur.lastrowid
    finally:
        conn.close()


def decisiones_de(run_id: str) -> list[dict[str, Any]]:
    """Filas del audit log de una corrida, en orden."""
    conn = sqlite3.connect(db.init_evidencia(db.settings().ruta_evidencia))
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute("SELECT * FROM audit_logs WHERE run_id = ? ORDER BY id", (run_id,))
        return [dict(f) for f in cur.fetchall()]
    finally:
        conn.close()


def registrar_entrada(*, session: Any, veredicto: Any) -> int:
    """Inserta el veredicto del verificador de entrada en ev.verificador_entrada. Lanza excepción si falla."""
    ctx = get_context()
    datos = veredicto.to_dict()
    conn = db.connect_evidencia()
    try:
        with conn:
            cur = conn.execute(
                "INSERT INTO ev.verificador_entrada (ts, run_id, config, usuario, area, nivel, accion, "
                "temas_json, reglas_json, motivo, notificado) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    ahora_utc(), ctx.run_id, ctx.config,
                    str(getattr(session, "usuario", "")), str(getattr(session, "area", "")),
                    str(getattr(session, "nivel", "")),
                    datos["action"], a_json(datos["topics"]), a_json(datos["rules"]), datos["reason"],
                    int(bool(datos["notified"])),
                ),
            )
            return cur.lastrowid
    finally:
        conn.close()


def entradas_de(run_id: str) -> list[dict[str, Any]]:
    """Veredictos del verificador de entrada de una corrida, en orden."""
    conn = sqlite3.connect(db.init_evidencia(db.settings().ruta_evidencia))
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute("SELECT * FROM verificador_entrada WHERE run_id = ? ORDER BY id", (run_id,))
        return [dict(f) for f in cur.fetchall()]
    finally:
        conn.close()
