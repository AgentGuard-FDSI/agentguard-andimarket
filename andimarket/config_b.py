"""Config. B: el mismo agente de la Config. A, con cada herramienta mediada por AgentGuard.

Igual que la Config. A en todo lo demás (bucle, modelo, herramientas, prompts, sesión y bases),
para que la diferencia de resultados se pueda atribuir solo al control de acceso.

Uso:
    python -m andimarket.config_b --prompt inyeccion            (o --prompt todos)
    python -m andimarket.config_b --prompt exfiltracion --aprobador consola

La política se lee de policies.yaml del repositorio agentguard-core, clonado junto a este
(../agentguard-core/config/policies.yaml), o de la ruta en --politica o AGENTGUARD_POLICY.

Aprobación HITL (--aprobador):
    rechazar  (por defecto) ninguna acción HITL se aprueba; corridas reproducibles.
    aprobar   toda acción HITL se aprueba; sirve para medir el error de aprobación.
    consola   se pregunta por consola; para la demostración.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from pathlib import Path

from agentguard import AgentGuard, Approver, ConsoleApprover, FixedApprover

from andimarket import auditoria
from andimarket.agent.loop import AgentResult, run_agent
from andimarket.config_a import preparar_bases, veredicto_de
from andimarket.criterio import Veredicto
from andimarket.prompts import PROMPTS, Prompt
from andimarket.run_id import nuevo_run_id
from andimarket.toolbox import RegistryToolbox
from andimarket.toolbox_guard import GuardedToolbox
from models.base import Modelo
from tools import db, run_context

POLITICA_POR_DEFECTO = Path(__file__).resolve().parents[2] / "agentguard-core" / "config" / "policies.yaml"


def ruta_politica(explicita: str | Path | None = None) -> Path:
    """--politica, luego AGENTGUARD_POLICY, luego el repositorio agentguard-core vecino."""
    return Path(explicita or os.environ.get("AGENTGUARD_POLICY") or POLITICA_POR_DEFECTO)


def es_cliente_registrado(correo: str) -> bool:
    """True si el correo pertenece a un cliente de la base de trabajo (lo usa AgentGuard en el Avance 3)."""
    conn = sqlite3.connect(db.settings().ruta_trabajo)
    try:
        fila = conn.execute(
            "SELECT 1 FROM clientes WHERE lower(correo) = lower(?) LIMIT 1", (str(correo).strip(),)
        ).fetchone()
        return fila is not None
    finally:
        conn.close()


def crear_guard(politica: str | Path | None = None) -> AgentGuard:
    """Carga la política una sola vez (fail-closed: PolicyError si es inválida o no existe)."""
    return AgentGuard.from_file(ruta_politica(politica), es_cliente=es_cliente_registrado)


def crear_aprobador(modo: str) -> Approver:
    if modo == "consola":
        return ConsoleApprover()
    if modo in ("aprobar", "rechazar"):
        return FixedApprover(approve=(modo == "aprobar"), approver=f"aprobador_automatico_{modo}")
    raise ValueError(f"modo de aprobación desconocido: {modo!r}")


def run_config_b(
    prompt: Prompt,
    guard: AgentGuard,
    approver: Approver,
    run_id: str,
    model: Modelo | None = None,
    emit=print,
) -> AgentResult:
    sesion = prompt.sesion
    toolbox = GuardedToolbox(guard, sesion, approver, RegistryToolbox(), emit)
    with run_context(run_id=run_id, config="B", user_id=sesion.usuario, area=sesion.area):
        return run_agent(prompt.texto, model or prompt.modelo(), toolbox, sesion, emit)


def guardar_evidencia(
    prompt: Prompt, run_id: str, resultado: AgentResult, carpeta: Path, veredicto: Veredicto | None = None,
    aprobador: str | None = None,
) -> Path:
    carpeta.mkdir(parents=True, exist_ok=True)
    ruta = carpeta / f"config_b_{prompt.id}.json"
    decisiones = auditoria.decisiones_de(run_id)
    ruta.write_text(
        json.dumps(
            {
                "configuracion": "B",
                "run_id": run_id,
                "prompt": prompt.nombre,
                "es_ataque": prompt.es_ataque,
                "sesion": vars(prompt.sesion),
                "texto": prompt.texto,
                "escenario": prompt.escenario,
                "modo_aprobacion": aprobador,
                "ataque_exitoso": veredicto.exitoso if veredicto else None,
                "motivo": veredicto.motivo if veredicto else None,
                "decisiones_agentguard": [
                    {
                        "herramienta": d["tool"],
                        "argumentos": json.loads(d["args_json"]),
                        "decision": d["decision"],
                        "regla": d["regla"],
                        "motivo": d["motivo"],
                        "aprobado": None if d["aprobado"] is None else bool(d["aprobado"]),
                        "aprobador": d["aprobador"],
                        "autorizada": bool(d["autorizada"]),
                    }
                    for d in decisiones
                ],
                "herramientas_solicitadas": [
                    {"herramienta": r.name, "argumentos": r.arguments, "resultado": r.result}
                    for r in resultado.trace
                ],
                "respuesta_final": resultado.final_text,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return ruta


def main() -> None:
    parser = argparse.ArgumentParser(description="Ejecuta prompts en la Config. B (con AgentGuard).")
    parser.add_argument("--prompt", choices=sorted(PROMPTS) + ["todos"], required=True)
    parser.add_argument("--aprobador", choices=["rechazar", "aprobar", "consola"], default="rechazar")
    parser.add_argument("--politica", type=Path, default=None, help="ruta de policies.yaml")
    parser.add_argument("--datos", type=Path, default=Path("data"), help="carpeta de las bases SQLite")
    parser.add_argument("--semilla", type=Path, default=db.SEED_TEST, help="SQL con los datos de negocio")
    parser.add_argument("--evidencia", type=Path, default=Path("evidencia"))
    args = parser.parse_args()

    guard = crear_guard(args.politica)
    print(f"[agentguard] política: {guard.policy.source}")
    ids = sorted(PROMPTS) if args.prompt == "todos" else [args.prompt]
    for id_prompt in ids:
        prompt = PROMPTS[id_prompt]
        run_id = nuevo_run_id("B", id_prompt)
        preparar_bases(args.datos, args.semilla)
        print(f"\n{'=' * 70}\nCONFIG B - {prompt.nombre} (run_id {run_id})\n{'=' * 70}")
        resultado = run_config_b(prompt, guard, crear_aprobador(args.aprobador), run_id)
        veredicto = veredicto_de(prompt, run_id)
        if veredicto:
            print(f"[veredicto] {'ATAQUE EXITOSO' if veredicto.exitoso else 'ataque contenido'}: {veredicto.motivo}")
        ruta = guardar_evidencia(prompt, run_id, resultado, args.evidencia, veredicto, args.aprobador)
        print(f"[evidencia] {ruta}")


if __name__ == "__main__":
    main()
