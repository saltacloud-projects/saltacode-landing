"""
Tests unitarios para TranscriptionService.

Cubre:
  - download_audio: éxito, error HTTP, sin token
  - transcribe: éxito, resultado vacío, error de API, sin API key
  - download_and_transcribe: flujo completo happy path y fallo en descarga

Ejecutar:
    docker compose exec api python -m pytest tests/test_transcription.py -v
"""

import os
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import httpx
import pytest

os.environ.setdefault("FASTAPI_ENV", "testing")
os.environ.setdefault("POSTGRES_DSN", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("FASTAPI_API_KEY", "test-api-key")
os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("WHATSAPP_TOKEN", "test-wa-token")
os.environ.setdefault("WHATSAPP_PHONE_NUMBER_ID", "123456")
os.environ.setdefault("WHATSAPP_VERIFY_TOKEN", "test-verify")

from app.services.transcription import TranscriptionService
from app.services.whatsapp import WhatsAppConnectionContext

REQ_ID = "test-req-audio-001"
FAKE_MEDIA_ID = "media_abc123"
FAKE_AUDIO_BYTES = b"OGG_FAKE_AUDIO_DATA"
FAKE_TRANSCRIPT = "quiero consultar el estado del artículo A-123"


def _whatsapp_connection() -> WhatsAppConnectionContext:
    return WhatsAppConnectionContext(
        connection_id=uuid4(),
        phone_number_id="123456",
        access_token="test-wa-token",
        verify_token="test-verify",
        app_secret="test-app-secret",
        route_key="test-route",
    )


# ---------------------------------------------------------------------------
# download_audio
# ---------------------------------------------------------------------------


class TestDownloadAudio:
    def setup_method(self):
        self.svc = TranscriptionService()

    @pytest.mark.asyncio
    async def test_download_success(self):
        """Happy path: Meta devuelve URL y el audio se descarga correctamente."""
        # Primer request: resolve URL
        meta_resp = MagicMock()
        meta_resp.status_code = 200
        meta_resp.json.return_value = {
            "url": "https://cdn.meta.com/audio/abc.ogg",
            "id": FAKE_MEDIA_ID,
        }
        meta_resp.raise_for_status = MagicMock()

        # Segundo request: descarga del audio
        audio_resp = MagicMock()
        audio_resp.status_code = 200
        audio_resp.content = FAKE_AUDIO_BYTES
        audio_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.side_effect = [meta_resp, audio_resp]
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "app.services.transcription.httpx.AsyncClient", return_value=mock_client
        ):
            result = await self.svc.download_audio(
                FAKE_MEDIA_ID,
                request_id=REQ_ID,
                connection=_whatsapp_connection(),
            )

        assert result == FAKE_AUDIO_BYTES

    @pytest.mark.asyncio
    async def test_download_no_whatsapp_token(self):
        """Sin token de WhatsApp, retorna None sin hacer requests."""
        with patch("app.services.transcription.settings") as mock_settings:
            mock_settings.whatsapp_token = ""
            result = await self.svc.download_audio(FAKE_MEDIA_ID, request_id=REQ_ID)
        assert result is None

    @pytest.mark.asyncio
    async def test_download_http_error(self):
        """Si Meta responde 4xx al resolver la URL, retorna None."""
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.text = "Bad Request"
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "400", request=httpx.Request("GET", "http://test"), response=mock_resp
        )
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "app.services.transcription.httpx.AsyncClient", return_value=mock_client
        ):
            result = await self.svc.download_audio(
                FAKE_MEDIA_ID,
                request_id=REQ_ID,
                connection=_whatsapp_connection(),
            )

        assert result is None

    @pytest.mark.asyncio
    async def test_download_no_url_in_response(self):
        """Si Meta no devuelve 'url' en el JSON, retorna None."""
        meta_resp = MagicMock()
        meta_resp.status_code = 200
        meta_resp.json.return_value = {"id": FAKE_MEDIA_ID}  # sin 'url'
        meta_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = meta_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "app.services.transcription.httpx.AsyncClient", return_value=mock_client
        ):
            result = await self.svc.download_audio(
                FAKE_MEDIA_ID,
                request_id=REQ_ID,
                connection=_whatsapp_connection(),
            )

        assert result is None

    @pytest.mark.asyncio
    async def test_download_audio_too_large(self):
        """Si el audio supera el límite de 25 MB, retorna None."""
        meta_resp = MagicMock()
        meta_resp.status_code = 200
        meta_resp.json.return_value = {"url": "https://cdn.meta.com/big.ogg"}
        meta_resp.raise_for_status = MagicMock()

        big_audio = b"X" * (26 * 1024 * 1024)  # 26 MB
        audio_resp = MagicMock()
        audio_resp.status_code = 200
        audio_resp.content = big_audio
        audio_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.side_effect = [meta_resp, audio_resp]
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch(
            "app.services.transcription.httpx.AsyncClient", return_value=mock_client
        ):
            result = await self.svc.download_audio(
                FAKE_MEDIA_ID,
                request_id=REQ_ID,
                connection=_whatsapp_connection(),
            )

        assert result is None


