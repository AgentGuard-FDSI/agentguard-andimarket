"""Config B: el mismo agente con cada herramienta envuelta por AgentGuard.

Depende de que AgentGuard.authorize() este implementado (Avance 2).
"""

from agentguard import AgentGuard, Decision, Session

from agent.agent_loop import run_agent
from agent.models.mock import MockModel
from tools.tool_registry import TOOL_DEFINITIONS, execute_tool


def run_prompt(prompt: str, session: Session, model=None, guard: AgentGuard | None = None) -> str:
    guard = guard or AgentGuard.from_yaml("policies.yaml")

    def guarded_execute(name: str, tool_input: dict) -> str:
        verdict = guard.authorize(session, name, tool_input)
        if verdict.decision is Decision.ALLOW:
            return execute_tool(name, tool_input)
        if verdict.decision is Decision.BLOCK:
            return f"BLOQUEADO: {verdict.reason}"
        return f"PENDIENTE DE APROBACION: {verdict.reason}"

    return run_agent(prompt, model or MockModel(), guarded_execute, TOOL_DEFINITIONS)
