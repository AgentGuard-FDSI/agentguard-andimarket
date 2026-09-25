"""Caja de herramientas de prueba: registra las llamadas y devuelve resultados fijos, sin SQLite."""

CLIENTES = "ana@correo.test\nluis@correo.test\nsofia@correo.test"


class FakeToolbox:
    def __init__(self, resultados: dict[str, str] | None = None):
        self.llamadas: list[tuple[str, dict]] = []
        self._resultados = {
            "consultar_pedido": "pedido 123: en camino",
            "eliminar_pedido": "OK: pedido eliminado",
            "admin_action": "OK: acción ejecutada",
            "enviar_correo": "OK: correo enviado",
            "leer_base_datos": CLIENTES,
        }
        self._resultados.update(resultados or {})

    def definitions(self) -> list[dict]:
        return [{"name": nombre} for nombre in self._resultados]

    def execute(self, name: str, arguments: dict) -> str:
        self.llamadas.append((name, arguments))
        return self._resultados.get(name, f"ERROR: herramienta desconocida '{name}'")
