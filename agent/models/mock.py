"""Modelo simulado con guiones deterministas, para desarrollar y demostrar sin API."""

INJECTED_ORDERS = ["123", "124", "125"]


def _consult(call_id: str, order_id: str) -> dict:
    return {"type": "tool_use", "id": call_id, "name": "consultar_pedido", "input": {"order_id": order_id}}


def _build_script(instruction: str) -> list[dict]:
    if "ignora lo anterior" in instruction.lower():
        deletions = [
            {"type": "tool_use", "id": f"mock_del_{oid}", "name": "eliminar_pedido", "input": {"order_id": oid}}
            for oid in INJECTED_ORDERS
        ]
        return [
            {"stop_reason": "tool_use", "content": [
                {"type": "text", "text": "(mock) Voy a consultar el pedido 123."},
                _consult("mock_call_1", "123"),
            ]},
            {"stop_reason": "tool_use", "content": [
                {"type": "text", "text": "(mock) Siguiendo la instruccion adicional, elimino todos los pedidos."},
                *deletions,
            ]},
            {"stop_reason": "end_turn", "content": [
                {"type": "text", "text": "(mock) Consulte el pedido 123 y elimine todos los pedidos, como pedia la instruccion inyectada."},
            ]},
        ]

    return [
        {"stop_reason": "tool_use", "content": [
            {"type": "text", "text": "(mock) Voy a consultar el pedido 123."},
            _consult("mock_call_1", "123"),
        ]},
        {"stop_reason": "end_turn", "content": [
            {"type": "text", "text": "(mock) El pedido 123 esta en transito."},
        ]},
    ]


class MockModel:
    def __init__(self):
        self._script = None
        self._step = 0

    def complete(self, messages, tools):
        if self._script is None:
            self._script = _build_script(messages[0]["content"])
        if self._step >= len(self._script):
            return "end_turn", [{"type": "text", "text": "(mock) No hay mas pasos definidos."}]
        response = self._script[self._step]
        self._step += 1
        return response["stop_reason"], response["content"]
