import sqlite3

import pytest

from tools import db


@pytest.fixture
def entorno(tmp_path):
    """Base limpia con seed_test.sql, base de trabajo restaurada y evidencia vacía."""
    base = db.init_db(tmp_path / "base.db", seed=db.SEED_TEST)
    trabajo = db.reset_db(base, tmp_path / "trabajo.db")
    evidencia = tmp_path / "evidencia.db"
    anterior = db.settings()
    db.configure(ruta_trabajo=trabajo, ruta_evidencia=evidencia, max_filas=50)
    yield {"base": base, "trabajo": trabajo, "evidencia": evidencia}
    db.configure(
        ruta_trabajo=anterior.ruta_trabajo,
        ruta_evidencia=anterior.ruta_evidencia,
        max_filas=anterior.max_filas,
    )


def consultar(ruta, sql, params=()):
    conn = sqlite3.connect(ruta)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(f) for f in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


@pytest.fixture
def bitacora(entorno):
    """Devuelve las filas actuales de la bitácora (se llama después de invocar herramientas)."""
    return lambda: consultar(entorno["evidencia"], "SELECT * FROM bitacora_efectos ORDER BY id")


@pytest.fixture
def negocio(entorno):
    return lambda sql, params=(): consultar(entorno["trabajo"], sql, params)
