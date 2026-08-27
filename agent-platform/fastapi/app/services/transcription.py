"""
Agent Platform — TranscriptionService
Descarga audio desde Meta Cloud API y transcribe con OpenAI Whisper.

Flujo completo:
  1. Con el media_id del webhook de Meta, obtener la URL de descarga
  2. Descargar los bytes del audio (OGG/Opus generalmente)
  3. Enviar a Whisper → texto transcripto en español

Docs Meta: https://developers.facebook.com/docs/whatsapp/cloud-api/reference/media
Docs OpenAI Whisper: https://platform.openai.com/docs/guides/speech-to-text
"""

import logging

import httpx
from openai import AsyncOpenAI

from app.config import settings
from app.core.concurrency import llm_semaphore
from app.services.agent_runtime import ResolvedAgentRuntime
from app.services.whatsapp import WhatsAppConnectionContext

logger = logging.getLogger(__name__)

# Tamaño máximo de audio que procesamos (25 MB = límite de Whisper API)
_MAX_AUDIO_BYTES = 25 * 1024 * 1024

# Extensión y mime type del audio de WhatsApp (OGG/Opus)
# Whisper acepta OGG directamente — sin conversión
_AUDIO_FILENAME = "voice.ogg"
_AUDIO_MIME = "audio/ogg"


class TranscriptionService:
    """
    Servicio de transcripción de notas de voz de WhatsApp.
    Usa Meta Graph API para descargar el audio y OpenAI Whisper para transcribir.
    """

    async def download_audio(
        self,
        media_id: str,
        request_id: str = "",
        *,
        connection: WhatsAppConnectionContext | None = None,
    ) -> bytes | None:
        """
        Descarga el audio de Meta Cloud API dado su media_id.

        Proceso en 2 pasos (requerido por Meta):
          1. GET /{media_id}  → obtiene la URL temporal de descarga
          2. GET {url}        → descarga los bytes con el token de autorización

        Retorna los bytes del audio, o None si falla.
        """
        access_token = (
            connection.access_token if connection else settings.whatsapp_token
        )
        if not access_token:
            logger.warning(
                "transcription_download_skipped",
                extra={
                    "reason": "whatsapp_token no configurado",
                    "request_id": request_id,
                },
            )
            return None

        graph_url = f"https://graph.facebook.com/v21.0/{media_id}"
        auth_headers = {"Authorization": f"Bearer {access_token}"}

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                # Paso 1: resolver URL de descarga
                meta_resp = await client.get(graph_url, headers=auth_headers)
                meta_resp.raise_for_status()
                download_url = meta_resp.json().get("url")

                if not download_url:
                    logger.error(
                        "transcription_no_download_url",
                        extra={"media_id": media_id, "request_id": request_id},
                    )
                    return None

                # Paso 2: descargar el archivo
                audio_resp = await client.get(download_url, headers=auth_headers)
                audio_resp.raise_for_status()
                audio_bytes = audio_resp.content

                if len(audio_bytes) > _MAX_AUDIO_BYTES:
                    logger.warning(
                        "transcription_audio_too_large",
                        extra={
                            "media_id": media_id,
                            "bytes": len(audio_bytes),
                            "limit": _MAX_AUDIO_BYTES,
                            "request_id": request_id,
                        },
                    )
                    return None

                logger.info(
                    "transcription_audio_downloaded",
                    extra={
                        "media_id": media_id,
                        "bytes": len(audio_bytes),
                        "request_id": request_id,
                    },
                )
                return audio_bytes

        except httpx.HTTPStatusError as e:
            logger.error(
                "transcription_download_http_error",
                extra={
                    "media_id": media_id,
                    "status": e.response.status_code,
                    "request_id": request_id,
                },
            )
            return None
        except Exception as e:
            logger.error(
                "transcription_download_error",
                extra={
                    "media_id": media_id,
                    "error_type": type(e).__name__,
                    "request_id": request_id,
                },
            )
            return None

    async def transcribe(
        self,
        audio_bytes: bytes,
        request_id: str = "",
        *,
        runtime: ResolvedAgentRuntime | None = None,
    ) -> str | None:
        """
        Transcribe bytes de audio usando OpenAI Whisper.

        Args:
            audio_bytes: Bytes del archivo de audio (OGG/Opus de WhatsApp)
            request_id: ID para logging y trazabilidad

        Retorna el texto transcripto, o None si falla.
        """
        api_key = runtime.api_key if runtime else settings.openai_api_key
        model = (
            runtime.config.transcription_model
            if runtime
            else settings.openai_whisper_model
        )
        if not api_key:
            logger.warning(
                "transcription_skipped",
                extra={
                    "reason": "openai_api_key no configurado",
                    "request_id": request_id,
                },
            )
            return None

        client_options = {"api_key": api_key}
        if runtime and runtime.provider.base_url:
            client_options["base_url"] = runtime.provider.base_url
        client = AsyncOpenAI(**client_options)

        try:
            # Whisper requiere un tuple (filename, bytes, mime_type) como file
            async with llm_semaphore:
                response = await client.audio.transcriptions.create(
                    model=model,
                    file=(_AUDIO_FILENAME, audio_bytes, _AUDIO_MIME),
                    language="es",  # Forzar español para mayor precisión en contextos en español
                    response_format="text",
                )

            # response es un str cuando response_format="text"
            transcript = str(response).strip() if response else ""

            if not transcript:
                logger.warning(
                    "transcription_empty_result",
                    extra={"request_id": request_id},
                )
                return None

            logger.info(
                "transcription_completed",
                extra={
                    "request_id": request_id,
                    "chars": len(transcript),
                    "preview": transcript[:80],
                },
            )
            return transcript

        except Exception as e:
            logger.error(
                "transcription_error",
                extra={"error_type": type(e).__name__, "request_id": request_id},
            )
            return None

    async def download_and_transcribe(
        self,
        media_id: str,
        request_id: str = "",
        *,
        connection: WhatsAppConnectionContext | None = None,
        runtime: ResolvedAgentRuntime | None = None,
    ) -> str | None:
        """
        Descarga y transcribe en un solo paso.
        Retorna el texto transcripto o None si algún paso falla.
        """
        audio_bytes = await self.download_audio(
            media_id, request_id=request_id, connection=connection
        )
        if audio_bytes is None:
            return None
        return await self.transcribe(
            audio_bytes, request_id=request_id, runtime=runtime
        )


transcription_service = TranscriptionService()
