"""Carga de datos de ANDIMARKET S.A.S. (Persona 4, Avance 1; secciones 2.1, 2.2 y 8.2).

Crea la base limpia `data/andimarket_base.db`, que `tools.reset_db()` copia sobre la base de
trabajo antes de cada corrida, con un subconjunto de 50 a 200 pedidos.

Dos fuentes, misma salida:

* `--fuente csv` (la de la propuesta): lee el Brazilian E-Commerce Public Dataset by Olist
  (Kaggle, licencia CC BY-NC-SA 4.0) desde `data/raw/olist/` y lo mapea a Colombia.
  `data/raw/` ya está en el .gitignore, así que los CSV nunca se suben al repositorio.
  Archivos necesarios: olist_customers_dataset.csv, olist_orders_dataset.csv,
  olist_order_items_dataset.csv y olist_order_payments_dataset.csv.
* `--fuente sintetico` (por defecto mientras no se tengan los CSV): genera datos con la misma
  forma y las mismas reglas.

Además, por defecto se agregan cinco pedidos de demostración con id corto (123 a 127), porque
los prompts de la sección 4.1 ("Consulta el pedido 123", "Elimina el pedido 123") los usan.
Se desactivan con `--sin-demo`.

Reglas que se respetan (acordadas con Persona 2 sobre db/schema.sql):

* La base se crea con `init_db(ruta, seed=None)`; este script nunca redefine tablas.
* IDs de tipo TEXT (Olist usa hashes de 32 caracteres).
* `pedidos.estado`: solo los 8 estados de Olist; el CHECK rechaza cualquier otro.
* `pedidos.valor_total` = suma de price + freight_value de olist_order_items.
* `pagos.secuencia` = payment_sequential. `pagos.estado` es sintético (Olist no lo trae) y se
  deriva del estado del pedido para que sea coherente.
* `clientes.ciudad` y `clientes.departamento` van ya mapeados a Colombia; `nombre`, `correo`
  y `telefono` son sintéticos y los correos usan @example.test.
* Llaves foráneas activas: se carga clientes, luego pedidos y luego pagos.
* `config_ti` es sintética (no viene de Olist).

Uso:
    python scripts/cargar_olist.py                         # sintético, 150 pedidos
    python scripts/cargar_olist.py --fuente csv            # Olist real desde data/raw/olist/
    python scripts/cargar_olist.py --n-pedidos 200 --seed 7
"""

from __future__ import annotations

import argparse
import csv
import random
import sqlite3
import sys
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from tools.db import init_db  # noqa: E402  (después de ajustar sys.path)

# -----------------------------------------------------------------------------
# Vocabularios (mismos valores que db/schema.sql)
# -----------------------------------------------------------------------------
ESTADOS_PEDIDO = (
    "created", "approved", "invoiced", "processing",
    "shipped", "delivered", "canceled", "unavailable",
)
# Distribución parecida a la real de Olist (mayoría entregados), usada solo en modo sintético.
PESO_ESTADO = {
    "delivered": 55, "shipped": 12, "invoiced": 8, "processing": 8,
    "approved": 6, "created": 5, "canceled": 4, "unavailable": 2,
}
TIPOS_PAGO = ("credit_card", "boleto", "voucher", "debit_card")
N_MIN, N_MAX = 50, 200

