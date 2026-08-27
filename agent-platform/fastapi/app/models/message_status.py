"""
Agent Platform — Modelo: MessageStatus

Rastrea el estado de ENTREGA real de los mensajes salientes de WhatsApp.

Por qué existe: al enviar via Cloud API, un HTTP 200 solo significa que Meta
"aceptó" el mensaje (status `accepted`), NO que se entregó. La entrega real
llega de forma asíncrona por los webhooks de status (`sent` → `delivered` →
`read`, o `failed` con un código de error). Persistimos esos eventos para tener
visibilidad real de quién recibió cada reporte y por qué falló cuando falla.

Correlación: `meta_message_id` (wamid...) es la clave. Al enviar un template
guardamos un registro con status `accepted`; cuando llega el webhook de status
para ese mismo id, actualizamos el registro (upsert).
"""

from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import TimestampedModel


class MessageStatus(TimestampedModel):
    __tablename__ = "message_statuses"

    # ID del mensaje devuelto por Meta al enviar (wamid...). Clave de correlación
    # con los webhooks de status entrantes.
    meta_message_id: Mapped[str] = mapped_column(
        String(128), unique=True, index=True, nullable=False
    )
    # Teléfono del destinatario. Al enviar usamos el número normalizado; desde el
    # webhook de status usamos el `recipient_id` (wa_id) que reporta Meta.
    phone: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    # Nombre del destinatario si lo conocemos al enviar (desde authorized_users).
    recipient_name: Mapped[str | None] = mapped_column(String(120))
    # Tipo de mensaje saliente: template / text / image / document.
    kind: Mapped[str] = mapped_column(String(20), default="template", nullable=False)
    # Contexto legible para humanos (ej: "reporte 06/06/2026 Tavella").
    context: Mapped[str | None] = mapped_column(String(160))
    # Ciclo de vida del envío:
    #   accepted (HTTP 200 al enviar) → sent → delivered → read | failed
    status: Mapped[str] = mapped_column(
        String(20), default="accepted", index=True, nullable=False
    )
    # Código/título de error de Meta cuando status=failed (ej: 131026 = el número
    # no está en WhatsApp / no se pudo entregar).
    error_code: Mapped[str | None] = mapped_column(String(20))
    error_title: Mapped[str | None] = mapped_column(String(255))
    # Momento del último status reportado por Meta (no confundir con updated_at).
    status_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
