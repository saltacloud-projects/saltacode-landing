"""Cliente de embeddings con batching y retries acotados."""

import asyncio
import logging

from openai import AsyncOpenAI

from app.config import settings

logger = logging.getLogger(__name__)


class EmbeddingError(RuntimeError):
    pass


class EmbeddingService:
    async def embed_texts(
        self,
        texts: list[str],
        *,
        model: str,
        dimensions: int,
        request_id: str,
    ) -> list[list[float]]:
        if not texts:
            return []
        if not settings.openai_api_key:
            raise EmbeddingError("OPENAI_API_KEY no configurada")
        client = AsyncOpenAI(
            api_key=settings.openai_api_key, timeout=60.0, max_retries=0
        )
        output: list[list[float]] = []
        for start in range(0, len(texts), 64):
            batch = texts[start : start + 64]
            response = None
            for attempt in range(1, 4):
                try:
                    response = await client.embeddings.create(
                        model=model,
                        input=batch,
                        dimensions=dimensions,
                        encoding_format="float",
                    )
                    break
                except Exception as exc:
                    logger.warning(
                        "rag_embedding_retry",
                        extra={
                            "request_id": request_id,
                            "attempt": attempt,
                            "error_type": type(exc).__name__,
                        },
                    )
                    if attempt == 3:
                        raise EmbeddingError(
                            "No se pudieron generar embeddings"
                        ) from exc
                    await asyncio.sleep(2 ** (attempt - 1))
            if response is None:
                raise EmbeddingError("Respuesta de embeddings ausente")
            ordered = sorted(response.data, key=lambda item: item.index)
            output.extend([list(item.embedding) for item in ordered])
        if len(output) != len(texts):
            raise EmbeddingError("Cantidad de embeddings inconsistente")
        return output

    async def embed_query(
        self,
        query: str,
        *,
        model: str,
        dimensions: int,
        request_id: str,
    ) -> list[float]:
        values = await self.embed_texts(
            [query], model=model, dimensions=dimensions, request_id=request_id
        )
        return values[0]


embedding_service = EmbeddingService()
