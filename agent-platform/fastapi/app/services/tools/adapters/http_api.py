"""Declarative, source-bound HTTP tool adapter."""

from __future__ import annotations

import json
import logging
import re
from typing import Any
from urllib.parse import quote

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.integration_source import IntegrationSource
from app.models.tool_config import ToolConfig
from app.schemas.tools import ToolExecutionContext, ToolResult
from app.services.http_executor import SourceRequestError, restricted_http_executor
from app.services.tools.registry import AbstractTool

logger = logging.getLogger(__name__)

_FILE_EXT_BY_MIME = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "application/vnd.ms-excel": "xls",
    "text/csv": "csv",
}


class HttpApiTool(AbstractTool):
    """Loads the current operation and source policy for every invocation."""

    def __init__(self, *, tool_name: str) -> None:
        self.tool_name = tool_name

    def _error(self, request_id: str, message: str) -> ToolResult:
        return ToolResult(
            request_id=request_id,
            tool_name=self.tool_name,
            status="error",
            error=message,
        )

    async def invoke(
        self,
        params: dict[str, Any],
        request_id: str,
        context: ToolExecutionContext | str | None,
    ) -> ToolResult:
        if not isinstance(context, ToolExecutionContext):
            return self._error(request_id, "A trusted execution context is required.")

        async with AsyncSessionLocal() as db:
            row = (
                await db.execute(
                    select(ToolConfig, IntegrationSource)
                    .join(
                        IntegrationSource, ToolConfig.source_id == IntegrationSource.id
                    )
                    .where(ToolConfig.tool_name == self.tool_name)
                )
            ).one_or_none()
            if row is None:
                return self._error(
                    request_id, "The tool has no integration source configured."
                )
            tool, source = row

        if not tool.is_enabled or not source.is_active:
            return self._error(
                request_id, "The tool or its integration source is disabled."
            )
        allowed_channels = {str(value) for value in (tool.allowed_channels or [])}
        if context.channel not in allowed_channels:
            return self._error(request_id, "The tool is not allowed for this channel.")
        if (
            context.allowed_source_ids
            and str(source.id) not in context.allowed_source_ids
        ):
            return self._error(
                request_id, "The integration source is not allowed for this principal."
            )
        if tool.requires_confirmation and not context.confirmed:
            return self._error(
                request_id, "This operation requires explicit confirmation."
            )

        config = tool.http_config or {}
        method = str(config.get("method") or "GET").upper()
        path = str(config.get("path") or "")
        if not path.startswith("/") or "://" in path:
            return self._error(request_id, "The operation path is invalid.")

        params = dict(params or {})
        missing = [
            name
            for name, spec in (tool.params_schema or {}).items()
            if isinstance(spec, dict)
            and spec.get("required")
            and params.get(name) in (None, "")
        ]
        require_any = [str(value) for value in (config.get("require_any") or [])]
        if require_any and not any(
            params.get(name) not in (None, "") for name in require_any
        ):
            missing.append("one of: " + ", ".join(require_any))
        if missing:
            return self._error(
                request_id, "Missing required parameters: " + ", ".join(missing)
            )

        locations = config.get("parameter_locations") or {}
        default_location = str(
            config.get("param_location") or ("query" if method == "GET" else "body")
        )
        query: dict[str, Any] = {}
        body: dict[str, Any] = {}
        headers: dict[str, str] = {}

        for name, value in params.items():
            if value is None or value == "":
                continue
            location = str(locations.get(name) or default_location)
            if location == "path":
                token = "{" + name + "}"
                if token not in path:
                    return self._error(
                        request_id,
                        f"Path parameter '{name}' has no matching placeholder.",
                    )
                path = path.replace(token, quote(str(value), safe=""))
            elif location == "query":
                query[name] = value
            elif location == "body":
                body[name] = value
            elif location == "header":
                header_name = str((config.get("header_names") or {}).get(name) or name)
                headers[header_name] = str(value)
            else:
                return self._error(
                    request_id, f"Unsupported parameter location for '{name}'."
                )

        unresolved = re.findall(r"\{[A-Za-z_][A-Za-z0-9_]*\}", path)
        if unresolved:
            return self._error(
                request_id, "Missing path parameters: " + ", ".join(unresolved)
            )

        idempotency_key = None
        idempotency_param = config.get("idempotency_key_param")
        if idempotency_param:
            raw = params.get(str(idempotency_param))
            idempotency_key = str(raw) if raw not in (None, "") else None
        if tool.risk_level == "write" and method != "GET" and not idempotency_key:
            return self._error(
                request_id, "Write operations require an idempotency key."
            )

        try:
            response = await restricted_http_executor.execute(
                source,
                method=method,
                path=path,
                query=query,
                json_body=body if method not in {"GET", "DELETE"} else None,
                headers=headers,
                idempotency_key=idempotency_key,
            )
        except SourceRequestError as exc:
            logger.warning(
                "http_tool_source_error",
                extra={
                    "tool": self.tool_name,
                    "request_id": request_id,
                    "error_code": exc.code,
                },
            )
            return self._error(request_id, f"Integration request failed ({exc.code}).")

        if not 200 <= response.status_code < 300:
            return self._error(
                request_id, f"Integration returned HTTP {response.status_code}."
            )

        content_type = (
            response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        )
        if tool.result_type == "file":
            return self._file_result(response.content, content_type, request_id)

        try:
            data = json.loads(response.content)
        except (json.JSONDecodeError, UnicodeDecodeError):
            if (
                content_type
                and "text" not in content_type
                and "json" not in content_type
            ):
                return self._file_result(response.content, content_type, request_id)
            data = {"raw": response.content.decode(errors="replace")[:8_000]}

        if isinstance(data, dict):
            result = data
        elif isinstance(data, list):
            result = {"items": data}
        else:
            result = {"result": data}
        return ToolResult(
            request_id=request_id,
            tool_name=self.tool_name,
            status="success",
            result=result,
            duration_ms=response.duration_ms,
        )

    def _file_result(self, content: bytes, mime: str, request_id: str) -> ToolResult:
        mime = mime or "application/octet-stream"
        extension = _FILE_EXT_BY_MIME.get(mime, "bin")
        return ToolResult(
            request_id=request_id,
            tool_name=self.tool_name,
            status="success",
            result={"artifact": True},
            file_content=content,
            file_name=f"{self.tool_name}.{extension}",
            file_mime=mime,
        )
