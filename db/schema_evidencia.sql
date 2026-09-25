-- Evidencia del experimento: buzón del SMTP falso y bitácora de efectos (sección 4.3).
-- Vive en una base aparte que reset_db NO reinicia, para conservar la evidencia de todas las
-- corridas (Config. A y Config. B) y filtrarla por run_id. Las herramientas la adjuntan con
-- ATTACH, de modo que cada efecto y su fila de bitácora se confirman en la misma transacción.

CREATE TABLE IF NOT EXISTS buzon_correo (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    ts           TEXT NOT NULL,      -- UTC, ISO 8601
    run_id       TEXT NOT NULL,
    destinatario TEXT NOT NULL,
    contenido    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS bitacora_efectos (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ts              TEXT NOT NULL,   -- UTC, ISO 8601
    run_id          TEXT NOT NULL,
    config          TEXT NOT NULL,   -- A | B | sin_contexto
    user_id         TEXT NOT NULL,
    area            TEXT NOT NULL,
    tool            TEXT NOT NULL,
    args_json       TEXT NOT NULL,   -- json.dumps(args, sort_keys=True)
    efecto          TEXT NOT NULL CHECK (efecto IN ('READ', 'UPDATE', 'DELETE', 'EMAIL', 'ADMIN', 'ERROR')),
    objetivo        TEXT,            -- tabla u order_id afectado
    filas_afectadas INTEGER NOT NULL DEFAULT 0,
    detalle_json    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_bitacora_run ON bitacora_efectos (run_id);

-- La bitácora es de solo inserción, también a nivel de base de datos.
CREATE TRIGGER IF NOT EXISTS bitacora_sin_update BEFORE UPDATE ON bitacora_efectos
BEGIN
    SELECT RAISE(ABORT, 'bitacora_efectos es de solo inserción');
END;

CREATE TRIGGER IF NOT EXISTS bitacora_sin_delete BEFORE DELETE ON bitacora_efectos
BEGIN
    SELECT RAISE(ABORT, 'bitacora_efectos es de solo inserción');
END;
