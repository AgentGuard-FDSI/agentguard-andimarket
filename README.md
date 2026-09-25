# agentguard-andimarket

El agente de ANDIMARKET S.A.S. (empresa ficticia de comercio electrónico) y el experimento del
proyecto AgentGuard: el mismo agente en dos configuraciones.

- **Config. A:** el agente ejecuta cualquier herramienta que el modelo pida.
- **Config. B:** el mismo agente con cada herramienta envuelta por
  [`agentguard-core`](https://github.com/AgentGuard-FDSI/agentguard-core), que decide ALLOW, BLOCK o HITL.

Todo es gratuito: SQLite, FastAPI y un modelo simulado, Gemini o Groq (cuotas gratuitas) u Ollama local.

## Qué va en este repositorio

- Bucle del agente y modelos intercambiables (simulado, Gemini, Groq, Ollama).
- Las seis herramientas simuladas: `consultar_pedido`, `actualizar_pedido`, `eliminar_pedido`,
  `enviar_correo`, `leer_base_datos` y `admin_action`.
- Datos: subconjunto del dataset de Olist cargado a SQLite.
- Autenticación de demostración: usuarios con área y nivel.
- Escenarios de ataque, criterio de éxito y experimento (runner y métricas).
- API FastAPI para el frontend.
- `config_a.py` y `config_b.py`. La Config. A no debe importar `agentguard`.

## Config. A (Avance 1, Persona 1)

- `andimarket/agent/loop.py`: bucle del agente (sin validación). `andimarket/models/`: interfaz de modelo y
  `ScriptedModel` (determinista, sin red). Los modelos reales se adaptan a `ModelClient`.
- `andimarket/prompts.py`: una solicitud legítima y dos ataques (inyección directa y escalada de privilegios).
- `andimarket/config_a.py`: la Config. A (no importa `agentguard`); guarda la evidencia en `evidencia/`.
- Necesita `andimarket/tools.py` con una clase `Tools` (`definitions()` y `execute(name, arguments)`) y las
  firmas `consultar_pedido(order_id)`, `eliminar_pedido(order_id)` y `admin_action(accion)`.

```bash
python -m pytest
python -m andimarket.config_a --prompt inyeccion
```

## Estado

Repositorio inicializado. El trabajo se reparte por avances: herramientas, datos y Config. A en el
Avance 1; conexión con `agentguard-core` y primera comparación en el Avance 2; escenarios, runner y
métricas en el Avance 3.

Las claves de los modelos gratuitos van en variables de entorno o en un `.env` que no se versiona.
