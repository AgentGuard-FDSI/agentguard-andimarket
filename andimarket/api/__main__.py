"""Arranca la API:  python -m andimarket.api  [--puerto 8000] [--modelo simulado]

La clave de la demostración se toma de ANDIMARKET_CLAVE_DEMO. Si no está definida, se genera una
al azar y se imprime en la consola (así nunca hay una clave por defecto conocida).
"""

from __future__ import annotations

import argparse
import os
import secrets
from pathlib import Path

from andimarket.api.app import ESPERA_HITL_POR_DEFECTO, MODELOS_CHAT, create_app


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

    clave = os.environ.get("ANDIMARKET_CLAVE_DEMO")
    if not clave:
        clave = secrets.token_urlsafe(9)
        print(f"[api] ANDIMARKET_CLAVE_DEMO no está definida; clave de esta sesión: {clave}")
    app = create_app(datos=args.datos, politica=args.politica, clave=clave, modelo_chat=args.modelo,
                     espera_hitl=args.espera_hitl)
    print(f"[api] política: {app.state.servidor.ruta_politica}")
    print(f"[api] modelo del chat: {args.modelo}; documentación en http://{args.host}:{args.puerto}/docs")
    uvicorn.run(app, host=args.host, port=args.puerto)


if __name__ == "__main__":
    main()
