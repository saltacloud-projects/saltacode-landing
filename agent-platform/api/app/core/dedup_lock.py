"""
Agent Platform — Idempotencia y locks distribuidos vía Redis.

Provee dos primitivas para el pipeline:

1. `claim_message_id()`: marca un message_id como "en proceso" de forma atómica.
   Si el mismo message_id ya fue reclamado, retorna False — Meta no debe
   reprocesarse aunque mande el webhook duplicado.

2. `conversation_lock()`: context manager que serializa el procesamiento de
   mensajes consecutivos del mismo usuario. Evita race conditions sobre
   `last_tool_params`, ventana conversacional y orden de respuestas.

Si Redis está caído, ambas primitivas degradan a "fail-open": permitir el
procesamiento. Es preferible procesar de más a no responder al usuario.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from contextlib import asynccontextmanager
from typing import AsyncIterator

logger = logging.getLogger(__name__)

# Idempotencia: cuánto tiempo recordamos que un message_id ya fue procesado.
# Meta no debería reintentar más allá de unas horas, pero conservamos 7 días
# como margen amplio para cubrir reinicios largos del servicio.
DEDUP_TTL_SECONDS = 7 * 24 * 3600

# Lock: TTL alto para sobrevivir a pipelines lentos pero seguro vs deadlocks
# si el pipeline crashea sin liberar el lock.
LOCK_TTL_SECONDS = 120

# Espera activa máxima cuando otro mensaje del mismo usuario tiene el lock.
# Si supera este timeout, el mensaje se procesa igual (best effort) para no
# dejar al usuario sin respuesta. El operador verá esto en logs.
LOCK_ACQUIRE_TIMEOUT_SECONDS = 90
LOCK_POLL_INTERVAL_SECONDS = 0.2


def _dedup_key(message_id: str) -> str:
    return f"wa:processed:{message_id}"


def _lock_key(phone_number: str) -> str:
    return f"wa:lock:{phone_number}"


async def claim_message_id(redis, message_id: str | None) -> bool:
    """
    Reclama el procesamiento de un message_id de forma atómica.
    Retorna True si es la primera vez que se ve este message_id;
    False si ya fue reclamado (duplicado de Meta).

    Si Redis falla o el message_id es vacío, retorna True (fail-open).
    """
    if not message_id:
        return True
    if redis is None:
        return True
    try:
        # SET NX EX: crear si no existe, con TTL atómico. Esto es exactamente
        # el patrón canónico de idempotencia con Redis.
        was_set = await redis.set(
            _dedup_key(message_id),
            "1",
            nx=True,
            ex=DEDUP_TTL_SECONDS,
        )
        return bool(was_set)
    except Exception as e:
        logger.warning(
            "dedup_redis_error_failing_open",
            extra={"message_id": message_id, "error": str(e)},
        )
        return True


@asynccontextmanager
async def conversation_lock(
    redis,
    phone_number: str,
    request_id: str,
    timeout_seconds: float = LOCK_ACQUIRE_TIMEOUT_SECONDS,
) -> AsyncIterator[bool]:
    """
    Context manager async que adquiere un lock por phone_number.

    Yield True si el lock fue adquirido limpiamente; False si se procedió
    sin lock porque Redis falló o se superó el timeout de espera.

    Implementación clásica de Redlock simplificado (single-node, suficiente
    para este stack): SET key value NX EX. El value es un token único para
    que solo el dueño pueda liberarlo (delete-if-equals via Lua script).
    """
    token = str(uuid.uuid4())
    key = _lock_key(phone_number)
    acquired = False

    if redis is None:
        # Redis no disponible — procesar sin lock (best effort).
        try:
            yield False
        finally:
            return

    deadline = asyncio.get_event_loop().time() + timeout_seconds
    try:
        while True:
            try:
                ok = await redis.set(key, token, nx=True, ex=LOCK_TTL_SECONDS)
            except Exception as e:
                logger.warning(
                    "conversation_lock_redis_error_failing_open",
                    extra={
                        "phone": phone_number,
                        "request_id": request_id,
                        "error": str(e),
                    },
                )
                break  # procesar sin lock

            if ok:
                acquired = True
                break

            if asyncio.get_event_loop().time() >= deadline:
                logger.warning(
                    "conversation_lock_timeout_failing_open",
                    extra={
                        "phone": phone_number,
                        "request_id": request_id,
                        "timeout_s": timeout_seconds,
                    },
                )
                break

            await asyncio.sleep(LOCK_POLL_INTERVAL_SECONDS)

        yield acquired
    finally:
        if acquired:
            # Liberar solo si el token coincide (no liberar locks ajenos).
            # Script Lua atómico clásico.
            release_script = (
                "if redis.call('get', KEYS[1]) == ARGV[1] then "
                "  return redis.call('del', KEYS[1]) "
                "else return 0 end"
            )
            try:
                await redis.eval(release_script, 1, key, token)
            except Exception as e:
                logger.warning(
                    "conversation_lock_release_error",
                    extra={
                        "phone": phone_number,
                        "request_id": request_id,
                        "error": str(e),
                    },
                )
