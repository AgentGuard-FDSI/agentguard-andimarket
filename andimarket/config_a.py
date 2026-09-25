"""Config. A: el agente ejecuta cualquier herramienta que el modelo pida, sin ningún control.

Este módulo no debe importar `agentguard`: es la línea base contra la que se compara la Config. B.

Uso:  python -m andimarket.config_a --prompt inyeccion
"""

import argparse
import json
from pathlib import Path

from andimarket.agent.loop import AgentResult, Toolbox, run_agent
from andimarket.models.base import ModelClient
from andimarket.prompts import PROMPTS, Prompt


def run_config_a(prompt: Prompt, toolbox: Toolbox, model: ModelClient | None = None, emit=print) -> AgentResult:
    return run_agent(prompt.texto, model or prompt.modelo(), toolbox, prompt.sesion, emit)


def guardar_evidencia(prompt: Prompt, resultado: AgentResult, carpeta: Path) -> Path:
    carpeta.mkdir(parents=True, exist_ok=True)
    ruta = carpeta / f"config_a_{prompt.id}.json"
    ruta.write_text(
        json.dumps(
            {
                "configuracion": "A",
                "prompt": prompt.nombre,
                "es_ataque": prompt.es_ataque,
                "sesion": vars(prompt.sesion),
                "texto": prompt.texto,
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Ejecuta un prompt en la Config. A (sin control).")
    parser.add_argument("--prompt", choices=sorted(PROMPTS), required=True)
    parser.add_argument("--evidencia", type=Path, default=Path("evidencia"))
    args = parser.parse_args()

    try:
        from andimarket.tools import Tools  # las herramientas simuladas (tools.py) las construye otro frente
    except ImportError:
        raise SystemExit("Falta andimarket/tools.py (las seis herramientas simuladas sobre SQLite).")

    prompt = PROMPTS[args.prompt]
    print(f"CONFIG A - {prompt.nombre}")
    resultado = run_config_a(prompt, Tools())
    print(f"\n[evidencia] {guardar_evidencia(prompt, resultado, args.evidencia)}")


if __name__ == "__main__":
    main()
