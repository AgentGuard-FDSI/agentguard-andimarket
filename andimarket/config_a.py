"""Config. A: el agente ejecuta cualquier herramienta que el modelo pida, sin ningún control.

Este módulo no debe importar `agentguard`: es la línea base contra la que se compara la Config. B.

Uso:  python -m andimarket.config_a --prompt inyeccion     (o --prompt todos)

Cada corrida parte de una base de trabajo limpia (reset_db) y deja su rastro en la base de evidencia,
filtrable por run_id, además de un JSON con lo que el agente ejecutó en `evidencia/`.
"""

import argparse
import json
from pathlib import Path

from andimarket.agent.loop import AgentResult, Toolbox, run_agent
from andimarket.criterio import Veredicto, evaluar
from andimarket.prompts import PROMPTS, Prompt
from andimarket.run_id import nuevo_run_id
from andimarket.toolbox import RegistryToolbox
from models.base import Modelo
from tools import db, run_context


def run_config_a(
    prompt: Prompt,
    toolbox: Toolbox,
    run_id: str,
    model: Modelo | None = None,
    emit=print,
) -> AgentResult:
    sesion = prompt.sesion
    with run_context(run_id=run_id, config="A", user_id=sesion.usuario, area=sesion.area):
        return run_agent(prompt.texto, model or prompt.modelo(), toolbox, sesion, emit)


def veredicto_de(prompt: Prompt, run_id: str) -> Veredicto | None:
    """Criterio de éxito automático sobre la bitácora; solo aplica a los ataques."""
    return evaluar(prompt.escenario, run_id) if prompt.es_ataque and prompt.escenario else None


def guardar_evidencia(
    prompt: Prompt, run_id: str, resultado: AgentResult, carpeta: Path, veredicto: Veredicto | None = None
) -> Path:
    carpeta.mkdir(parents=True, exist_ok=True)
    ruta = carpeta / f"config_a_{prompt.id}.json"
    ruta.write_text(
        json.dumps(
            {
                "configuracion": "A",
                "run_id": run_id,
                "prompt": prompt.nombre,
                "es_ataque": prompt.es_ataque,
                "sesion": vars(prompt.sesion),
                "texto": prompt.texto,
                "escenario": prompt.escenario,
                "ataque_exitoso": veredicto.exitoso if veredicto else None,
                "motivo": veredicto.motivo if veredicto else None,
                "herramientas_ejecutadas": [
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


def preparar_bases(carpeta: Path, semilla: Path) -> None:
    """Base limpia (si falta), base de trabajo restaurada y base de evidencia (que no se reinicia)."""
    base = carpeta / "andimarket_base.db"
    if not base.exists():
        db.init_db(base, seed=semilla)
    trabajo = db.reset_db(base, carpeta / "andimarket_trabajo.db")
    evidencia = db.init_evidencia(carpeta / "andimarket_evidencia.db")
    db.configure(ruta_trabajo=trabajo, ruta_evidencia=evidencia)


def main() -> None:
    parser = argparse.ArgumentParser(description="Ejecuta prompts en la Config. A (sin control).")
    parser.add_argument("--prompt", choices=sorted(PROMPTS) + ["todos"], required=True)
    parser.add_argument("--datos", type=Path, default=Path("data"), help="carpeta de las bases SQLite")
    parser.add_argument("--semilla", type=Path, default=db.SEED_TEST, help="SQL con los datos de negocio")
    parser.add_argument("--evidencia", type=Path, default=Path("evidencia"))
    args = parser.parse_args()

    ids = sorted(PROMPTS) if args.prompt == "todos" else [args.prompt]
    for id_prompt in ids:
        prompt = PROMPTS[id_prompt]
        run_id = nuevo_run_id("A", id_prompt)
        preparar_bases(args.datos, args.semilla)
        print(f"\n{'=' * 70}\nCONFIG A - {prompt.nombre} (run_id {run_id})\n{'=' * 70}")
        resultado = run_config_a(prompt, RegistryToolbox(), run_id)
        veredicto = veredicto_de(prompt, run_id)
        if veredicto:
            print(f"[veredicto] {'ATAQUE EXITOSO' if veredicto.exitoso else 'ataque contenido'}: {veredicto.motivo}")
        print(f"[evidencia] {guardar_evidencia(prompt, run_id, resultado, args.evidencia, veredicto)}")


if __name__ == "__main__":
    main()
