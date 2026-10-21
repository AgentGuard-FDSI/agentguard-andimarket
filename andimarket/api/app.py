"""API web de ANDIMARKET con AgentGuard (Avance 3, Persona 2).

El chat corre siempre en la Config. B (con todos los controles de agentguard-core). La Config. A
solo aparece en la comparación, como laboratorio aislado: usa sus propias bases y sus propios
controles en memoria, así que no toca la base del chat ni el log de Seguridad.

Sesión: POST /api/login devuelve un token; el resto de endpoints lo piden en la cabecera
`Authorization: Bearer <token>`. La identidad sale de la sesión, nunca del cuerpo de la petición.

Endpoints (todos bajo /api; documentación interactiva en /docs):

    GET  /salud                       estado de la API (sin sesión)
    POST /login, POST /logout, GET /me
    GET  /prompts                     prompts de demostración (un legítimo y los ataques)
    POST /chat                        mensaje libre (modelo del chat) o prompt de demostración (guion)
    GET  /chat/historial              ejecuciones del chat de quien pregunta
    GET  /ejecuciones/{id}?desde=N    polling: estado, eventos nuevos y resultado
    GET  /aprobaciones                pendientes que puedo aprobar, las mías y las recientes
    POST /aprobaciones/{id}           aprobar o rechazar (separación de funciones en el core)
    GET  /seguridad/resumen | /seguridad/registro | /seguridad/alertas | /seguridad/verificar
    GET  /politicas                   policies.yaml en solo lectura y las herramientas de mi área
    POST /comparacion                 un prompt en la Config. A y en la Config. B, lado a lado
    POST /comparacion/experimento     el experimento completo con el modelo de guion
    GET  /comparacion/resultados      los experimentos guardados en evidencia/ (gemini, guion, ...)
    POST /demo/reiniciar              restaura la base del chat (solo Tecnología o Gerencia)

Solo corre una ejecución a la vez (las herramientas comparten la configuración de las bases); si
hay otra en curso, POST /chat y POST /comparacion responden 409. Mientras una ejecución espera una
aprobación HITL, las aprobaciones sí se pueden decidir.
"""

from __future__ import annotations

import json
import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Callable

from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from agentguard import ApprovalRule

from andimarket import comparar
from andimarket.api import vistas
from andimarket.api.ejecuciones import AprobadorWeb, Ejecucion
from andimarket.api.sesiones import DURACION_SEGUNDOS, LoginBloqueado, Sesiones
from andimarket.config_a import preparar_bases, run_config_a, veredicto_de
from andimarket.config_b import (
    capa_contencion, crear_aprobador, crear_controles, resumen_corrida, ruta_politica, run_config_b,
)
from andimarket.modelos import MODELOS, crear_modelo, nombre_de
from andimarket.prompts import PROMPTS, Prompt
from andimarket.run_id import nuevo_run_id
from andimarket.session import Session
from andimarket.toolbox import RegistryToolbox
from models.base import Modelo, ModeloError
from tools import db

ORIGENES_POR_DEFECTO = ("http://localhost:5173", "http://127.0.0.1:5173")  # Vite en desarrollo
MODELOS_CHAT = tuple(m for m in MODELOS if m != "guion")  # el guion solo sirve con un prompt de demostración
AREAS_DE_ADMINISTRACION = ("tecnologia_ti", "gerencia")
MAX_EJECUCIONES = 500
ESPERA_HITL_POR_DEFECTO = 120.0


# ---------------------------------------------------------------------------
# Cuerpos de las peticiones
# ---------------------------------------------------------------------------
class Credenciales(BaseModel):
    usuario: str = Field(min_length=1, max_length=64)
    clave: str = Field(min_length=1, max_length=128)


class MensajeChat(BaseModel):
    """Un mensaje libre o un prompt de demostración (uno de los dos, no ambos)."""

    mensaje: str | None = Field(default=None, max_length=2000, description="Texto libre para el asistente.")
    prompt_id: str | None = Field(default=None, max_length=40,
                                  description="Id de un prompt de demostración (GET /api/prompts), con el guion.")
    modelo: str | None = Field(default=None, max_length=20,
                               description="Modelo del chat; si se omite, el del servidor.")

    model_config = {"json_schema_extra": {"examples": [
        {"mensaje": "Actualiza el pedido 125 a entregado"},
        {"prompt_id": "inyeccion"},
    ]}}