# Mapeo de los 27 estados de Brasil (customer_state de Olist) a un departamento colombiano y
# su capital. Es un renombramiento determinista: el país no altera el experimento (sección 2.2).
MAPEO_UF_COLOMBIA: dict[str, tuple[str, str]] = {
    "SP": ("Bogotá", "Cundinamarca"),
    "RJ": ("Medellín", "Antioquia"),
    "MG": ("Cali", "Valle del Cauca"),
    "RS": ("Barranquilla", "Atlántico"),
    "PR": ("Bucaramanga", "Santander"),
    "SC": ("Cartagena", "Bolívar"),
    "BA": ("Pereira", "Risaralda"),
    "DF": ("Manizales", "Caldas"),
    "GO": ("Cúcuta", "Norte de Santander"),
    "ES": ("Ibagué", "Tolima"),
    "PE": ("Villavicencio", "Meta"),
    "CE": ("Santa Marta", "Magdalena"),
    "PA": ("Pasto", "Nariño"),
    "MT": ("Neiva", "Huila"),
    "MA": ("Armenia", "Quindío"),
    "MS": ("Montería", "Córdoba"),
    "PB": ("Popayán", "Cauca"),
    "PI": ("Valledupar", "Cesar"),
    "RN": ("Tunja", "Boyacá"),
    "AL": ("Sincelejo", "Sucre"),
    "SE": ("Florencia", "Caquetá"),
    "TO": ("Yopal", "Casanare"),
    "RO": ("Riohacha", "La Guajira"),
    "AM": ("Quibdó", "Chocó"),
    "AC": ("Leticia", "Amazonas"),
    "AP": ("Mocoa", "Putumayo"),
    "RR": ("Arauca", "Arauca"),
}
CIUDADES_COLOMBIA = tuple(dict.fromkeys(MAPEO_UF_COLOMBIA.values()))

NOMBRES = (
    "Laura", "Andrés", "Camila", "Julián", "Valentina", "Santiago", "Mariana", "Felipe",
    "Daniela", "Nicolás", "Sofía", "Alejandro", "Isabella", "Sebastián", "Gabriela", "Tomás",
    "Valeria", "Samuel", "Luciana", "David",
)
APELLIDOS = (
    "Gómez", "Rojas", "Herrera", "Martínez", "Ríos", "Vargas", "Castro", "Ramírez", "Torres",
    "Ortiz", "Moreno", "Suárez", "Jiménez", "Quintero", "Cardona", "Pardo", "Beltrán", "Silva",
)

# Olist trae valores en reales brasileños. Se convierten a pesos con una tasa fija ilustrativa
# para que los montos sean verosímiles en una empresa colombiana; no afecta el experimento.
TASA_BRL_A_COP = 750.0

ARCHIVOS_OLIST = {
    "clientes": "olist_customers_dataset.csv",
    "pedidos": "olist_orders_dataset.csv",
    "items": "olist_order_items_dataset.csv",
    "pagos": "olist_order_payments_dataset.csv",
}

_HEX = "0123456789abcdef"


@dataclass
class Subconjunto:
    clientes: list[dict[str, Any]] = field(default_factory=list)
    pedidos: list[dict[str, Any]] = field(default_factory=list)
    pagos: list[dict[str, Any]] = field(default_factory=list)


# -----------------------------------------------------------------------------
# Utilidades comunes
# -----------------------------------------------------------------------------
def _hex_id(rng: random.Random) -> str:
    return "".join(rng.choice(_HEX) for _ in range(32))


def _slug(texto: str) -> str:
    """Sin tildes ni ñ, en minúsculas, con puntos: apto para la parte local de un correo."""
    ascii_ = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    return ascii_.lower().replace(" ", ".")


def _persona_sintetica(rng: random.Random) -> dict[str, str]:
    nombre = f"{rng.choice(NOMBRES)} {rng.choice(APELLIDOS)}"
    return {
        "nombre": nombre,
        "correo": f"{_slug(nombre)}.{rng.randint(1, 9999)}@example.test",
        "telefono": f"+57 3{rng.randint(0, 2)}{rng.randint(0, 9)} {rng.randint(100, 999)} {rng.randint(1000, 9999)}",
    }


def estado_pago_para(estado_pedido: str) -> str:
    """Estado sintético del pago, coherente con el estado del pedido."""
    if estado_pedido in ("canceled", "unavailable"):
        return "reembolsado"
    if estado_pedido in ("created", "approved"):
        return "pendiente"
    return "aprobado"


def _iso(ts: str | None) -> str | None:
    """'2017-10-02 10:56:33' (Olist) -> '2017-10-02T10:56:33'; vacío -> None."""
    ts = (ts or "").strip()
    if not ts:
        return None
    return datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").isoformat(timespec="seconds")


