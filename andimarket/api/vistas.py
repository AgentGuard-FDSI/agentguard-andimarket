"""Lo que la API muestra de cada pieza, ya filtrado por quién pregunta.

Regla de visibilidad del log encadenado (Seguridad): cada persona ve sus propias decisiones y
veredictos, las solicitudes HITL en las que fue solicitante o aprobador, y los avisos que originó
o que van dirigidos a su área. Tecnología recibe así las alertas de toda la organización (son
para su área), pero no ve las decisiones de los demás. La verificación de integridad de la cadena
la puede pedir cualquiera: solo dice si cierra y cuántas entradas revisó.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import yaml

from agentguard import AuditChain, StoredApproval

from andimarket.session import Session
from tools import db

TIPOS_DE_AVISO = ("notificacion",)
TIPOS_HITL = ("hitl_solicitada", "hitl_decidida", "hitl_intento_rechazado", "hitl_anulada")


def sesion_a_dict(sesion: Session) -> dict[str, str]:
    return {"usuario": sesion.usuario, "area": sesion.area, "nivel": sesion.nivel}


def solicitud_a_dict(s: StoredApproval) -> dict[str, Any]:
    return {
        "id": s.id,
        "ts": s.ts,
        "run_id": s.run_id,
        "solicitante": {"usuario": s.usuario, "area": s.area, "nivel": s.nivel},
        "herramienta": s.tool,
        "argumentos": dict(s.arguments),
        "motivo": s.reason,
        "estado": s.estado,
        "aprobador": s.aprobador,
        "ts_decision": s.ts_decision,
        "comentario": s.comentario,
    }


# ---------------------------------------------------------------------------
# Log encadenado
# ---------------------------------------------------------------------------
def visible_para(record: dict[str, Any], sesion: Session, solicitudes_propias: set[int]) -> bool:
    tipo = record.get("tipo")
    if tipo in ("decision", "verificador_entrada"):
        return record.get("usuario") == sesion.usuario
    if tipo in TIPOS_DE_AVISO:
        return record.get("usuario") == sesion.usuario or record.get("area_destino") == sesion.area
    if tipo in TIPOS_HITL:
        if sesion.usuario in (record.get("usuario"), record.get("solicitante"), record.get("aprobador")):
            return True
        return record.get("solicitud") in solicitudes_propias  # anulación de una solicitud propia
    return False


def entradas_visibles(cadena: AuditChain, sesion: Session) -> list[dict[str, Any]]:
    """Entradas del log encadenado que puede ver la sesión, de la más reciente a la más antigua."""
    entradas = list(cadena.entries())
    propias = {
        e.record.get("solicitud") for e in entradas
        if e.record.get("tipo") == "hitl_solicitada" and e.record.get("usuario") == sesion.usuario
    }
    visibles = [
        {"seq": e.seq, "ts": e.ts, "hash": e.hash, "prev_hash": e.prev_hash, "registro": dict(e.record)}
        for e in entradas
        if visible_para(dict(e.record), sesion, propias)
    ]
    return list(reversed(visibles))


def resumen_seguridad(visibles: list[dict[str, Any]]) -> dict[str, Any]:
    decisiones = {"ALLOW": 0, "BLOCK": 0, "HITL": 0}
    rechazos, avisos, alertas = 0, 0, 0
    for e in visibles:
        r = e["registro"]
        if r.get("tipo") == "decision":
            accion = (r.get("decision") or {}).get("action")
            if accion in decisiones:
                decisiones[accion] += 1
        elif r.get("tipo") == "verificador_entrada" and (r.get("resultado") or {}).get("action") == "REJECT":
            rechazos += 1
        elif r.get("tipo") == "notificacion":
            avisos += 1
            alertas += r.get("prioridad") == "PRIORITARIA"
    return {"decisiones": decisiones, "rechazos_entrada": rechazos, "avisos": avisos, "alertas_prioritarias": alertas}


def verificacion_a_dict(cadena: AuditChain) -> dict[str, Any]:
    v = cadena.verify()
    return {
        "integra": v.ok,
        "entradas_verificadas": v.checked,
        "cabeza": {"seq": v.head[0], "hash": v.head[1]} if v.head else None,
        "roto_en": v.broken_at,
        "motivo": v.reason,
    }


# ---------------------------------------------------------------------------
# Bitácora de efectos (lo que realmente pasó en la base)
# ---------------------------------------------------------------------------
def efectos_de(run_id: str) -> list[dict[str, Any]]:
    conn = sqlite3.connect(db.init_evidencia(db.settings().ruta_evidencia))
    conn.row_factory = sqlite3.Row
    try:
        filas = conn.execute(
            "SELECT tool, efecto, objetivo, filas_afectadas FROM bitacora_efectos WHERE run_id = ? ORDER BY id",
            (run_id,),
        ).fetchall()
        return [dict(f) for f in filas]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Políticas (solo lectura)
# ---------------------------------------------------------------------------
def politicas(ruta: str | Path, policy: Any, sesion: Session) -> dict[str, Any]:
    """policies.yaml tal como está (solo lectura) y las herramientas que tiene el área de la sesión."""
    datos = yaml.safe_load(Path(ruta).read_text(encoding="utf-8")) or {}
    return {
        "archivo": Path(ruta).name,
        "version": datos.get("version"),
        "organizacion": datos.get("organizacion", {}),
        "verificador_entrada": datos.get("verificador_entrada", {}),
        "regla_entre_areas": datos.get("regla_entre_areas", {}),
        "areas": datos.get("areas", {}),
        "herramientas": datos.get("tools", {}),
        "mi_area": {
            "area": sesion.area,
            "nivel": sesion.nivel,
            "herramientas": list(policy.tools_for_area(sesion.area)),
            "aprueba_hitl": policy.top_level(sesion.area) == sesion.nivel,
        },
    }
