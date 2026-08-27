"""
Agent Platform — ConversationService
Gestión de memoria conversacional en 3 niveles:
  1. Ventana activa (Redis) — últimos mensajes, TTL 2 horas
  2. Historial completo (PostgreSQL) — 30 días de retención
  3. Resumen por usuario (PostgreSQL) — persistente indefinido

Uso:
  - El pipeline carga la ventana al inicio de cada mensaje
  - Después de responder, guarda ambos mensajes (user + assistant)
  - La ventana se pasa como historial a OpenAI para contexto conversacional
"""

import json
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.concurrency import llm_semaphore
from app.core.database import AsyncSessionLocal
from app.models.authorized_user import AuthorizedUser
from app.models.conversation_message import ConversationMessage

logger = logging.getLogger(__name__)

# Configuración
WINDOW_TTL_SECONDS = 7200  # 2 horas
MAX_WINDOW_MESSAGES = 20  # máximo de mensajes en la ventana activa
MAX_WINDOW_CHARS = 16000  # ~4000 tokens (1 token ≈ 4 chars en español)


def _cache_key(phone: str) -> str:
    return f"conversation:{phone}"


def _aged_out_messages(rows: list, keep_in_window: int) -> list:
    """De una lista de mensajes en orden ascendente, devuelve los que ya
    "envejecieron": todos menos los últimos `keep_in_window` (que siguen en la
    ventana activa y el agente ya los ve textualmente)."""
    if keep_in_window <= 0:
        return list(rows)
    return rows[:-keep_in_window] if len(rows) > keep_in_window else []


