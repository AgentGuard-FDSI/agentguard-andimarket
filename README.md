# andimarket-agent

Agente de ANDIMARKET S.A.S. y experimento del proyecto AgentGuard: el mismo agente en dos
configuraciones.

- **Config. A** (`config_a.py`): el agente ejecuta cualquier herramienta que el modelo pida.
- **Config. B** (`config_b.py`): el mismo agente con cada herramienta envuelta por
  [AgentGuard](../AgentGuard), que decide ALLOW, BLOCK o HITL.

Todo es gratuito: SQLite, FastAPI y un modelo simulado, Gemini o Groq (cuotas gratuitas) u Ollama local.

## Estructura

```
agent/            bucle del agente y modelos intercambiables (agent/models/)
tools/            las seis herramientas simuladas y su registro
data/             carga del subconjunto de Olist a SQLite
scenarios/        escenarios, variantes y criterio de éxito
experiment/       runner, métricas y bitácora de efectos
api/              FastAPI para el frontend
config_a.py       agente sin AgentGuard (no importa agentguard)
config_b.py       agente con AgentGuard
policies.yaml     política de ANDIMARKET
tests/
```

## Estado

| Pieza | Fase |
|---|---|
| Bucle del agente, modelo simulado, registro de herramientas y Config. A con datos en memoria | Listo (provisional) |
| Herramientas sobre SQLite con Olist, `policies.yaml` base, modelos Gemini, Groq y Ollama | Avance 1 |
| `authorize()` conectado a `config_b.py` y primera comparación A frente a B | Avance 2 |
| Runner, escenarios 1 a 6, métricas e interfaz mínima | Avance 3 |

## Uso

```bash
pip install -r requirements.txt
python config_a.py        # ejecuta el prompt legítimo y el de inyección con el modelo simulado
python -m pytest
```

`tests/test_a_isolated.py` falla si `config_a.py`, `agent/` o `tools/` importan `agentguard`:
la Config. A debe seguir siendo un agente sin control.

Las claves de los modelos gratuitos van en `.env` (ver `.env.example`), nunca en el repositorio.
