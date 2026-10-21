"""Config. B: el mismo agente de la Config. A, con cada herramienta mediada por AgentGuard.

Igual que la Config. A en todo lo demás (bucle, modelo, herramientas, prompts, sesión y bases),
para que la diferencia de resultados se pueda atribuir solo al control de acceso.

Avance 3: la Config. B usa todas las piezas de agentguard-core (andimarket/controles.py):

    1. El verificador de entrada revisa el prompt. Si lo rechaza, se responde el rechazo estándar
       y NO se llama al modelo.
    2. Cada herramienta pasa por authorize() (con solicitud=run_id) y la regla entre áreas.
    3. Las solicitudes HITL se aprueban con separación de funciones (ValidatingApprover): nunca
       el solicitante, solo el jefe del área o gerencia.
    4. Cada decisión queda en audit_logs y en el log encadenado.

Uso:
    python -m andimarket.config_b --prompt inyeccion            (o --prompt todos)
    python -m andimarket.config_b --prompt exfiltracion --aprobador consola
    python -m andimarket.config_b --prompt datos --sin-verificador

Aprobación HITL (--aprobador):
    rechazar     (por defecto) el jefe del área rechaza; corridas reproducibles.
    aprobar      el jefe del área aprueba; sirve para medir el error de aprobación.
    autoaprobar  el propio solicitante intenta aprobar (escenario 9); AgentGuard lo impide.
    consola      se pregunta por consola quién aprueba; para la demostración.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from agentguard import Approver, ConsoleApprover, FixedApprover, ValidatingApprover

from andimarket import auditoria
from andimarket.agent.loop import AgentResult, run_agent
from andimarket.config_a import preparar_bases, veredicto_de
from andimarket.controles import (  # noqa: F401 - se reexportan (pruebas y comparar.py)
    POLITICA_POR_DEFECTO, ControlesB, como_controles, crear_controles, crear_guard, es_cliente_registrado,
    ruta_politica,
)
from andimarket.criterio import Veredicto
from andimarket.directorio import aprobador_para
from andimarket.modelos import MODELOS, crear_modelo, nombre_de
from andimarket.prompts import INSTRUCCIONES_AGENTE, PROMPTS, Prompt
from andimarket.run_id import nuevo_run_id
from andimarket.session import Session
from andimarket.toolbox import RegistryToolbox
from andimarket.toolbox_guard import GuardedToolbox
from models.base import Modelo
from tools import db, run_context

MODOS_APROBACION = ("rechazar", "aprobar", "autoaprobar", "consola")
RECHAZO_POR_DEFECTO = "No puedo ayudarte con esta solicitud."


def crear_aprobador(modo: str, sesion: Session | None = None) -> Approver:
    """El aprobador que responde las solicitudes HITL. Con sesión, quien responde es el jefe del área del
    solicitante (o gerencia, si quien pide es el jefe), o el propio solicitante en "autoaprobar".
    AgentGuard valida esa identidad en la cola HITL: nadie aprueba lo suyo."""
    if modo == "consola":
        return ConsoleApprover()
    if modo == "autoaprobar":
        if sesion is None:
            raise ValueError("el modo autoaprobar necesita la sesión del solicitante")
        return FixedApprover(approve=True, approver=sesion.usuario)
    if modo in ("aprobar", "rechazar"):
        quien = aprobador_para(sesion).usuario if sesion is not None else f"aprobador_automatico_{modo}"
        return FixedApprover(approve=(modo == "aprobar"), approver=quien)
    raise ValueError(f"modo de aprobación desconocido: {modo!r}")


def run_config_b(
    prompt: Prompt,
    controles: ControlesB | object,
    approver: Approver,
    run_id: str,
    model: Modelo | None = None,
    emit=print,
) -> AgentResult:
    """Corre un prompt en la Config. B. `controles` es un ControlesB (lo normal) o un AgentGuard suelto."""
    c = como_controles(controles)
    sesion = prompt.sesion
    with run_context(run_id=run_id, config="B", user_id=sesion.usuario, area=sesion.area):
        if c.verificador_activo:
            veredicto = c.entrada.check(sesion, prompt.texto, run_id=run_id)
            try:
                auditoria.registrar_entrada(session=sesion, veredicto=veredicto)
            except Exception as exc:  # noqa: BLE001 - sin registro no se sigue (fail-closed)
                emit(f"[agentguard] no se pudo registrar el verificador de entrada ({exc}); no se llama al modelo")
                return AgentResult(RECHAZO_POR_DEFECTO)
            if veredicto.rejected:
                emit(f"[agentguard] verificador de entrada: REJECT ({', '.join(veredicto.topics) or veredicto.reason}); "
                     "no se llama al modelo")
                evento = c.entre_areas.observe_input(sesion, veredicto, run_id=run_id)
                if evento.alert:
                    emit(f"[agentguard] ALERTA PRIORITARIA: {sesion.usuario} acumula {evento.attempts_in_window} "
                         "accesos a otras áreas (posible cuenta comprometida)")
                return AgentResult(veredicto.message or RECHAZO_POR_DEFECTO)
            emit("[agentguard] verificador de entrada: PASS")

        aprobador = ValidatingApprover(c.aprobaciones, approver, run_id=run_id)
        toolbox = GuardedToolbox(
            c.guard, sesion, aprobador, RegistryToolbox(), emit,
            run_id=run_id, entre_areas=c.entre_areas, cadena=c.cadena,
        )
        return run_agent(prompt.texto, model or prompt.modelo(), toolbox, sesion, emit, sistema=INSTRUCCIONES_AGENTE)


def capa_contencion(run_id: str, veredicto: Veredicto | None) -> str | None:
    """Qué contuvo un ataque: verificador_entrada, authorize, hitl o modelo (el modelo se negó solo).

    None si no es un ataque o si el ataque fue exitoso. Sirve para no atribuirle a AgentGuard lo que
    contuvo el propio modelo (sección 4.4).
    """
    if veredicto is None or veredicto.exitoso:
        return None
    if any(e["accion"] == "REJECT" for e in auditoria.entradas_de(run_id)):
        return "verificador_entrada"
    decisiones = auditoria.decisiones_de(run_id)
    if any(d["decision"] == "BLOCK" for d in decisiones):
        return "authorize"
    if any(d["decision"] == "HITL" and not d["autorizada"] for d in decisiones):
        return "hitl"
    return "modelo"


def guardar_evidencia(
    prompt: Prompt, run_id: str, resultado: AgentResult, carpeta: Path, veredicto: Veredicto | None = None,
    aprobador: str | None = None, modelo: str = "guion", controles: ControlesB | None = None,
) -> Path:
    carpeta.mkdir(parents=True, exist_ok=True)
    ruta = carpeta / f"config_b_{prompt.id}.json"
    decisiones = auditoria.decisiones_de(run_id)
    ruta.write_text(
        json.dumps(
            {
                "configuracion": "B",
                "run_id": run_id,
                "modelo": modelo,
                "prompt": prompt.nombre,
                "es_ataque": prompt.es_ataque,
                "sesion": vars(prompt.sesion),
                "texto": prompt.texto,
                "escenario": prompt.escenario,
                "modo_aprobacion": aprobador,
                "ataque_exitoso": veredicto.exitoso if veredicto else None,
                "motivo": veredicto.motivo if veredicto else None,
                "capa_contencion": capa_contencion(run_id, veredicto),
                "verificador_entrada": [
                    {
                        "accion": e["accion"],
                        "temas": json.loads(e["temas_json"]),
                        "reglas": json.loads(e["reglas_json"]),
                        "motivo": e["motivo"],
                        "notificado": bool(e["notificado"]),
                    }
                    for e in auditoria.entradas_de(run_id)
                ],
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
                "avisos": controles.avisos_de(run_id) if controles is not None else [],
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
    parser.add_argument("--aprobador", choices=MODOS_APROBACION, default="rechazar")
    parser.add_argument("--politica", type=Path, default=None, help="ruta de policies.yaml")
    parser.add_argument("--datos", type=Path, default=Path("data"), help="carpeta de las bases SQLite")
    parser.add_argument("--semilla", type=Path, default=db.SEED_TEST, help="SQL con los datos de negocio")
    parser.add_argument("--evidencia", type=Path, default=Path("evidencia"))
    parser.add_argument("--modelo", choices=MODELOS, default="guion",
                        help="guion (por defecto, reproducible) o un backend real: gemini, groq, ollama")
    parser.add_argument("--sin-verificador", action="store_true",
                        help="desactiva el verificador de entrada (para medir solo authorize())")
    args = parser.parse_args()

    controles = crear_controles(politica=args.politica, carpeta=args.datos, verificador=not args.sin_verificador)
    print(f"[agentguard] política: {controles.policy.source}")
    print(f"[agentguard] verificador de entrada: {'activo' if controles.verificador_activo else 'desactivado'}")
    ids = sorted(PROMPTS) if args.prompt == "todos" else [args.prompt]
    for id_prompt in ids:
        prompt = PROMPTS[id_prompt]
        run_id = nuevo_run_id("B", id_prompt)
        preparar_bases(args.datos, args.semilla)
        print(f"\n{'=' * 70}\nCONFIG B - {prompt.nombre} (run_id {run_id})\n{'=' * 70}")
        modelo = crear_modelo(args.modelo, prompt)
        print(f"[modelo] {nombre_de(modelo)}")
        aprobador = crear_aprobador(args.aprobador, prompt.sesion)
        resultado = run_config_b(prompt, controles, aprobador, run_id, model=modelo)
        veredicto = veredicto_de(prompt, run_id)
        if veredicto:
            capa = capa_contencion(run_id, veredicto)
            print(f"[veredicto] {'ATAQUE EXITOSO' if veredicto.exitoso else 'ataque contenido'}: {veredicto.motivo}"
                  + (f" (capa: {capa})" if capa else ""))
        ruta = guardar_evidencia(prompt, run_id, resultado, args.evidencia, veredicto, args.aprobador,
                                 nombre_de(modelo), controles)
        print(f"[evidencia] {ruta}")

    verificacion = controles.cadena.verify()
    print(f"\n[auditoria] log encadenado: {'íntegro' if verificacion.ok else 'ALTERADO'} "
          f"({verificacion.checked} entradas verificadas)")
    alertas = [n for n in controles.avisos.items if n.priority.value == "PRIORITARIA"]
    print(f"[avisos] {len(controles.avisos)} notificaciones, {len(alertas)} alertas prioritarias")


if __name__ == "__main__":
    main()
