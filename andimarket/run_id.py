"""Identificador único de una corrida, compartido por la Config. A y la Config. B.

El criterio de éxito y el audit log filtran por run_id, así que dos corridas nunca deben
compartirlo. La marca de tiempo deja el id legible y ordenable; el sufijo aleatorio evita la
colisión cuando dos corridas caen en el mismo segundo (por ejemplo, las repeticiones del
experimento).

    nuevo_run_id("B", "exfiltracion")  ->  "B-exfiltracion-20261012T195507Z-3f9a1c2e"
"""

from datetime import datetime, timezone
from uuid import uuid4


def nuevo_run_id(config: str, id_prompt: str) -> str:
    return f"{config}-{id_prompt}-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{uuid4().hex[:8]}"
