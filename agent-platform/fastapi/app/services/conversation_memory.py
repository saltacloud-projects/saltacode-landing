"""Agent-scoped conversation memory and provider boundary."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Protocol, Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.concurrency import llm_semaphore
from app.models.platform import ChatConversation, ChatMessage
from app.services.agent_runtime import ResolvedAgentRuntime

logger = logging.getLogger(__name__)

_SUMMARY_WATERMARK = "summary_through"
_MAX_MESSAGES_PER_SUMMARY = 100


class ConversationSummaryProvider(Protocol):
    async def summarize(
        self,
        *,
        runtime: ResolvedAgentRuntime,
        previous_summary: str | None,
        messages: Sequence[ChatMessage],
        max_chars: int,
    ) -> str | None: ...


class OpenAIConversationSummaryProvider:
    async def summarize(
        self,
        *,
        runtime: ResolvedAgentRuntime,
        previous_summary: str | None,
        messages: Sequence[ChatMessage],
        max_chars: int,
    ) -> str | None:
        from openai import AsyncOpenAI

        client_options: dict[str, str] = {"api_key": runtime.api_key}
        if runtime.provider.base_url:
            client_options["base_url"] = runtime.provider.base_url
        client = AsyncOpenAI(**client_options)
        transcript = "\n".join(
            f"{message.role}: {message.content}" for message in messages
        )
        previous = (
            f"Previous summary:\n{previous_summary}\n\n" if previous_summary else ""
        )
        async with llm_semaphore:
            response = await client.chat.completions.create(
                model=runtime.config.chat_model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Maintain a concise, factual conversation summary for future context. "
                            "Merge the previous summary with the new messages. Preserve confirmed facts, "
                            "preferences and pending actions; omit greetings and speculation. Preserve the "
                            "conversation's language. "
                            f"Return only the updated summary, up to {max_chars} characters."
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"{previous}New messages, oldest first:\n{transcript}",
                    },
                ],
                temperature=0.2,
                max_tokens=min(runtime.config.max_output_tokens, 1200),
            )
        text = (response.choices[0].message.content or "").strip()
        return text[:max_chars].rstrip() or None


class ConversationMemoryService:
    def __init__(self, provider: ConversationSummaryProvider | None = None):
        self._provider = provider or OpenAIConversationSummaryProvider()

    async def refresh_summary(
        self,
        db: AsyncSession,
        *,
        conversation: ChatConversation,
        runtime: ResolvedAgentRuntime | None,
    ) -> bool:
        if runtime is None or not runtime.config.summary_enabled:
            return False

        history_limit = max(0, runtime.config.history_message_limit)
        trigger = max(1, runtime.config.summary_trigger_messages)
        watermark = self._watermark(conversation)
        filters = [
            ChatMessage.conversation_id == conversation.id,
            ChatMessage.status == "completed",
        ]
        if watermark is not None:
            filters.append(ChatMessage.created_at > watermark)

        pending = (
            await db.execute(
                select(func.count()).select_from(ChatMessage).where(*filters)
            )
        ).scalar() or 0
        foldable = pending - history_limit
        if foldable < trigger:
            return False

        batch_size = min(foldable, _MAX_MESSAGES_PER_SUMMARY)
        messages = list(
            (
                await db.execute(
                    select(ChatMessage)
                    .where(*filters)
                    .order_by(ChatMessage.created_at.asc())
                    .limit(batch_size)
                )
            )
            .scalars()
            .all()
        )
        if not messages:
            return False

        try:
            summary = await self._provider.summarize(
                runtime=runtime,
                previous_summary=conversation.summary,
                messages=messages,
                max_chars=runtime.config.summary_max_chars,
            )
        except Exception as exc:
            logger.warning(
                "conversation_summary_update_failed",
                extra={"conversation_id": str(conversation.id), "error": str(exc)},
            )
            return False
        if not summary:
            return False

        conversation.summary = summary
        attributes = dict(conversation.attributes or {})
        attributes[_SUMMARY_WATERMARK] = messages[-1].created_at.isoformat()
        conversation.attributes = attributes
        logger.info(
            "conversation_summary_updated",
            extra={
                "conversation_id": str(conversation.id),
                "folded_messages": len(messages),
                "summary_chars": len(summary),
            },
        )
        return True

    @staticmethod
    def _watermark(conversation: ChatConversation) -> datetime | None:
        raw = (conversation.attributes or {}).get(_SUMMARY_WATERMARK)
        if not isinstance(raw, str):
            return None
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            logger.warning(
                "conversation_summary_watermark_invalid",
                extra={"conversation_id": str(conversation.id)},
            )
            return None


conversation_memory_service = ConversationMemoryService()
