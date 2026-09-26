"""Pruebas de scripts/cargar_olist.py: fuente sintética y fuente CSV con archivos mínimos de Olist."""

import csv
import sqlite3

import pytest

from scripts import cargar_olist as co
from tools import db


def filas(ruta, sql):
    conn = sqlite3.connect(ruta)
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def verificar_reglas(ruta):
    assert filas(ruta, "PRAGMA foreign_key_check") == []
    estados = {e for (e,) in filas(ruta, "SELECT DISTINCT estado FROM pedidos")}
    assert estados <= set(co.ESTADOS_PEDIDO)
    correos = [c for (c,) in filas(ruta, "SELECT correo FROM clientes")]
    assert all(c.endswith("@example.test") and c.isascii() for c in correos)
    ciudades = {tuple(r) for r in filas(ruta, "SELECT ciudad, departamento FROM clientes")}
    assert ciudades <= set(co.MAPEO_UF_COLOMBIA.values())
    assert filas(ruta, "SELECT COUNT(*) FROM config_ti")[0][0] >= 3


def test_sintetico_cumple_las_reglas(tmp_path):
    ruta = tmp_path / "base.db"
    co.construir_base(ruta, n_pedidos=60, seed=1)
    verificar_reglas(ruta)
    assert filas(ruta, "SELECT COUNT(*) FROM pedidos")[0][0] == 65  # 60 + 5 de demostración
    assert {e for (e,) in filas(ruta, "SELECT DISTINCT estado FROM pedidos")} == set(co.ESTADOS_PEDIDO)
    assert filas(ruta, "SELECT estado FROM pedidos WHERE order_id = '123'") == [("shipped",)]
    # Pagos coherentes con el total del pedido
    desajustes = filas(ruta, """SELECT p.order_id FROM pedidos p JOIN pagos g USING (order_id)
                               GROUP BY p.order_id HAVING ABS(p.valor_total - SUM(g.valor)) > 0.01""")
    assert desajustes == []


def test_sintetico_es_reproducible(tmp_path):
    a, b = tmp_path / "a.db", tmp_path / "b.db"
    co.construir_base(a, seed=7)
    co.construir_base(b, seed=7)
    q = "SELECT * FROM pedidos ORDER BY order_id"
    assert filas(a, q) == filas(b, q)


def test_sin_demo(tmp_path):
    ruta = tmp_path / "base.db"
    co.construir_base(ruta, n_pedidos=50, demo=False)
    assert filas(ruta, "SELECT COUNT(*) FROM pedidos WHERE order_id = '123'")[0][0] == 0


@pytest.mark.parametrize("n", [49, 201])
def test_rango_de_pedidos(tmp_path, n):
    with pytest.raises(ValueError):
        co.construir_base(tmp_path / "x.db", n_pedidos=n)


def test_la_base_sirve_para_reset_db(tmp_path):
    base = tmp_path / "base.db"
    co.construir_base(base, n_pedidos=50)
    trabajo = db.reset_db(base, tmp_path / "trabajo.db")
    assert filas(trabajo, "SELECT COUNT(*) FROM pedidos")[0][0] == 55


# --- Fuente CSV con archivos mínimos que imitan los de Olist -------------------------------
def escribir(ruta, encabezado, registros):
    with ruta.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(encabezado)
        w.writerows(registros)


@pytest.fixture
def olist_minimo(tmp_path):
    d = tmp_path / "olist"
    d.mkdir()
    ufs = list(co.MAPEO_UF_COLOMBIA)
    clientes, pedidos, items, pagos = [], [], [], []
    for i in range(80):
        cid, oid = f"{i:032x}", f"{i + 1000:032x}"
        estado = co.ESTADOS_PEDIDO[i % 8]
        clientes.append([cid, f"u{i}", "01000", "sao paulo", ufs[i % len(ufs)]])
        entrega = "2017-10-10 21:25:13" if estado == "delivered" else ""
        pedidos.append([oid, cid, estado, "2017-10-02 10:56:33", "", "", entrega, "2017-10-18 00:00:00"])
        items.append([oid, 1, "p", "s", "2017-10-06 11:07:15", "29.99", "8.72"])
        items.append([oid, 2, "p", "s", "2017-10-06 11:07:15", "10.00", "1.28"])
        pagos.append([oid, 1, "credit_card", 3, "50.00"])
    escribir(d / co.ARCHIVOS_OLIST["clientes"],
             ["customer_id", "customer_unique_id", "customer_zip_code_prefix", "customer_city", "customer_state"], clientes)
    escribir(d / co.ARCHIVOS_OLIST["pedidos"],
             ["order_id", "customer_id", "order_status", "order_purchase_timestamp", "order_approved_at",
              "order_delivered_carrier_date", "order_delivered_customer_date", "order_estimated_delivery_date"], pedidos)
    escribir(d / co.ARCHIVOS_OLIST["items"],
             ["order_id", "order_item_id", "product_id", "seller_id", "shipping_limit_date", "price", "freight_value"], items)
    escribir(d / co.ARCHIVOS_OLIST["pagos"],
             ["order_id", "payment_sequential", "payment_type", "payment_installments", "payment_value"], pagos)
    return d


def test_csv_mapea_olist(tmp_path, olist_minimo):
    ruta = tmp_path / "base.db"
    co.construir_base(ruta, fuente="csv", csv_dir=olist_minimo, n_pedidos=50, demo=False)
    verificar_reglas(ruta)
    assert filas(ruta, "SELECT COUNT(*) FROM pedidos")[0][0] == 50
    # valor_total = suma de (price + freight_value) de sus ítems, convertido a pesos
    esperado = round((29.99 + 8.72 + 10.00 + 1.28) * co.TASA_BRL_A_COP, 2)
    assert {v for (v,) in filas(ruta, "SELECT valor_total FROM pedidos")} == {esperado}
    assert filas(ruta, "SELECT COUNT(*) FROM pedidos WHERE estado='delivered' AND fecha_entrega IS NULL")[0][0] == 0
    assert filas(ruta, "SELECT DISTINCT fecha_compra FROM pedidos") == [("2017-10-02T10:56:33",)]
    # estado del pago coherente con el del pedido
    assert filas(ruta, """SELECT COUNT(*) FROM pagos g JOIN pedidos p USING (order_id)
                         WHERE p.estado='canceled' AND g.estado <> 'reembolsado'""")[0][0] == 0


def test_csv_faltante_explica_que_hacer(tmp_path):
    with pytest.raises(FileNotFoundError, match="kaggle"):
        co.construir_base(tmp_path / "x.db", fuente="csv", csv_dir=tmp_path / "vacio")
