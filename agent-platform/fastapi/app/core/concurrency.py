"""Per-process concurrency limits for channel and provider backpressure."""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)

# Límites razonables para el volumen actual. Estos valores deben ser
# revisados si el patrón de uso cambia.
MAX_CONCURRENT_PIPELINES = 20  # pipelines completos corriendo en paralelo
MAX_CONCURRENT_LLM_CALLS = 8  # llamadas a OpenAI simultáneas
MAX_CONCURRENT_INTEGRATION_CALLS = 10  # llamadas a fuentes simultáneas
MAX_CONCURRENT_WHATSAPP_CALLS = 15  # envíos a WhatsApp Graph API simultáneos

pipeline_semaphore = asyncio.Semaphore(MAX_CONCURRENT_PIPELINES)
llm_semaphore = asyncio.Semaphore(MAX_CONCURRENT_LLM_CALLS)
integration_semaphore = asyncio.Semaphore(MAX_CONCURRENT_INTEGRATION_CALLS)
whatsapp_semaphore = asyncio.Semaphore(MAX_CONCURRENT_WHATSAPP_CALLS)


def get_semaphores_state() -> dict[str, int]:
    """Helper de observabilidad: cuántos slots quedan en cada semáforo."""
    return {
        "pipeline_free": pipeline_semaphore._value,  # type: ignore[attr-defined]
        "llm_free": llm_semaphore._value,  # type: ignore[attr-defined]
        "integration_free": integration_semaphore._value,  # type: ignore[attr-defined]
        "whatsapp_free": whatsapp_semaphore._value,  # type: ignore[attr-defined]
    }