class ConversationService:
    async def load_window(
        self,
        phone: str,
        db: AsyncSession,
        redis=None,
    ) -> list[dict[str, str]]:
        """
        Carga la ventana de conversación activa.
        Prioridad: Redis → PostgreSQL (últimos 10 mensajes) → vacía.
        Retorna lista de dicts {"role": "user"|"assistant", "content": "..."}.
        """
        # 1. Intentar desde Redis
        if redis:
            try:
                raw = await redis.get(_cache_key(phone))
                if raw:
                    return json.loads(raw)
            except Exception as e:
                logger.warning("conversation_cache_miss", extra={"error": str(e)})

        # 2. Cargar desde PostgreSQL (últimos 10 mensajes como contexto inicial)
        messages = await self._load_recent_from_db(db, phone, limit=10)
        if messages and redis:
            await self._save_window_to_redis(redis, phone, messages)

        return messages

    async def save_messages(
        self,
        phone: str,
        user_content: str,
        assistant_content: str,
        db: AsyncSession,
        redis=None,
        intent: str | None = None,
        tool_used: str | None = None,
    ) -> None:
        """
        Guarda el par de mensajes (user + assistant) en PostgreSQL y Redis.
        """
        # 1. Persistir en PostgreSQL
        db.add(
            ConversationMessage(
                phone_number=phone,
                role="user",
                content=user_content,
            )
        )
        db.add(
            ConversationMessage(
                phone_number=phone,
                role="assistant",
                content=assistant_content,
                intent=intent,
                tool_used=tool_used,
            )
        )

        # 2. Actualizar ventana en Redis
        if redis:
            try:
                window = await self.load_window(
                    phone, db, redis=None
                )  # desde DB, no recursivo
                window.append({"role": "user", "content": user_content})
                window.append({"role": "assistant", "content": assistant_content})

                # Trimming: mantener solo últimos MAX_WINDOW_MESSAGES
                if len(window) > MAX_WINDOW_MESSAGES:
                    window = window[-MAX_WINDOW_MESSAGES:]

                # Trimming por tokens: si excede, cortar los más viejos
                window = self._trim_by_chars(window)

                await self._save_window_to_redis(redis, phone, window)
            except Exception as e:
                logger.warning(
                    "conversation_cache_write_error", extra={"error": str(e)}
                )

    def build_openai_messages(
        self,
        window: list[dict[str, str]],
    ) -> list[dict[str, str]]:
        """
        Convierte la ventana de conversación al formato de mensajes de OpenAI.
        Solo incluye role y content (lo que OpenAI espera).
        """
        return [{"role": msg["role"], "content": msg["content"]} for msg in window]

    # -----------------------------------------------------------------------
    # Privados
    # -----------------------------------------------------------------------
    async def _load_recent_from_db(
        self,
        db: AsyncSession,
        phone: str,
        limit: int = 10,
    ) -> list[dict[str, str]]:
        """Carga los últimos N mensajes desde PostgreSQL."""
        result = await db.execute(
            select(ConversationMessage)
            .where(ConversationMessage.phone_number == phone)
            .order_by(ConversationMessage.created_at.desc())
            .limit(limit)
        )
        rows = list(result.scalars().all())
        rows.reverse()  # orden cronológico (más viejo primero)
        return [{"role": row.role, "content": row.content} for row in rows]

    async def _save_window_to_redis(
        self,
        redis,
        phone: str,
        window: list[dict[str, str]],
    ) -> None:
        """Guarda la ventana en Redis con TTL."""
        await redis.setex(
            _cache_key(phone),
            WINDOW_TTL_SECONDS,
            json.dumps(window, ensure_ascii=False),
        )

    def _trim_by_chars(self, window: list[dict[str, str]]) -> list[dict[str, str]]:
        """Elimina mensajes viejos si el total de caracteres excede el límite."""
        total = sum(len(m["content"]) for m in window)
        while total > MAX_WINDOW_CHARS and len(window) > 2:
            removed = window.pop(0)
            total -= len(removed["content"])
        return window

    # -----------------------------------------------------------------------
    # Nivel 3 — Resumen rodante de largo plazo (memoria persistente por usuario)
    # -----------------------------------------------------------------------
    async def get_summary(self, db: AsyncSession, phone: str) -> str | None:
        """Devuelve el resumen rodante (memoria de largo plazo) del usuario, si hay."""
        result = await db.execute(
            select(AuthorizedUser.conversation_summary).where(
                AuthorizedUser.phone_number == phone
            )
        )
        return result.scalar_one_or_none()

    async def maybe_update_summary(self, phone: str) -> None:
        """
        Refresca el resumen rodante del usuario de forma INCREMENTAL cuando hay
        suficientes mensajes que ya "envejecieron" fuera de la ventana activa.

        - Usa su propia sesión DB y corre DESPUÉS de responder al usuario, así no
          agrega latencia perceptible.
        - Es best-effort: nunca rompe el flujo del pipeline (captura todo).
        - El watermark (`summary_updated_at`) marca hasta dónde ya se resumió; se
          dejan SIEMPRE los últimos MAX_WINDOW_MESSAGES sin resumir (están en la
          ventana activa y el agente ya los ve textualmente).
        """
        from app.config import settings

        if not settings.memory_summary_enabled:
            return
        trigger = max(1, settings.memory_summary_trigger_messages)
        try:
            async with AsyncSessionLocal() as db:
                user = (
                    await db.execute(
                        select(AuthorizedUser).where(
                            AuthorizedUser.phone_number == phone
                        )
                    )
                ).scalar_one_or_none()
                if user is None:
                    return

                stmt = select(ConversationMessage).where(
                    ConversationMessage.phone_number == phone
                )
                if user.summary_updated_at is not None:
                    stmt = stmt.where(
                        ConversationMessage.created_at > user.summary_updated_at
                    )
                stmt = stmt.order_by(ConversationMessage.created_at.asc()).limit(
                    MAX_WINDOW_MESSAGES + trigger + 20
                )
                rows = list((await db.execute(stmt)).scalars().all())

                # Dejar los últimos MAX_WINDOW_MESSAGES sin resumir (ventana activa).
                aged_out = _aged_out_messages(rows, MAX_WINDOW_MESSAGES)
                if len(aged_out) < trigger:
                    return

                new_summary = await self._summarize(user.conversation_summary, aged_out)
                if not new_summary:
                    return

                user.conversation_summary = new_summary
                user.summary_updated_at = aged_out[-1].created_at
                await db.commit()
                logger.info(
                    "conversation_summary_updated",
                    extra={
                        "phone": phone,
                        "folded_messages": len(aged_out),
                        "summary_chars": len(new_summary),
                    },
                )
        except Exception as e:
            logger.warning(
                "conversation_summary_update_error",
                extra={"phone": phone, "error": str(e)},
            )

    async def _summarize(
        self,
        previous: str | None,
        messages: list[ConversationMessage],
    ) -> str | None:
        """Compacta (resumen previo + mensajes nuevos) en un resumen actualizado."""
        from app.config import settings

        if not settings.openai_api_key or not messages:
            return None
        transcript = "\n".join(f"{m.role}: {m.content}" for m in messages)
        prev_block = f"Resumen previo:\n{previous}\n\n" if previous else ""
        system = (
            "Mantenés un RESUMEN BREVE y factual de la conversación con un usuario, "
            "para dar continuidad a largo plazo. Integrá el resumen previo con los "
            "mensajes nuevos en un ÚNICO resumen actualizado. Conservá hechos, "
            "preferencias, identificadores y temas pendientes; descartá el chit-chat "
            "y los saludos. No inventes nada. Español rioplatense, en prosa, máximo "
            f"{settings.memory_summary_max_chars} caracteres."
        )
        user_msg = (
            f"{prev_block}Mensajes nuevos (más viejos primero):\n{transcript}\n\n"
            "Devolvé SOLO el resumen actualizado."
        )
        try:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(api_key=settings.openai_api_key)
            async with llm_semaphore:
                resp = await client.chat.completions.create(
                    model=settings.openai_model,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": user_msg},
                    ],
                    temperature=0.2,
                    max_tokens=600,
                )
            text = (resp.choices[0].message.content or "").strip()
            if len(text) > settings.memory_summary_max_chars:
                text = text[: settings.memory_summary_max_chars].rstrip()
            return text or None
        except Exception as e:
            logger.warning("conversation_summarize_llm_error", extra={"error": str(e)})
            return None


conversation_service = ConversationService()
