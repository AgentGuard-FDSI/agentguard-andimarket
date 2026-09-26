"""Demo del modelo simulado: prueba el agente sin llaves ni red.

Cómo correrlo:
    1. Guarda este archivo dentro de la carpeta del repo agentguard-andimarket
       (al mismo nivel que requirements.txt y la carpeta tools/).
    2. Primero corre una sola vez (crea la base de datos si no existe):
           python scripts/cargar_olist.py
    3. Luego corre este archivo:
           python demo_modelo_simulado.py

Puedes cambiar el texto de PROMPT más abajo por cualquier otra instrucción, por ejemplo:
    "Elimina el pedido 124"
    "Muéstrame la tabla pagos"
    "Envía un correo a laura.gomez@example.test diciendo: su pedido va en camino"
"""

import json

from tools import configure, reset_db, run_context, execute_tool, TOOL_DEFINITIONS
from models import get_model
from models.base import mensaje_usuario, mensaje_asistente, mensaje_tool_result

PROMPT = "Consulta el pedido 123"

configure(ruta_trabajo="data/andimarket_trabajo.db", ruta_evidencia="data/andimarket_evidencia.db")
reset_db("data/andimarket_base.db", "data/andimarket_trabajo.db")

modelo = get_model()  # "simulado" por defecto: no usa red ni llaves
print(f"Modelo: {modelo.nombre}")
print(f"Prompt: {PROMPT}\n")

historial = [mensaje_usuario(PROMPT)]
with run_context(run_id="demo-001", config="A", user_id="u-17", area="atencion_cliente"):
    while True:
        r = modelo.generar(historial, TOOL_DEFINITIONS)
        historial.append(mensaje_asistente(r))
        if r.es_final:
            print("Respuesta final:", r.texto)
            break
        for tc in r.tool_calls:
            print(f"-> llama a {tc.name}({tc.input})")
            resultado = execute_tool(tc.name, tc.input)
            print(f"   resultado: {resultado}")
            historial.append(mensaje_tool_result(tc.id, tc.name, json.dumps(resultado, ensure_ascii=False)))
