"""Modelo simulado: determinista, sin red y sin llaves (sección 4 de la propuesta).

Sirve para iterar y para la demostración en vivo con resultados reproducibles. No "razona":
reconoce en el último mensaje del usuario una intención con reglas fijas y pide la
herramienta correspondiente, tomando literalmente los datos del texto (id de pedido, estado,
tabla, destinatario, comando). Cuando recibe el resultado de la herramienta, responde con un
texto final que lo resume.

Mismo historial -> misma respuesta, siempre.

Intenciones reconocidas (en español, sin importar tildes ni mayúsculas):

    consulta / muestra / estado del pedido <id>        -> consultar_pedido
    actualiza / marca / cambia el pedido <id> ... <estado> -> actualizar_pedido
    elimina / borra el pedido <id>                     -> eliminar_pedido
    envía un correo a <correo> [diciendo ...]          -> enviar_correo
    lee / muestra / consulta la tabla <tabla>          -> leer_base_datos
    ejecuta el comando <comando>                       -> admin_action

Si la herramienta no está en las definiciones que recibe, o no reconoce la intención,
responde con texto y no pide ninguna herramienta.
"""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Any

from .base import RespuestaModelo, ToolCall

TABLAS = ("clientes", "pedidos", "pagos", "config_ti")

# Palabras en español -> estado de Olist (los 8 que admite el CHECK de pedidos.estado).
ESTADOS = {
    "entregado": "delivered", "entregados": "delivered", "delivered": "delivered",
    "enviado": "shipped", "enviados": "shipped", "shipped": "shipped",
    "cancelado": "canceled", "cancelados": "canceled", "canceled": "canceled",
    "aprobado": "approved", "aprobados": "approved", "approved": "approved",
    "facturado": "invoiced", "facturados": "invoiced", "invoiced": "invoiced",
    "en proceso": "processing", "procesando": "processing", "processing": "processing",
    "creado": "created", "creados": "created", "created": "created",
    "no disponible": "unavailable", "unavailable": "unavailable",
}

_ID_PEDIDO = re.compile(r"pedido\s*(?:n(?:o|um(?:ero)?)?\.?\s*)?#?\s*([0-9a-f]{32}|\d+)")
_CORREO = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def _normalizar(texto: str) -> str:
    sin_tildes = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    return " ".join(sin_tildes.lower().split())


class ModeloSimulado:
    nombre = "simulado"

    def generar(
        self, historial: list[dict[str, Any]], tool_definitions: list[dict[str, Any]]
    ) -> RespuestaModelo:
        if not historial:
            return RespuestaModelo(texto="No recibí ninguna instrucción.")

        ultimo = historial[-1]
        if ultimo.get("role") == "tool":
            return RespuestaModelo(texto=self._resumir(historial))

        texto_usuario = next(
            (str(m.get("content") or "") for m in reversed(historial) if m.get("role") == "user"), ""
        )
        intencion = self._intencion(texto_usuario)
        if intencion is None:
            return RespuestaModelo(
                texto="No identifiqué una acción que pueda hacer con mis herramientas. "
                "Puedo consultar, actualizar o eliminar un pedido, enviar un correo, "
                "leer una tabla o ejecutar un comando administrativo."
            )

        nombre, argumentos = intencion
        disponibles = {d.get("name") for d in tool_definitions}
        if nombre not in disponibles:
            return RespuestaModelo(texto=f"No tengo disponible la herramienta {nombre}.")

        n_previas = sum(len(m.get("tool_calls") or []) for m in historial if m.get("role") == "assistant")
        return RespuestaModelo(tool_calls=(ToolCall(id=f"sim-{n_previas + 1}", name=nombre, input=argumentos),))

    # ------------------------------------------------------------------
    def _intencion(self, texto: str) -> tuple[str, dict[str, Any]] | None:
        t = _normalizar(texto)
        id_pedido = _ID_PEDIDO.search(t)
        oid = id_pedido.group(1) if id_pedido else None

        m = re.search(r"ejecuta(?:r)?\s+(?:el\s+)?comando\s*[:\"']?\s*(.+)", t)
        if m:
            return "admin_action", {"comando": m.group(1).strip(" \"'.")}

        if re.search(r"\b(envia|enviar|manda|mandar)\b.*\bcorreo\b", t):
            destino = _CORREO.search(texto)
            if destino:
                cuerpo = re.search(r"(?:diciendo|que diga|con el mensaje)\s*[:\"']?\s*(.+)", texto, re.I | re.S)
                contenido = cuerpo.group(1).strip(" \"'") if cuerpo else "Mensaje de ANDIMARKET S.A.S."
                return "enviar_correo", {"destinatario": destino.group(0), "contenido": contenido}

        if oid and re.search(r"\b(elimina|eliminar|borra|borrar)\b", t):
            return "eliminar_pedido", {"order_id": oid}

        if oid and re.search(r"\b(actualiza|actualizar|marca|marcar|cambia|cambiar)\b", t):
            estado = self._estado(t)
            if estado:
                return "actualizar_pedido", {"order_id": oid, "estado": estado}

        m = re.search(r"\btabla\s+(\w+)", t)
        if m and m.group(1) in TABLAS:
            return "leer_base_datos", {"tabla": m.group(1)}

        if oid:
            return "consultar_pedido", {"order_id": oid}
        return None

    @staticmethod
    def _estado(t: str) -> str | None:
        # Primero las expresiones de dos palabras, para que "no disponible" no se lea como otra cosa.
        for palabra in sorted(ESTADOS, key=len, reverse=True):
            if re.search(rf"\b{re.escape(palabra)}\b", t):
                return ESTADOS[palabra]
        return None

    @staticmethod
    def _resumir(historial: list[dict[str, Any]]) -> str:
        resultados = []
        for m in reversed(historial):
            if m.get("role") != "tool":
                break
            resultados.append(m)
        partes = []
        for m in reversed(resultados):
            try:
                r = json.loads(m.get("content") or "{}")
            except (TypeError, ValueError):
                r = {"ok": True, "data": m.get("content")}
            if isinstance(r, dict) and r.get("ok") is False:
                partes.append(f"{m.get('name')}: no fue posible ({r.get('error')}).")
            else:
                data = r.get("data") if isinstance(r, dict) else r
                resumen = json.dumps(data, ensure_ascii=False)
                if len(resumen) > 400:
                    resumen = resumen[:400] + "…"
                partes.append(f"{m.get('name')}: listo. {resumen}")
        return " ".join(partes) or "Listo."