class DecisionHitl(BaseModel):
    aprobar: bool
    comentario: str = Field(default="", max_length=500)


class PedidoComparacion(BaseModel):
    prompt_id: str = Field(max_length=40)


class PedidoExperimento(BaseModel):
    repeticiones: int = Field(default=1, ge=1, le=5)


# ---------------------------------------------------------------------------
# Estado del servidor
# ---------------------------------------------------------------------------
class Servidor:
    def __init__(
        self,
        *,
        datos: Path,
        politica: str | Path | None,
        clave: str,
        modelo_chat: str,
        espera_hitl: float,
        evidencia: Path,
        semilla: Path,
    ):
        if modelo_chat not in MODELOS_CHAT:
            raise ValueError(f"modelo del chat desconocido: {modelo_chat!r}; válidos: {MODELOS_CHAT}")
        self.datos = Path(datos)
        self.laboratorio = self.datos / "api" / "laboratorio"
        self.experimento = self.datos / "api" / "experimento"
        self.evidencia = Path(evidencia)
        self.semilla = Path(semilla)
        self.modelo_chat = modelo_chat
        self.espera_hitl = espera_hitl
        self.ruta_politica = ruta_politica(politica)

        preparar_bases(self.datos, self.semilla)
        self.controles = crear_controles(politica=self.ruta_politica, carpeta=self.datos)
        for pendiente in self.controles.aprobaciones.pendientes():  # su hilo ya no existe
            self.controles.aprobaciones.anular(pendiente.id, "la API se reinició antes de decidirla")
        self.sesiones = Sesiones(clave)
        self.candado = threading.Lock()          # una ejecución a la vez
        self.aviso_hitl = threading.Condition()  # despierta al hilo que espera una aprobación
        self._ejecuciones: dict[str, Ejecucion] = {}
        self._lock = threading.Lock()

    # -- bases -----------------------------------------------------------------
    def usar_bases_chat(self) -> None:
        db.configure(
            ruta_trabajo=self.datos / "andimarket_trabajo.db",
            ruta_evidencia=self.datos / "andimarket_evidencia.db",
        )

    # -- ejecuciones -------------------------------------------------------------
    def ejecucion(self, ejecucion_id: str) -> Ejecucion | None:
        with self._lock:
            return self._ejecuciones.get(ejecucion_id)

    def ejecuciones_de(self, usuario: str, tipo: str) -> list[Ejecucion]:
        with self._lock:
            propias = [e for e in self._ejecuciones.values() if e.sesion.usuario == usuario and e.tipo == tipo]
        return sorted(propias, key=lambda e: e.creada, reverse=True)

    def lanzar(self, ej: Ejecucion, objetivo: Callable[..., None], *args: Any) -> Ejecucion:
        if not self.candado.acquire(blocking=False):
            raise HTTPException(status.HTTP_409_CONFLICT, "Hay otra ejecución en curso; espera a que termine.")
        with self._lock:
            self._ejecuciones[ej.id] = ej
            terminadas = [e for e in self._ejecuciones.values() if not e.activa]
            for vieja in sorted(terminadas, key=lambda e: e.creada)[: max(0, len(self._ejecuciones) - MAX_EJECUCIONES)]:
                del self._ejecuciones[vieja.id]

        def correr() -> None:
            try:
                objetivo(ej, *args)
            except ModeloError as exc:
                ej.fallar(f"el modelo falló: {exc}")
            except Exception as exc:  # noqa: BLE001 - el error se muestra en el frontend
                ej.fallar(f"{type(exc).__name__}: {exc}")
            finally:
                try:
                    self.usar_bases_chat()
                finally:
                    self.candado.release()

        try:
            threading.Thread(target=correr, name=f"ejecucion-{ej.id}", daemon=True).start()
        except Exception:
            self.candado.release()
            raise
        return ej

    def correr_chat(self, ej: Ejecucion, prompt: Prompt, modelo: Modelo) -> None:
        self.usar_bases_chat()
        ej.emitir(f"[modelo] {nombre_de(modelo)}")
        aprobador = AprobadorWeb(
            self.controles.aprobaciones, ej, self.aviso_hitl, run_id=ej.run_id, espera_segundos=self.espera_hitl,
        )
        resultado = run_config_b(prompt, self.controles, aprobador, ej.run_id, model=modelo, emit=ej.emitir)
        veredicto = veredicto_de(prompt, ej.run_id)
        ej.terminar({
            "configuracion": "B",
            "modelo": nombre_de(modelo),
            **resumen_corrida(ej.run_id, resultado, self.controles),
            "efectos": vistas.efectos_de(ej.run_id),
            "ataque": None if veredicto is None else {
                "escenario": prompt.escenario,
                "exitoso": veredicto.exitoso,
                "motivo": veredicto.motivo,
                "capa": capa_contencion(ej.run_id, veredicto),
            },
        })

    def correr_comparacion(self, ej: Ejecucion, prompt: Prompt) -> None:
        controles_lab = crear_controles(self.controles.guard)  # aislados: en memoria, solo para esta comparación
        try:
            salida: dict[str, Any] = {"prompt": prompt_a_dict(prompt)}
            for config in ("A", "B"):
                preparar_bases(self.laboratorio, self.semilla)
                run_id = nuevo_run_id(config, prompt.id)
                ej.emitir(f"Config. {config} ({'sin control' if config == 'A' else 'con AgentGuard'})",
                          tipo="seccion", config=config)

                def emitir(texto: str, _config: str = config) -> None:
                    ej.emitir(texto, config=_config)

                if config == "A":
                    resultado = run_config_a(prompt, RegistryToolbox(), run_id, model=prompt.modelo(), emit=emitir)
                else:
                    aprobador = crear_aprobador("rechazar", prompt.sesion)
                    resultado = run_config_b(prompt, controles_lab, aprobador, run_id, model=prompt.modelo(), emit=emitir)
                veredicto = veredicto_de(prompt, run_id)
                salida[config] = {
                    "run_id": run_id,
                    **resumen_corrida(run_id, resultado, controles_lab if config == "B" else None),
                    "efectos": vistas.efectos_de(run_id),
                    "ataque_exitoso": veredicto.exitoso if veredicto else None,
                    "motivo": veredicto.motivo if veredicto else None,
                    "capa": capa_contencion(run_id, veredicto) if config == "B" else None,
                }
            ej.terminar(salida)
        finally:
            controles_lab.cerrar()

    def correr_experimento(self, ej: Ejecucion, repeticiones: int) -> None:
        _, ruta_md, metricas = comparar.ejecutar(
            "guion", repeticiones, carpeta_datos=self.experimento,
            carpeta_salida=self.experimento / "resultados", emit=ej.emitir,
        )
        ej.terminar({"modelo": "guion", "repeticiones": repeticiones, "metricas": metricas,
                     "reporte_md": ruta_md.read_text(encoding="utf-8")})

    def resultados_guardados(self) -> list[dict[str, Any]]:
        resultados = []
        for ruta in sorted(self.evidencia.glob("comparacion_*.json")):
            try:
                datos = json.loads(ruta.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            resultados.append({
                "archivo": ruta.name,
                **{k: datos.get(k) for k in ("modelo", "fecha", "temperatura", "repeticiones", "aprobador")},
                "metricas": datos.get("metricas"),
            })
        return resultados


def prompt_a_dict(p: Prompt) -> dict[str, Any]:
    return {
        "id": p.id, "nombre": p.nombre, "texto": p.texto, "es_ataque": p.es_ataque, "escenario": p.escenario,
        "sesion": vistas.sesion_a_dict(p.sesion),
    }


# Declara el esquema Bearer en OpenAPI: así /docs muestra el botón "Authorize". auto_error=False para
# responder nosotros el 401 con el mismo mensaje en todos los casos (sin cabecera, esquema o token malos).
ESQUEMA_BEARER = HTTPBearer(auto_error=False, description="Token que devuelve POST /api/login.")


# ---------------------------------------------------------------------------
# Aplicación
# ---------------------------------------------------------------------------
def create_app(
    *,
    datos: str | Path = "data",
    politica: str | Path | None = None,
    clave: str | None = None,
    modelo_chat: str | None = None,
    espera_hitl: float = ESPERA_HITL_POR_DEFECTO,
    evidencia: str | Path = "evidencia",
    semilla: str | Path = db.SEED_TEST,
    origenes: tuple[str, ...] | list[str] | None = None,
) -> FastAPI:
    clave = clave or os.environ.get("ANDIMARKET_CLAVE_DEMO")
    if not clave:
        raise ValueError("falta la clave de la demostración (ANDIMARKET_CLAVE_DEMO)")
    srv = Servidor(
        datos=Path(datos), politica=politica, clave=clave,
        modelo_chat=modelo_chat or os.environ.get("ANDIMARKET_MODELO_CHAT", "simulado"),
        espera_hitl=espera_hitl, evidencia=Path(evidencia), semilla=Path(semilla),
    )

    @asynccontextmanager
    async def ciclo_de_vida(_app: FastAPI):
        yield
        srv.controles.cerrar()

    app = FastAPI(
        title="AgentGuard · ANDIMARKET",
        version="0.1.0",
        description="API de la demostración: chat en la Config. B, aprobaciones HITL, seguridad, políticas "
                    "y comparación con la Config. A.",
        lifespan=ciclo_de_vida,
    )
    app.state.servidor = srv
    env_origenes = os.environ.get("ANDIMARKET_CORS")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(origenes or (env_origenes.split(",") if env_origenes else ORIGENES_POR_DEFECTO)),
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
    )

    def token_actual(credenciales: HTTPAuthorizationCredentials | None = Depends(ESQUEMA_BEARER)) -> str:
        token = credenciales.credentials.strip() if credenciales else None
        if not token or srv.sesiones.validar(token) is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sesión no válida o vencida.",
                                headers={"WWW-Authenticate": "Bearer"})
        return token

    def sesion_actual(token: str = Depends(token_actual)) -> Session:
        sesion = srv.sesiones.validar(token)
        if sesion is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sesión no válida o vencida.",
                                headers={"WWW-Authenticate": "Bearer"})
        return sesion

    def perfil(sesion: Session) -> dict[str, Any]:
        policy = srv.controles.policy
        return {
            **vistas.sesion_a_dict(sesion),
            "aprueba_hitl": policy.top_level(sesion.area) == sesion.nivel,
            "herramientas": list(policy.tools_for_area(sesion.area)),
            "administra_demo": sesion.area in AREAS_DE_ADMINISTRACION,
        }

    # -- salud y sesión -------------------------------------------------------
    @app.get("/api/salud", tags=["sesión"])
    def salud() -> dict[str, Any]:
        return {
            "ok": True,
            "politica": srv.ruta_politica.name,
            "verificador_entrada": srv.controles.verificador_activo,
            "modelo_chat": srv.modelo_chat,
            "ejecucion_en_curso": srv.candado.locked(),
        }

    @app.post("/api/login", tags=["sesión"])
    def login(credenciales: Credenciales) -> dict[str, Any]:
        try:
            activa = srv.sesiones.iniciar(credenciales.usuario, credenciales.clave)
        except LoginBloqueado:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                                "Demasiados intentos fallidos; espera unos minutos.") from None
        if activa is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Usuario o clave incorrectos.")
        return {"token": activa.token, "tipo": "Bearer", "expira_en_segundos": DURACION_SEGUNDOS,
                "usuario": perfil(activa.sesion)}

    @app.post("/api/logout", tags=["sesión"])
    def logout(token: str = Depends(token_actual)) -> dict[str, bool]:
        srv.sesiones.cerrar(token)
        return {"ok": True}

    @app.get("/api/me", tags=["sesión"])
    def me(sesion: Session = Depends(sesion_actual)) -> dict[str, Any]:
        return perfil(sesion)

    # -- asistente (chat, siempre Config. B) ---------------------------------------
    @app.get("/api/prompts", tags=["asistente"])
    def prompts(_: Session = Depends(sesion_actual)) -> list[dict[str, Any]]:
        return [prompt_a_dict(p) for p in PROMPTS.values()]

    @app.post("/api/chat", status_code=status.HTTP_202_ACCEPTED, tags=["asistente"])
    def chat(cuerpo: MensajeChat, sesion: Session = Depends(sesion_actual)) -> dict[str, Any]:
        texto = (cuerpo.mensaje or "").strip()
        if bool(texto) == bool(cuerpo.prompt_id):
            raise HTTPException(422, "Envía un mensaje o un prompt_id (uno de los dos).")
        if cuerpo.prompt_id:
            base = PROMPTS.get(cuerpo.prompt_id)
            if base is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "No existe ese prompt de demostración.")
            # Mismo texto y guion del escenario, pero con la identidad de quien inició sesión.
            prompt = Prompt(base.id, base.nombre, sesion, base.texto, base.es_ataque, base.escenario,
                            base.pasos, base.texto_final)
            nombre_modelo = "guion"
        else:
            prompt = Prompt("chat", "Chat", sesion, texto, False, None, [], "")
            nombre_modelo = cuerpo.modelo or srv.modelo_chat
            if nombre_modelo not in MODELOS_CHAT:
                raise HTTPException(422,
                                    f"Modelo desconocido; válidos para el chat: {', '.join(MODELOS_CHAT)}.")
        try:
            modelo = crear_modelo(nombre_modelo, prompt)
        except ModeloError as exc:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"El modelo no está disponible: {exc}") from None
        ej = Ejecucion("chat", sesion, prompt.texto)
        ej.run_id = nuevo_run_id("B", prompt.id)
        srv.lanzar(ej, srv.correr_chat, prompt, modelo)
        return ej.a_dict()

    @app.get("/api/chat/historial", tags=["asistente"])
    def historial(sesion: Session = Depends(sesion_actual)) -> list[dict[str, Any]]:
        return [e.resumen() for e in srv.ejecuciones_de(sesion.usuario, "chat")]

    @app.get("/api/ejecuciones/{ejecucion_id}", tags=["asistente"])
    def ejecucion(ejecucion_id: str, desde: int = Query(default=0, ge=0),
                  sesion: Session = Depends(sesion_actual)) -> dict[str, Any]:
        ej = srv.ejecucion(ejecucion_id)
        if ej is None or ej.sesion.usuario != sesion.usuario:  # la de otro usuario no existe para ti
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No existe esa ejecución.")
        return ej.a_dict(desde)

    # -- aprobaciones HITL -----------------------------------------------------------
    @app.get("/api/aprobaciones", tags=["aprobaciones"])
    def aprobaciones(sesion: Session = Depends(sesion_actual)) -> dict[str, Any]:
        servicio = srv.controles.aprobaciones
        recientes = [
            e for e in vistas.entradas_visibles(srv.controles.cadena, sesion)
            if e["registro"].get("tipo") in ("hitl_decidida", "hitl_intento_rechazado", "hitl_anulada")
        ][:20]
        return {
            "puedo_aprobar": perfil(sesion)["aprueba_hitl"],
            "pendientes": [vistas.solicitud_a_dict(s) for s in servicio.pendientes(para=sesion.usuario)],
            "mias": [vistas.solicitud_a_dict(s) for s in servicio.pendientes() if s.usuario == sesion.usuario],
            "recientes": recientes,
        }

    @app.post("/api/aprobaciones/{solicitud_id}", tags=["aprobaciones"])
    def decidir(solicitud_id: int, cuerpo: DecisionHitl, sesion: Session = Depends(sesion_actual)) -> dict[str, Any]:
        resultado = srv.controles.aprobaciones.decidir(solicitud_id, sesion.usuario, cuerpo.aprobar, cuerpo.comentario)
        if resultado.rule:
            codigo = {
                ApprovalRule.SOLICITUD_NO_EXISTE.value: status.HTTP_404_NOT_FOUND,
                ApprovalRule.SOLICITUD_YA_DECIDIDA.value: status.HTTP_409_CONFLICT,
            }.get(resultado.rule, status.HTTP_403_FORBIDDEN)
            raise HTTPException(codigo, {"regla": resultado.rule, "motivo": resultado.comment})
        with srv.aviso_hitl:
            srv.aviso_hitl.notify_all()
        return {"solicitud": solicitud_id, "estado": "APPROVED" if resultado.approved else "REJECTED",
                "aprobador": resultado.approver, "comentario": resultado.comment}

    # -- seguridad -----------------------------------------------------------------
    @app.get("/api/seguridad/resumen", tags=["seguridad"])
    def seguridad_resumen(sesion: Session = Depends(sesion_actual)) -> dict[str, Any]:
        visibles = vistas.entradas_visibles(srv.controles.cadena, sesion)
        return {
            **vistas.resumen_seguridad(visibles),
            "pendientes_para_mi": len(srv.controles.aprobaciones.pendientes(para=sesion.usuario)),
            "integridad": vistas.verificacion_a_dict(srv.controles.cadena),
        }

    @app.get("/api/seguridad/registro", tags=["seguridad"])
    def seguridad_registro(
        limite: int = Query(default=100, ge=1, le=500),
        tipo: str | None = Query(default=None, max_length=40),
        sesion: Session = Depends(sesion_actual),
    ) -> list[dict[str, Any]]:
        visibles = vistas.entradas_visibles(srv.controles.cadena, sesion)
        if tipo:
            visibles = [e for e in visibles if e["registro"].get("tipo") == tipo]
        return visibles[:limite]

    @app.get("/api/seguridad/alertas", tags=["seguridad"])
    def seguridad_alertas(sesion: Session = Depends(sesion_actual)) -> list[dict[str, Any]]:
        return [e for e in vistas.entradas_visibles(srv.controles.cadena, sesion)
                if e["registro"].get("tipo") == "notificacion"]

    @app.get("/api/seguridad/verificar", tags=["seguridad"])
    def seguridad_verificar(_: Session = Depends(sesion_actual)) -> dict[str, Any]:
        return vistas.verificacion_a_dict(srv.controles.cadena)

    # -- políticas -----------------------------------------------------------------
    @app.get("/api/politicas", tags=["políticas"])
    def politicas(sesion: Session = Depends(sesion_actual)) -> dict[str, Any]:
        return vistas.politicas(srv.ruta_politica, srv.controles.policy, sesion)

    # -- comparación A y B -----------------------------------------------------------
    @app.post("/api/comparacion", status_code=status.HTTP_202_ACCEPTED, tags=["comparación"])
    def comparacion(cuerpo: PedidoComparacion, sesion: Session = Depends(sesion_actual)) -> dict[str, Any]:
        prompt = PROMPTS.get(cuerpo.prompt_id)
        if prompt is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No existe ese prompt de demostración.")
        ej = Ejecucion("comparacion", sesion, prompt.texto)
        srv.lanzar(ej, srv.correr_comparacion, prompt)
        return ej.a_dict()

    @app.post("/api/comparacion/experimento", status_code=status.HTTP_202_ACCEPTED, tags=["comparación"])
    def experimento(cuerpo: PedidoExperimento, sesion: Session = Depends(sesion_actual)) -> dict[str, Any]:
        ej = Ejecucion("experimento", sesion, f"experimento con guion, {cuerpo.repeticiones} repetición(es)")
        srv.lanzar(ej, srv.correr_experimento, cuerpo.repeticiones)
        return ej.a_dict()

    @app.get("/api/comparacion/resultados", tags=["comparación"])
    def resultados(_: Session = Depends(sesion_actual)) -> list[dict[str, Any]]:
        return srv.resultados_guardados()

    # -- demostración ------------------------------------------------------------------
    @app.post("/api/demo/reiniciar", tags=["demostración"])
    def reiniciar(sesion: Session = Depends(sesion_actual)) -> dict[str, Any]:
        if sesion.area not in AREAS_DE_ADMINISTRACION:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Solo Tecnología o Gerencia pueden reiniciar la demostración.")
        if not srv.candado.acquire(blocking=False):
            raise HTTPException(status.HTTP_409_CONFLICT, "Hay una ejecución en curso; espera a que termine.")
        try:
            preparar_bases(srv.datos, srv.semilla)  # copia la base limpia sobre la de trabajo
        finally:
            srv.candado.release()
        return {"ok": True, "mensaje": "Base de trabajo del chat restaurada desde la base limpia."}

    return app