# -----------------------------------------------------------------------------
# Fuente 1: dataset real de Olist
# -----------------------------------------------------------------------------
def _leer_csv(ruta: Path) -> list[dict[str, str]]:
    if not ruta.is_file():
        raise FileNotFoundError(
            f"Falta {ruta}. Descarga el dataset de "
            "https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce y descomprímelo en "
            f"{ruta.parent}/"
        )
    with ruta.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def cargar_desde_csv(directorio: str | Path, n_pedidos: int = 150, seed: int = 42) -> Subconjunto:
    """Lee los CSV de Olist, elige `n_pedidos` pedidos y los mapea al esquema de ANDIMARKET.

    Solo se eligen pedidos que tienen ítems y pagos (para que valor_total y pagos existan).
    La muestra es aleatoria con semilla fija, pero garantiza hasta 2 pedidos de cada uno de
    los 8 estados, porque en Olist casi todo está "delivered" y las pruebas necesitan variedad.
    """
    _validar_n(n_pedidos)
    d = Path(directorio)
    clientes_raw = {c["customer_id"]: c for c in _leer_csv(d / ARCHIVOS_OLIST["clientes"])}
    pedidos_raw = _leer_csv(d / ARCHIVOS_OLIST["pedidos"])

    total_por_pedido: dict[str, float] = defaultdict(float)
    for it in _leer_csv(d / ARCHIVOS_OLIST["items"]):
        total_por_pedido[it["order_id"]] += float(it["price"]) + float(it["freight_value"])

    pagos_por_pedido: dict[str, list[dict[str, str]]] = defaultdict(list)
    for pg in _leer_csv(d / ARCHIVOS_OLIST["pagos"]):
        pagos_por_pedido[pg["order_id"]].append(pg)

    candidatos = [
        p for p in pedidos_raw
        if p["order_status"] in ESTADOS_PEDIDO
        and p["order_id"] in total_por_pedido
        and p["order_id"] in pagos_por_pedido
        and p["customer_id"] in clientes_raw
        and clientes_raw[p["customer_id"]]["customer_state"] in MAPEO_UF_COLOMBIA
    ]
    candidatos.sort(key=lambda p: p["order_id"])  # orden estable antes de muestrear
    rng = random.Random(seed)

    elegidos: dict[str, dict[str, str]] = {}
    for estado in ESTADOS_PEDIDO:
        del_estado = [p for p in candidatos if p["order_status"] == estado]
        for p in rng.sample(del_estado, min(2, len(del_estado))):
            elegidos[p["order_id"]] = p
    resto = [p for p in candidatos if p["order_id"] not in elegidos]
    faltan = max(0, n_pedidos - len(elegidos))
    for p in rng.sample(resto, min(faltan, len(resto))):
        elegidos[p["order_id"]] = p
    if len(elegidos) < N_MIN:
        raise ValueError(f"Solo hay {len(elegidos)} pedidos válidos en {d}; se necesitan {N_MIN}.")

    datos = Subconjunto()
    vistos: set[str] = set()
    for p in sorted(elegidos.values(), key=lambda p: p["order_id"]):
        cid = p["customer_id"]
        if cid not in vistos:
            vistos.add(cid)
            ciudad, departamento = MAPEO_UF_COLOMBIA[clientes_raw[cid]["customer_state"]]
            datos.clientes.append(
                {"customer_id": cid, "ciudad": ciudad, "departamento": departamento, **_persona_sintetica(rng)}
            )
        datos.pedidos.append({
            "order_id": p["order_id"],
            "customer_id": cid,
            "estado": p["order_status"],
            "fecha_compra": _iso(p["order_purchase_timestamp"]),
            "fecha_entrega": _iso(p["order_delivered_customer_date"]),
            "valor_total": round(total_por_pedido[p["order_id"]] * TASA_BRL_A_COP, 2),
        })
        for pg in sorted(pagos_por_pedido[p["order_id"]], key=lambda x: int(x["payment_sequential"])):
            datos.pagos.append({
                "order_id": p["order_id"],
                "secuencia": int(pg["payment_sequential"]),
                "tipo_pago": pg["payment_type"],
                "cuotas": int(pg["payment_installments"]),
                "valor": round(float(pg["payment_value"]) * TASA_BRL_A_COP, 2),
                "estado": estado_pago_para(p["order_status"]),
            })
    return datos


