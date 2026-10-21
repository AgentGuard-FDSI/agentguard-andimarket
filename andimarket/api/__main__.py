"""Arranca la API:  python -m andimarket.api  [--puerto 8000] [--modelo simulado]

La clave de la demostración se toma de ANDIMARKET_CLAVE_DEMO (variable de entorno o archivo `.env`).
Si no está definida y la API escucha solo en este equipo (127.0.0.1, el valor por defecto), se usa la
clave de demostración local "demo2026". Para exponer la API en la red (--host 0.0.0.0, por ejemplo) hay
que definir una clave propia: con una clave conocida, la API se niega a arrancar.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from models._config import cargar_dotenv

from andimarket.api.app import ESPERA_HITL_POR_DEFECTO, MODELOS_CHAT, create_app

CLAVE_LOCAL = "demo2026"
HOSTS_LOCALES = frozenset({"127.0.0.1", "localhost", "::1"})


def clave_demo(host: str) -> str:
    """La clave de la demostración: ANDIMARKET_CLAVE_DEMO (entorno o .env) o, solo en local, "demo2026"."""
    cargar_dotenv()
    clave = os.environ.get("ANDIMARKET_CLAVE_DEMO", "").strip()
    if clave:
        return clave
    if host in HOSTS_LOCALES:
        return CLAVE_LOCAL
    raise SystemExit(
        f"[api] --host {host} expone la API fuera de este equipo: define ANDIMARKET_CLAVE_DEMO "
        "(en la consola o en .env) con una clave propia antes de arrancar."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="API web de ANDIMARKET con AgentGuard.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--puerto", type=int, default=8000)
    parser.add_argument("--datos", type=Path, default=Path("data"), help="carpeta de las bases SQLite")
    parser.add_argument("--politica", type=Path, default=None, help="ruta de policies.yaml")
    parser.add_argument("--modelo", choices=MODELOS_CHAT, default=os.environ.get("ANDIMARKET_MODELO_CHAT", "simulado"),
                        help="modelo del chat (los prompts de demostración usan siempre el guion)")
    parser.add_argument("--espera-hitl", type=float, default=ESPERA_HITL_POR_DEFECTO,
                        help="segundos que una acción HITL espera al aprobador antes de anularse")
    args = parser.parse_args()

    import uvicorn

    clave = clave_demo(args.host)
    if clave == CLAVE_LOCAL:
        print(f"[api] clave de demostración local: {CLAVE_LOCAL} (cámbiala con ANDIMARKET_CLAVE_DEMO en .env)")
    app = create_app(datos=args.datos, politica=args.politica, clave=clave, modelo_chat=args.modelo,
                     espera_hitl=args.espera_hitl)
    print(f"[api] política: {app.state.servidor.ruta_politica}")
    print(f"[api] modelo del chat: {args.modelo}; documentación en http://{args.host}:{args.puerto}/docs")
    uvicorn.run(app, host=args.host, port=args.puerto)


if __name__ == "__main__":
    main()
