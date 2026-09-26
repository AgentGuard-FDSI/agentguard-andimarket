"""Traducción entre el formato canónico (models.base) y el de cada proveedor.

Groq y Ollama usan el formato de herramientas estilo OpenAI; Gemini usa el suyo. Estas
funciones son puras (sin red), así que se prueban sin llaves.
"""

from __future__ import annotations

import copy
import json
from typing import Any

from .base import ModeloError, RespuestaModelo, ToolCall

# Claves de JSON Schema que Gemini acepta en "parameters"; el resto se elimina.
_CLAVES_SCHEMA_GEMINI = {"type", "description", "properties", "required", "enum", "items", "format", "nullable"}


def tools_openai(tool_definitions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": d["name"],
                "description": d.get("description", ""),
                "parameters": d.get("input_schema", {"type": "object", "properties": {}}),
            },
        }
        for d in tool_definitions
    ]


def mensajes_openai(historial: list[dict[str, Any]], *, argumentos_como_texto: bool) -> list[dict[str, Any]]:
    """`argumentos_como_texto`: Groq espera los argumentos como JSON en texto; Ollama como objeto."""
    salida: list[dict[str, Any]] = []
    for m in historial:
        rol = m.get("role")
        if rol in ("system", "user"):
            salida.append({"role": rol, "content": str(m.get("content") or "")})
        elif rol == "assistant":
            msg: dict[str, Any] = {"role": "assistant", "content": m.get("content") or ""}
            if m.get("tool_calls"):
                msg["tool_calls"] = [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": json.dumps(tc["input"], ensure_ascii=False)
                            if argumentos_como_texto else tc["input"],
                        },
                    }
                    for tc in m["tool_calls"]
                ]
            salida.append(msg)
        elif rol == "tool":
            salida.append({
                "role": "tool",
                "tool_call_id": m.get("tool_call_id"),
                "name": m.get("name"),
                "tool_name": m.get("name"),  # Ollama usa tool_name; Groq lo ignora
                "content": str(m.get("content") or ""),
            })
        else:
            raise ModeloError(f"rol desconocido en el historial: {rol!r}")
    return salida


def respuesta_desde_openai(mensaje: dict[str, Any], *, prefijo_id: str) -> RespuestaModelo:
    llamadas = []
    for i, tc in enumerate(mensaje.get("tool_calls") or [], start=1):
        fn = tc.get("function") or {}
        args = fn.get("arguments") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args) if args.strip() else {}
            except ValueError:
                raise ModeloError(f"el modelo devolvió argumentos que no son JSON: {args[:200]!r}") from None
        if not isinstance(args, dict):
            raise ModeloError("el modelo devolvió argumentos que no son un objeto JSON")
        llamadas.append(ToolCall(id=tc.get("id") or f"{prefijo_id}-{i}", name=fn.get("name", ""), input=args))
    if llamadas:
        return RespuestaModelo(tool_calls=tuple(llamadas))
    return RespuestaModelo(texto=mensaje.get("content") or "")

def _schema_gemini(schema: Any) -> Any:
    if isinstance(schema, dict):
        limpio = {k: v for k, v in schema.items() if k in _CLAVES_SCHEMA_GEMINI}
        if "properties" in limpio:
            limpio["properties"] = {k: _schema_gemini(v) for k, v in limpio["properties"].items()}
        if "items" in limpio:
            limpio["items"] = _schema_gemini(limpio["items"])
        return limpio
    return schema


def tools_gemini(tool_definitions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{
        "functionDeclarations": [
            {
                "name": d["name"],
                "description": d.get("description", ""),
                "parameters": _schema_gemini(copy.deepcopy(d.get("input_schema", {"type": "object"}))),
            }
            for d in tool_definitions
        ]
    }]


def contenido_gemini(historial: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Devuelve (systemInstruction, contents). Resultados de herramientas consecutivos se
    agrupan en un solo turno "user" con varias functionResponse, como pide la API."""
    sistema: list[str] = []
    contents: list[dict[str, Any]] = []
    for m in historial:
        rol = m.get("role")
        if rol == "system":
            sistema.append(str(m.get("content") or ""))
        elif rol == "user":
            contents.append({"role": "user", "parts": [{"text": str(m.get("content") or "")}]})
        elif rol == "assistant":
            partes: list[dict[str, Any]] = []
            if m.get("content"):
                partes.append({"text": m["content"]})
            for tc in m.get("tool_calls") or []:
                partes.append({"functionCall": {"name": tc["name"], "args": tc["input"]}})
            contents.append({"role": "model", "parts": partes or [{"text": ""}]})
        elif rol == "tool":
            try:
                respuesta = json.loads(m.get("content") or "{}")
            except ValueError:
                respuesta = {"resultado": m.get("content")}
            if not isinstance(respuesta, dict):
                respuesta = {"resultado": respuesta}
            parte = {"functionResponse": {"name": m.get("name"), "response": respuesta}}
            if contents and contents[-1]["role"] == "user" and "functionResponse" in contents[-1]["parts"][0]:
                contents[-1]["parts"].append(parte)
            else:
                contents.append({"role": "user", "parts": [parte]})
        else:
            raise ModeloError(f"rol desconocido en el historial: {rol!r}")
    instruccion = {"parts": [{"text": "\n\n".join(sistema)}]} if sistema else None
    return instruccion, contents


def respuesta_desde_gemini(data: dict[str, Any], *, prefijo_id: str) -> RespuestaModelo:
    candidatos = data.get("candidates") or []
    if not candidatos:
        motivo = (data.get("promptFeedback") or {}).get("blockReason", "sin candidatos")
        raise ModeloError(f"Gemini no devolvió respuesta ({motivo})")
    partes = (candidatos[0].get("content") or {}).get("parts") or []
    llamadas, textos = [], []
    for i, p in enumerate(partes, start=1):
        if "functionCall" in p:
            fc = p["functionCall"]
            llamadas.append(ToolCall(id=fc.get("id") or f"{prefijo_id}-{i}", name=fc.get("name", ""),
                                     input=dict(fc.get("args") or {})))
        elif "text" in p:
            textos.append(p["text"])
    if llamadas:
        return RespuestaModelo(tool_calls=tuple(llamadas))
    return RespuestaModelo(texto="".join(textos))
