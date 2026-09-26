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

## Puesta en marcha

### Requisitos

Python 3.10 o superior. En Windows, instálalo desde https://www.python.org/downloads/ marcando
la casilla "Add Python to PATH"; verifica con `py --version`.

### Instalación

**Windows (cmd o PowerShell):**

    py -m venv .venv
    .venv\Scripts\activate
    pip install -r requirements.txt -r requirements-dev.txt

**Linux / macOS:**

    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt -r requirements-dev.txt

### Generar la base de datos

    python scripts/cargar_olist.py

Crea `data/andimarket_base.db` (sintética, 150 pedidos + los 5 de demostración: 123 a 127). No se
sube a git.

Para probar el agente con el modelo simulado, En **Windows** ejecutar:

    python demo.py

De lo contrario, ejecutar el bloque en la terminar Unix.

### Pruebas

    pytest

## Config. A (Avance 1, Persona 1)

- `andimarket/agent/loop.py`: bucle del agente (sin validación). `andimarket/models/`: interfaz de modelo y
  `ScriptedModel` (determinista, sin red). Los modelos reales se adaptan a `ModelClient`.
- `andimarket/toolbox.py`: adaptador del paquete `tools` (`execute_tool`, `TOOL_DEFINITIONS`) al bucle.
- `andimarket/prompts.py`: una solicitud legítima y dos ataques (inyección directa y escalada de privilegios).
- `andimarket/config_a.py`: la Config. A (no importa `agentguard`). Fija el contexto de la corrida
  (`run_context` con config A, usuario y área) para que la bitácora de efectos lo registre.
- `evidencia/`: JSON de las corridas de la Config. A con los datos de prueba (`db/seed_test.sql`).

```bash
python -m pytest
python -m andimarket.config_a --prompt todos
```

## Estado

Repositorio inicializado. El trabajo se reparte por avances: herramientas, datos y Config. A en el
Avance 1; conexión con `agentguard-core` y primera comparación en el Avance 2; escenarios, runner y
métricas en el Avance 3.

Las claves de los modelos gratuitos van en variables de entorno o en un `.env` que no se versiona.
