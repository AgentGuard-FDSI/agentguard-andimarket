"""Acceso a las bases SQLite de ANDIMARKET.

Hay dos archivos:

* Base de trabajo (negocio): clientes, pedidos, pagos y config_ti. Las herramientas la
  modifican, así que antes de cada corrida se restaura desde una base limpia con reset_db(),
  para que la Config. A y la Config. B partan del mismo estado.
* Base de evidencia: buzon_correo y bitacora_efectos. No se reinicia entre corridas; se
  adjunta con ATTACH bajo el alias "ev", de modo que un efecto y su fila de bitácora se
  confirman en la misma transacción.

Las rutas se toman de las variables de entorno ANDIMARKET_DB y ANDIMARKET_EVIDENCIA_DB, o se
fijan con configure().
"""

from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass, replace
from pathlib import Path

DB_DIR = Path(__file__).resolve().parents[1] / "db"
SCHEMA = DB_DIR / "schema.sql"
SCHEMA_EVIDENCIA = DB_DIR / "schema_evidencia.sql"
SEED_TEST = DB_DIR / "seed_test.sql"

MAX_FILAS_POR_DEFECTO = 50


@dataclass(frozen=True)
class Settings:
    ruta_trabajo: Path
    ruta_evidencia: Path
    max_filas: int


_settings = Settings(
    ruta_trabajo=Path(os.environ.get("ANDIMARKET_DB", "data/andimarket_trabajo.db")),
    ruta_evidencia=Path(os.environ.get("ANDIMARKET_EVIDENCIA_DB", "data/andimarket_evidencia.db")),
    max_filas=int(os.environ.get("ANDIMARKET_MAX_FILAS", MAX_FILAS_POR_DEFECTO)),
)


def configure(
    *,
    ruta_trabajo: str | Path | None = None,
    ruta_evidencia: str | Path | None = None,
    max_filas: int | None = None,
) -> Settings:
    """Cambia las rutas de las bases o el límite de filas de leer_base_datos."""
    global _settings
    if max_filas is not None and (not isinstance(max_filas, int) or max_filas < 1):
        raise ValueError("max_filas debe ser un entero mayor o igual a 1")
    _settings = replace(
        _settings,
        ruta_trabajo=Path(ruta_trabajo) if ruta_trabajo is not None else _settings.ruta_trabajo,
        ruta_evidencia=Path(ruta_evidencia) if ruta_evidencia is not None else _settings.ruta_evidencia,
        max_filas=max_filas if max_filas is not None else _settings.max_filas,
    )
    return _settings


def settings() -> Settings:
    return _settings


def init_db(ruta: str | Path, *, seed: str | Path | None = None) -> Path:
    """Crea una base de negocio nueva con el esquema y, opcionalmente, un archivo de datos."""
    ruta = Path(ruta)
    if ruta.exists():
        raise FileExistsError(f"La base ya existe: {ruta}")
    ruta.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(ruta)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(SCHEMA.read_text(encoding="utf-8"))
        if seed is not None:
            conn.executescript(Path(seed).read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()
    return ruta


def init_evidencia(ruta: str | Path) -> Path:
    """Crea (si no existe) la base de evidencia. Es idempotente y nunca borra filas."""
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(ruta)
    try:
        conn.executescript(SCHEMA_EVIDENCIA.read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()
    return ruta


def reset_db(ruta_base: str | Path, ruta_trabajo: str | Path) -> Path:
    """Copia la base limpia sobre la base de trabajo, reemplazando su contenido.

    Usa la API de respaldo de SQLite (no una copia de archivo) para obtener una copia
    consistente. La base limpia se abre en solo lectura y nunca se modifica.
    """
    base, trabajo = Path(ruta_base), Path(ruta_trabajo)
    if not base.is_file():
        raise FileNotFoundError(f"No existe la base limpia: {base}")
    if base.resolve() == trabajo.resolve():
        raise ValueError("La base limpia y la base de trabajo no pueden ser el mismo archivo")
    trabajo.parent.mkdir(parents=True, exist_ok=True)
    origen = sqlite3.connect(f"{base.resolve().as_uri()}?mode=ro", uri=True)
    destino = sqlite3.connect(trabajo)
    try:
        origen.backup(destino)
    finally:
        destino.close()
        origen.close()
    return trabajo


def connect() -> sqlite3.Connection:
    """Abre la base de trabajo con la base de evidencia adjunta como "ev"."""
    s = _settings
    if not s.ruta_trabajo.is_file():
        # sqlite3.connect crearía un archivo vacío en silencio; se prefiere fallar.
        raise FileNotFoundError(f"No existe la base de trabajo: {s.ruta_trabajo}")
    conn = sqlite3.connect(s.ruta_trabajo)
    _prepare(conn)
    return conn


def connect_evidencia() -> sqlite3.Connection:
    """Abre solo la base de evidencia (alias "ev"), para registrar errores sin base de trabajo."""
    conn = sqlite3.connect(":memory:")
    _prepare(conn)
    return conn


def _prepare(conn: sqlite3.Connection) -> None:
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    ruta_evidencia = init_evidencia(_settings.ruta_evidencia)
    conn.execute("ATTACH DATABASE ? AS ev", (str(ruta_evidencia),))
