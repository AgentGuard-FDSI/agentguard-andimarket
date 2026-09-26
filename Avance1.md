# AgentGuard — Avance 1: problema y arquitectura

Seminario de Seguridad de la Información, Escuela Colombiana de Ingeniería Julio Garavito.
Tema: autonomía excesiva en agentes.

## 1. Problema

Los agentes basados en modelos de lenguaje ya no solo generan texto: actúan sobre sistemas reales mediante herramientas:

- Connsultan bases de datos
- Modifican registros
- Envían correos
- Ejecutan comandos. 

La práctica habitual es entregarles todas las herramientas disponibles con permisos amplios, suponiendo que el modelo sabrá cuándo y cómo usar cada una. Ese supuesto falla en dos situaciones:

- Cuando el modelo se equivoca 
- Cuando un tercero lo manipula mediante inyección de instrucciones, ya sea directamente en el prompt o de forma indirecta, escondida en contenido que el agente lee (un comentario, un correo reenviado, un adjunto).

El problema no es que el modelo tome decisiones incorrectas, sino que no existe una barrera que contenga el impacto antes de que la acción se ejecute. 

Una sola acción no autorizada puede ser irreversible y, a diferencia de un error humano, un agente puede repetirla a gran velocidad. OWASP clasifica esta situación como 

`
LLM06:2025, *Excessive Agency*
`

Y la descompone en:

- Exceso de funcionalidad
- Exceso de permisos
- Exceso de autonomía. 

En términos de seguridad de la información, se invierte la lógica tradicional: normalmente se limita lo que un sistema puede hacer antes de darle autonomía; con los agentes se entrega la autonomía primero y los límites se piensan después.

Para que el problema sea concreto, el proyecto se ancla en ANDIMARKET S.A.S., un marketplace colombiano ficticio que implementó un asistente interno usado por Atención al cliente, Logística, Marketing, Tecnología y Finanzas. 

El asistente tiene acceso directo a seis herramientas 

- `consultar_pedido`
- `actualizar_pedido`
- `eliminar_pedido`
- `enviar_correo`
- `leer_base_datos`
- `admin_action`

Con los mismos permisos sin importar quién lo invoque, y procesa contenido de terceros. Los datos expuestos incluyen información personal de clientes, historial de pedidos, pagos y configuración interna, todos simulados o anonimizados.

## 2. Pregunta y diseño experimental

**¿Cuánto reduce un control de acceso de mínimo privilegio, aplicado por herramienta, argumento, área y nivel jerárquico, la ejecución de acciones no autorizadas por un agente LLM, y con qué costo en fricción para las solicitudes legítimas?**

Se compara el mismo agente en dos configuraciones, con el mismo modelo, las mismas herramientas, los mismos prompts y la misma temperatura: 

La Configuración A ejecuta directamente cualquier herramienta que el modelo pida, y la Configuración B pasa cada llamada por AgentGuard, que decide ALLOW, BLOCK o HITL (aprobación humana). 

Así, la diferencia de resultados se puede atribuir al control de acceso y no a otra variable. El éxito o fracaso de cada intento se determina con una bitácora de efectos que cada herramienta escribe en SQLite, independiente de lo que el modelo diga en su respuesta.

## 3. Arquitectura

### 3.1 Decisión: interceptor embebido

Se evaluaron dos arquitecturas. 

- La primera, elegida, implementa AgentGuard como un módulo de Python que corre en el mismo proceso que el agente: antes de ejecutar cualquier herramienta, el agente llama a `AgentGuard.authorize(session, tool, arguments)`, que devuelve la decisión. 

- La segunda, descartada por ahora, lo implementa como un servicio HTTP independiente al que el agente consulta por red.

