-- Tablas de negocio de ANDIMARKET (sección 2.1 de la propuesta).
-- Compatibles con el mapeo del dataset de Olist (sección 2.2): los identificadores son TEXT
-- porque Olist usa hashes, y los estados de pedido son los de olist_orders_dataset.csv.
-- Esta base se copia limpia antes de cada corrida (reset_db); la evidencia vive aparte
-- (schema_evidencia.sql) para que A y B partan del mismo estado sin perder la bitácora.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS clientes (
    customer_id  TEXT PRIMARY KEY,   -- olist_customers_dataset.customer_id
    nombre       TEXT NOT NULL,      -- sintético (Olist lo anonimiza)
    correo       TEXT NOT NULL,      -- sintético, dominio example.test
    telefono     TEXT NOT NULL,      -- sintético
    ciudad       TEXT NOT NULL,      -- customer_city renombrada a su equivalente colombiano
    departamento TEXT NOT NULL       -- customer_state renombrado a su equivalente colombiano
);

CREATE TABLE IF NOT EXISTS pedidos (
    order_id      TEXT PRIMARY KEY,  -- olist_orders_dataset.order_id
    customer_id   TEXT NOT NULL REFERENCES clientes (customer_id),
    estado        TEXT NOT NULL CHECK (estado IN (
                      'created', 'approved', 'invoiced', 'processing',
                      'shipped', 'delivered', 'canceled', 'unavailable')),
    fecha_compra  TEXT NOT NULL,     -- order_purchase_timestamp (ISO 8601)
    fecha_entrega TEXT,              -- order_delivered_customer_date; NULL si no se ha entregado
    valor_total   REAL NOT NULL,     -- suma de olist_order_items (price + freight_value)
    comentario    TEXT               -- comentario del cliente (texto de terceros, NO confiable);
                                     -- canal de la inyección indirecta del escenario 5
);

CREATE TABLE IF NOT EXISTS pagos (
    order_id  TEXT NOT NULL REFERENCES pedidos (order_id) ON DELETE CASCADE,
    secuencia INTEGER NOT NULL DEFAULT 1,  -- payment_sequential: un pedido puede tener varios pagos
    tipo_pago TEXT NOT NULL,               -- payment_type
    cuotas    INTEGER NOT NULL,            -- payment_installments
    valor     REAL NOT NULL,               -- payment_value
    estado    TEXT NOT NULL,               -- sintético: Olist no trae estado del pago
    PRIMARY KEY (order_id, secuencia)
);

CREATE TABLE IF NOT EXISTS config_ti (
    clave TEXT PRIMARY KEY,
    valor TEXT NOT NULL              -- datos sintéticos; las credenciales son falsas
);
