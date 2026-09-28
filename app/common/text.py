from typing import Annotated

from pydantic import StringConstraints

#: El motivo de una acción auditada (reabrir la caja, anular, egresar,
#: descontar). Se recorta y tiene que quedar algo: un motivo vacío o de
#: puros espacios es una auditoría sin contenido (F5-05). Un `str` con
#: `min_length=1` solo no alcanza: `" "` lo cumple.
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