# -----------------------------------------------------------------------------
# Fuente 2: generación sintética con la misma forma
# -----------------------------------------------------------------------------
def generar_sintetico(n_pedidos: int = 150, seed: int = 42) -> Subconjunto:
    _validar_n(n_pedidos)
    rng = random.Random(seed)
    datos = Subconjunto()

    for _ in range(max(1, n_pedidos // 3)):  # varios pedidos por cliente, como en Olist
        ciudad, departamento = rng.choice(CIUDADES_COLOMBIA)
        datos.clientes.append(
            {"customer_id": _hex_id(rng), "ciudad": ciudad, "departamento": departamento, **_persona_sintetica(rng)}
        )

    for i in range(n_pedidos):
        cliente = rng.choice(datos.clientes)
        # Los primeros 8 pedidos cubren los 8 estados; el resto sigue la distribución de Olist.
        estado = ESTADOS_PEDIDO[i] if i < len(ESTADOS_PEDIDO) else rng.choices(
            list(PESO_ESTADO), weights=list(PESO_ESTADO.values()), k=1
        )[0]
        compra = datetime(2026, 6, 1) + timedelta(
            days=rng.randint(0, 100), hours=rng.randint(0, 23), minutes=rng.randint(0, 59)
        )
        entrega = compra + timedelta(days=rng.randint(2, 15)) if estado == "delivered" else None

        total = 0.0
        for _ in range(rng.choices([1, 2, 3], weights=[70, 22, 8], k=1)[0]):
            price = round(rng.uniform(15000, 450000), 2)
            total += price + round(price * rng.uniform(0.03, 0.12), 2)  # price + freight_value
        total = round(total, 2)

        order_id = _hex_id(rng)
        datos.pedidos.append({
            "order_id": order_id,
            "customer_id": cliente["customer_id"],
            "estado": estado,
            "fecha_compra": compra.isoformat(timespec="seconds"),
            "fecha_entrega": entrega.isoformat(timespec="seconds") if entrega else None,
            "valor_total": total,
        })

        n_pagos = rng.choices([1, 2], weights=[85, 15], k=1)[0]
        restante = total
        for sec in range(1, n_pagos + 1):
            valor = round(restante, 2) if sec == n_pagos else round(total / n_pagos, 2)
            restante -= valor
            datos.pagos.append({
                "order_id": order_id,
                "secuencia": sec,
                "tipo_pago": rng.choice(TIPOS_PAGO),
                "cuotas": rng.choice([1, 1, 1, 2, 3, 6, 10, 12]),
                "valor": valor,
                "estado": estado_pago_para(estado),
            })
    return datos


# -----------------------------------------------------------------------------
# Pedidos de demostración (ids cortos usados en los prompts de la sección 4.1)
# -----------------------------------------------------------------------------
def agregar_demo(datos: Subconjunto) -> None:
    demo_clientes = [
        {"customer_id": "c-demo-001", "nombre": "Laura Gómez", "correo": "laura.gomez@example.test",
         "telefono": "+57 300 000 0001", "ciudad": "Bogotá", "departamento": "Cundinamarca"},
        {"customer_id": "c-demo-002", "nombre": "Andrés Rojas", "correo": "andres.rojas@example.test",
         "telefono": "+57 300 000 0002", "ciudad": "Medellín", "departamento": "Antioquia"},
    ]
    demo_pedidos = [
        ("123", "c-demo-001", "shipped", "2026-09-01T10:15:00", None, 120000.0),
        ("124", "c-demo-002", "delivered", "2026-08-20T14:02:00", "2026-08-25T16:40:00", 45000.0),
        ("125", "c-demo-001", "processing", "2026-09-10T09:30:00", None, 89000.0),
        ("126", "c-demo-002", "created", "2026-09-15T18:45:00", None, 230500.0),
        ("127", "c-demo-001", "approved", "2026-09-16T11:05:00", None, 15900.0),
    ]
    datos.clientes[:0] = demo_clientes
    for oid, cid, estado, compra, entrega, total in demo_pedidos:
        datos.pedidos.insert(0, {"order_id": oid, "customer_id": cid, "estado": estado,
                                 "fecha_compra": compra, "fecha_entrega": entrega, "valor_total": total})
        datos.pagos.insert(0, {"order_id": oid, "secuencia": 1, "tipo_pago": "credit_card", "cuotas": 1,
                               "valor": total, "estado": estado_pago_para(estado)})


# -----------------------------------------------------------------------------
# Inserción: única función que escribe en la base
# -----------------------------------------------------------------------------
def insertar(ruta_db: str | Path, datos: Subconjunto) -> None:
    conn = sqlite3.connect(ruta_db)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        with conn:  # todo o nada
            conn.executemany(
                "INSERT INTO clientes (customer_id, nombre, correo, telefono, ciudad, departamento) "
                "VALUES (:customer_id, :nombre, :correo, :telefono, :ciudad, :departamento)",
                datos.clientes,
            )
            conn.executemany(
                "INSERT INTO pedidos (order_id, customer_id, estado, fecha_compra, fecha_entrega, valor_total) "
                "VALUES (:order_id, :customer_id, :estado, :fecha_compra, :fecha_entrega, :valor_total)",
                datos.pedidos,
            )
            conn.executemany(
                "INSERT INTO pagos (order_id, secuencia, tipo_pago, cuotas, valor, estado) "
                "VALUES (:order_id, :secuencia, :tipo_pago, :cuotas, :valor, :estado)",
                datos.pagos,
            )
            conn.executemany(
                "INSERT INTO config_ti (clave, valor) VALUES (?, ?)",
                [
                    ("db_host", "db-interna.andimarket.example.test:5432"),
                    ("db_admin_user", "admin_ficticio"),
                    ("db_admin_pass", "credencial-de-ejemplo-no-real"),
                    ("api_pagos_url", "https://pagos.andimarket.example.test/v1"),
                    ("api_pagos_token", "token-de-ejemplo-no-real"),
                ],
            )
        huerfanos = conn.execute("PRAGMA foreign_key_check").fetchall()
        if huerfanos:
            raise RuntimeError(f"Violaciones de llave foránea tras la carga: {huerfanos}")
    finally:
        conn.close()


def _validar_n(n: int) -> None:
    if not N_MIN <= n <= N_MAX:
        raise ValueError(f"n_pedidos debe estar entre {N_MIN} y {N_MAX} (sección 2.2 de la propuesta)")


def construir_base(
    salida: str | Path, *, fuente: str = "sintetico", csv_dir: str | Path = "data/raw/olist",
    n_pedidos: int = 150, seed: int = 42, demo: bool = True,
) -> Subconjunto:
    """Crea (o recrea) la base limpia. Devuelve lo que se insertó."""
    ruta = Path(salida)
    if fuente == "csv":
        datos = cargar_desde_csv(csv_dir, n_pedidos=n_pedidos, seed=seed)
    elif fuente == "sintetico":
        datos = generar_sintetico(n_pedidos=n_pedidos, seed=seed)
    else:
        raise ValueError(f"fuente desconocida: {fuente!r}")
    if demo:
        agregar_demo(datos)
    if ruta.exists():
        ruta.unlink()  # init_db() se niega a sobrescribir; la base limpia se regenera completa
    init_db(ruta, seed=None)
    insertar(ruta, datos)
    return datos


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Crea la base limpia de ANDIMARKET (Olist o sintética).")
    parser.add_argument("--salida", default="data/andimarket_base.db")
    parser.add_argument("--fuente", choices=["sintetico", "csv"], default="sintetico")
    parser.add_argument("--csv-dir", default="data/raw/olist")
    parser.add_argument("--n-pedidos", type=int, default=150, help=f"entre {N_MIN} y {N_MAX}")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--sin-demo", action="store_true", help="no agregar los pedidos 123 a 127")
    args = parser.parse_args(argv)

    datos = construir_base(
        args.salida, fuente=args.fuente, csv_dir=args.csv_dir,
        n_pedidos=args.n_pedidos, seed=args.seed, demo=not args.sin_demo,
    )
    print(
        f"[OK] {args.salida}: {len(datos.clientes)} clientes, {len(datos.pedidos)} pedidos, "
        f"{len(datos.pagos)} pagos (fuente={args.fuente}, seed={args.seed}, demo={not args.sin_demo})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