El criterio decisivo fue que el valor del experimento depende solo de que la llamada a la herramienta pase o no por la política, no de que AgentGuard sea un servicio aparte. La opción de servicio independiente tiene un mejor argumento de producto ("protege cualquier agente sin tocar su código"), pero agrega superficie de fallo en la demostración en vivo (varios procesos, red, comunicación entre servicios) sin aportar evidencia adicional. Aun así, AgentGuard se mantiene como componente separable: vive en su propio repositorio con una interfaz estable, y pasar a la segunda opción significaría envolver esa misma interfaz en un endpoint, no reescribirla.

### 3.2 Componentes y repositorios

El código se organiza en repositorios de la organización AgentGuard-FDSI. 

- `agentguard-core` contiene el producto: el lector de `policies.yaml` y, en los siguientes avances, el motor de decisiones, el verificador de entrada, la regla de acceso entre áreas, las aprobaciones y el registro de auditoría. 

- `agentguard-andimarket` contiene todo lo que pertenece al caso de estudio: las herramientas simuladas, los datos, la interfaz de modelo, el agente y el experimento. 

Esta separación garantiza que la Configuración A sea un agente sin ningún control (no importa `agentguard`, y una prueba automática lo verifica) y que la Configuración B sea el mismo agente con AgentGuard instalado como paquete.

El flujo de una acción en la Configuración B es: el usuario, autenticado con un área y un nivel que vienen de la sesión y nunca del prompt, envía una instrucción; el verificador de entrada la examina con reglas; si pasa, el agente consulta al modelo, que elige una herramienta y sus argumentos; antes de ejecutarla, `authorize()` evalúa la política y decide ejecutarla, bloquearla o dejarla pendiente de aprobación por una persona distinta del solicitante. Toda decisión queda en el registro de auditoría. En la Configuración A el paso de autorización no existe.

### 3.3 Interfaz de modelo intercambiable

El agente no llama directamente a ningún proveedor. Llama a un objeto con una interfaz única, `generar(historial, definiciones_de_herramientas)`, que devuelve o un texto final o una o más llamadas a herramienta. 

Detrás de esa interfaz hay cuatro implementaciones: 

- Un modelo simulado determinista, sin red ni llaves, para iterar y para la demostración en vivo; 
- Gemini (cuota gratuita de Google AI Studio); 
- Groq (cuota gratuita); 
- Ollama, que ejecuta un modelo local. 

El backend se elige con la variable `MODEL_BACKEND` y el modelo se fija y se reporta por corrida; si se cambia de proveedor, el experimento completo se repite con el mismo modelo en A y en B. Las llaves se leen de variables de entorno o de un archivo `.env` local excluido del repositorio. La temperatura se fija por configuración (`MODEL_TEMPERATURE`, 0 por defecto) y los backends remotos reintentan con espera creciente ante límites de tasa, para respetar las cuotas gratuitas.

### 3.4 Datos

El esquema de ANDIMARKET tiene cuatro tablas de negocio (clientes, pedidos, pagos y configuración de TI) y una base de evidencia aparte con el buzón de correo simulado y la bitácora de efectos, que no se reinicia entre corridas. 

Antes de cada corrida, la base de trabajo se restaura desde una base limpia para que A y B partan del mismo estado.

La base limpia se construye a partir del Brazilian E-Commerce Public Dataset de Olist (Kaggle, licencia CC BY-NC-SA 4.0): se toma un subconjunto de 50 a 200 pedidos con sus clientes y pagos, el valor de cada pedido se calcula como la suma del precio y el flete de sus ítems, los 27 estados de Brasil se renombran a departamentos colombianos y su capital, y los nombres, correos (dominio reservado `example.test`) y teléfonos se generan de forma sintética porque Olist los anonimiza. El estado del pago, que Olist no trae, se deriva del estado del pedido. Mientras el equipo descarga el dataset, el mismo script genera un conjunto sintético con idéntica forma y reglas, reproducible con una semilla fija; ambos incluyen cinco pedidos de demostración con identificadores cortos (123 a 127) usados en los escenarios de prueba.