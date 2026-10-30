# API de ANDIMARKET

FastAPI que sirve a la interfaz web. Se arranca con:

```bash
python -m andimarket.api
```

FastAPI también publica la documentación interactiva en `/docs`. Todas las rutas cuelgan de `/api`.

## Sesión

| Método y ruta | Qué hace |
|---|---|
| `GET /api/salud` | Comprueba que la API esté corriendo. |
| `POST /api/login` | Inicia sesión con un usuario del directorio de demostración y devuelve un token. |
| `POST /api/logout` | Cierra la sesión. |
| `GET /api/me` | Devuelve usuario, área y nivel de la sesión actual. |

## Asistente (Config. B)

| Método y ruta | Qué hace |
|---|---|
| `GET /api/prompts` | Ejemplos de prompts para la sesión. |
| `POST /api/chat` | Inicia una ejecución del agente. Responde `202` con el id de la ejecución. |
| `GET /api/chat/historial` | Historial de conversaciones de la sesión. |
| `GET /api/ejecuciones/{ejecucion_id}` | Estado de una ejecución. Con `?desde=N` devuelve solo los eventos nuevos. |

El chat usa polling: la interfaz pide `GET /api/ejecuciones/{id}?desde=N` cada segundo hasta que la ejecución
termina. Si una acción requiere aprobación, la ejecución queda esperando.

## Aprobaciones

| Método y ruta | Qué hace |
|---|---|
| `GET /api/aprobaciones` | Lista por aprobar (solo jefes y Gerencia), mis solicitudes e historial. |
| `POST /api/aprobaciones/{solicitud_id}` | Aprueba o rechaza una solicitud. El núcleo rechaza la autoaprobación y a quien no corresponde. |

## Seguridad

| Método y ruta | Qué hace |
|---|---|
| `GET /api/seguridad/resumen` | Conteo de decisiones. |
| `GET /api/seguridad/registro` | Registro de auditoría con hash. |
| `GET /api/seguridad/alertas` | Alertas de la regla entre áreas. |
| `GET /api/seguridad/verificar` | Verifica la integridad de la cadena de auditoría. |

Cada persona ve lo suyo y los avisos dirigidos a su área.

## Políticas

| Método y ruta | Qué hace |
|---|---|
| `GET /api/politicas` | `policies.yaml` en solo lectura. |

## Comparación A/B

| Método y ruta | Qué hace |
|---|---|
| `POST /api/comparacion` | Corre un escenario en Config. A y en Config. B. Responde `202`. |
| `POST /api/comparacion/experimento` | Corre el experimento completo. Responde `202`. |
| `GET /api/comparacion/resultados` | Resultados guardados en `evidencia/`. |

Un experimento corrido con un modelo remoto consume cuota. Revisa el costo antes de lanzarlo.

## Demostración

| Método y ruta | Qué hace |
|---|---|
| `POST /api/demo/reiniciar` | Reinicia los datos de la demostración. |

Esta lista sale de las rutas definidas en `andimarket/api/app.py`. Si agregas o cambias una ruta, actualiza
este documento.
