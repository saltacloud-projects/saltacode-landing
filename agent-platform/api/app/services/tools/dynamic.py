"""
Synchronization of source-bound declarative HTTP tools.

Lee de `tool_registry` (DB) las tools con handler_kind='http_api' y registra
una instancia de `HttpApiTool` por cada una en el `tool_registry` (memoria).

Como uvicorn corre con 1 worker, registrar/actualizar desde un request admin
(o al arrancar) deja la tool disponible para el agente de inmediato, sin
reiniciar el servicio. Las tools nativas (handler_kind='native') y de base de
datos ('database') no se tocan acá: las registra el código en el lifespan.
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tool_config import ToolConfig
from app.services.tools.adapters.http_api import HttpApiTool
from app.services.tools.registry import tool_registry

logger = logging.getLogger(__name__)

_http_api_tool_names: set[str] = set()


def _build_tool(cfg: ToolConfig) -> HttpApiTool:
    return HttpApiTool(tool_name=cfg.tool_name)


async def sync_http_api_tools(db: AsyncSession) -> int:
    """
    Registra/actualiza en el registry TODAS las tools handler_kind='http_api'.
    Idempotente: `register` sobreescribe por tool_name, así que reflejar una
    edición de http_config es sólo volver a llamar a esta función.
    Retorna la cantidad de tools http_api registradas.
    """
    result = await db.execute(
        select(ToolConfig).where(
            ToolConfig.handler_kind == "http_api",
            ToolConfig.is_enabled == True,  # noqa: E712
            ToolConfig.source_id.is_not(None),
        )
    )
    configs = list(result.scalars().all())
    current_names = {c.tool_name for c in configs}
    stale_names = _http_api_tool_names - current_names
    for name in stale_names:
        tool_registry.unregister(name)

    for cfg in configs:
        tool_registry.register(_build_tool(cfg))

    _http_api_tool_names.clear()
    _http_api_tool_names.update(current_names)

    names = sorted(c.tool_name for c in configs)
    logger.info(
        "http_api_tools_synced",
        extra={
            "count": len(names),
            "tools": names,
            "stale_removed": sorted(stale_names),
        },
    )
    return len(names)


def register_one_http_api_tool(cfg: ToolConfig) -> None:
    """Registra/actualiza una única tool http_api (tras crear/editar en el panel)."""
    tool_registry.register(_build_tool(cfg))
    _http_api_tool_names.add(cfg.tool_name)
    logger.info("http_api_tool_registered", extra={"tool": cfg.tool_name})


def unregister_http_api_tool(tool_name: str) -> None:
    """Quita una tool http_api declarativa del registry runtime."""
    tool_registry.unregister(tool_name)
    _http_api_tool_names.discard(tool_name)
    logger.info("http_api_tool_unregistered", extra={"tool": tool_name})
