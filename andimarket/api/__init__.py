"""API web de ANDIMARKET (Avance 3, Persona 2): la Config. A y la Config. B detrás de FastAPI.

    python -m andimarket.api             (arranca en http://127.0.0.1:8000; documentación en /docs)

Ver andimarket/api/app.py para los endpoints.
"""

from andimarket.api.app import create_app

__all__ = ["create_app"]