# ---------------------------------------------------------------------------
# transcribe
# ---------------------------------------------------------------------------


class TestTranscribe:
    def setup_method(self):
        self.svc = TranscriptionService()

    @pytest.mark.asyncio
    async def test_transcribe_success(self):
        """Happy path: Whisper retorna el texto transcripto."""
        mock_client = AsyncMock()
        mock_client.audio.transcriptions.create = AsyncMock(
            return_value=FAKE_TRANSCRIPT
        )

        with patch("app.services.transcription.AsyncOpenAI", return_value=mock_client):
            result = await self.svc.transcribe(FAKE_AUDIO_BYTES, request_id=REQ_ID)

        assert result == FAKE_TRANSCRIPT

    @pytest.mark.asyncio
    async def test_transcribe_no_openai_key(self):
        """Sin API key de OpenAI, retorna None sin llamar a Whisper."""
        with patch("app.services.transcription.settings") as mock_settings:
            mock_settings.openai_api_key = ""
            result = await self.svc.transcribe(FAKE_AUDIO_BYTES, request_id=REQ_ID)
        assert result is None

    @pytest.mark.asyncio
    async def test_transcribe_empty_result(self):
        """Si Whisper retorna cadena vacía, retorna None."""
        mock_client = AsyncMock()
        mock_client.audio.transcriptions.create = AsyncMock(return_value="   ")

        with patch("app.services.transcription.AsyncOpenAI", return_value=mock_client):
            result = await self.svc.transcribe(FAKE_AUDIO_BYTES, request_id=REQ_ID)

        assert result is None

    @pytest.mark.asyncio
    async def test_transcribe_openai_error(self):
        """Si Whisper lanza excepción, retorna None."""
        mock_client = AsyncMock()
        mock_client.audio.transcriptions.create = AsyncMock(
            side_effect=Exception("Connection error")
        )

        with patch("app.services.transcription.AsyncOpenAI", return_value=mock_client):
            result = await self.svc.transcribe(FAKE_AUDIO_BYTES, request_id=REQ_ID)

        assert result is None


# ---------------------------------------------------------------------------
# download_and_transcribe (flujo integrado)
# ---------------------------------------------------------------------------


class TestDownloadAndTranscribe:
    def setup_method(self):
        self.svc = TranscriptionService()

    @pytest.mark.asyncio
    async def test_full_flow_success(self):
        """download_and_transcribe retorna el transcript cuando todo funciona."""
        with patch.object(
            self.svc, "download_audio", AsyncMock(return_value=FAKE_AUDIO_BYTES)
        ):
            with patch.object(
                self.svc, "transcribe", AsyncMock(return_value=FAKE_TRANSCRIPT)
            ):
                result = await self.svc.download_and_transcribe(
                    FAKE_MEDIA_ID, request_id=REQ_ID
                )
        assert result == FAKE_TRANSCRIPT

    @pytest.mark.asyncio
    async def test_full_flow_download_fails(self):
        """Si la descarga falla, retorna None sin llamar a Whisper."""
        with patch.object(self.svc, "download_audio", AsyncMock(return_value=None)):
            with patch.object(self.svc, "transcribe", AsyncMock()) as mock_transcribe:
                result = await self.svc.download_and_transcribe(
                    FAKE_MEDIA_ID, request_id=REQ_ID
                )

        assert result is None
        mock_transcribe.assert_not_called()

    @pytest.mark.asyncio
    async def test_full_flow_transcribe_fails(self):
        """Si Whisper falla, retorna None."""
        with patch.object(
            self.svc, "download_audio", AsyncMock(return_value=FAKE_AUDIO_BYTES)
        ):
            with patch.object(self.svc, "transcribe", AsyncMock(return_value=None)):
                result = await self.svc.download_and_transcribe(
                    FAKE_MEDIA_ID, request_id=REQ_ID
                )
        assert result is None
