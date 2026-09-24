"""Bucle del agente: instruccion -> modelo -> herramienta -> resultado -> respuesta.

El modelo y la funcion que ejecuta las herramientas se inyectan: Config A pasa
execute_tool directamente y Config B pasa una version envuelta por AgentGuard.
"""

MAX_ITERATIONS = 8


def run_agent(instruction, model, execute_tool, tools, max_iterations=MAX_ITERATIONS) -> str:
    print(f"[agent] Instruccion recibida: {instruction!r}")
    messages = [{"role": "user", "content": instruction}]

    final_text = ""
    for iteration in range(1, max_iterations + 1):
        print(f"[agent] --- iteracion {iteration} ---")
        stop_reason, content = model.complete(messages, tools)

        for block in content:
            if block["type"] == "text" and block.get("text"):
                print(f"[agent] modelo dice: {block['text']}")

        messages.append({"role": "assistant", "content": content})

        if stop_reason != "tool_use":
            final_text = "\n".join(b["text"] for b in content if b["type"] == "text")
            print("[agent] respuesta final del modelo, fin del loop")
            break

        tool_results = []
        for block in content:
            if block["type"] != "tool_use":
                continue
            name, tool_input = block["name"], block["input"]
            print(f"[agent] el modelo solicito la herramienta '{name}' con argumentos {tool_input}")
            result = execute_tool(name, tool_input)
            print(f"[agent] resultado de '{name}': {result!r}")
            tool_results.append(
                {"type": "tool_result", "tool_use_id": block["id"], "content": str(result)}
            )

        messages.append({"role": "user", "content": tool_results})
    else:
        print("[agent] se alcanzo el limite de iteraciones sin respuesta final")

    return final_text
