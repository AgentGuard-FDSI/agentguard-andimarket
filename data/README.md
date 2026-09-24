# Datos

Subconjunto del [Brazilian E-Commerce Public Dataset by Olist](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce)
(licencia CC BY-NC-SA 4.0, uso académico).

Pendiente (Avance 1): `load_olist.py`, que toma unos 500 pedidos con sus clientes y pagos, renombra
ciudades y estados a equivalentes colombianos, genera nombre, correo y teléfono sintéticos, crea la
tabla `config_ti` sintética y escribe todo en `andimarket.db`.

El dataset completo (`data/raw/`) y el `.db` no se versionan: se descargan y se generan con el script.
