"""Entrypoint del worker RAG."""

import asyncio

from app.core.logging import setup_logging
from app.services.rag.ingestion import rag_ingestion_worker


def main() -> None:
    setup_logging()
    asyncio.run(rag_ingestion_worker.run_forever())


if __name__ == "__main__":
    main()
