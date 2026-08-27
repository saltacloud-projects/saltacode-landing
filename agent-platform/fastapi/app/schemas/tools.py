"""Channel-neutral tool invocation contracts."""

from typing import Any

from pydantic import BaseModel, Field

# MIME por defecto cuando una tool devuelve un archivo sin especificar tipo.
# Mantiene compatibilidad con los adapters actuales que devuelven Excel.
DEFAULT_FILE_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class ToolInvokeRequest(BaseModel):
    request_id: str
    channel: str = "api"
    principal_id: str | None = None
    conversation_id: str | None = None
    agent_id: str | None = None
    external_subject: str | None = None
    scopes: list[str] = Field(default_factory=list)
    allowed_source_ids: list[str] = Field(default_factory=list)
    confirmed: bool = False
    params: dict[str, Any] = Field(default_factory=dict)
    timeout_override_seconds: int | None = None


class ToolExecutionContext(BaseModel):
    request_id: str
    channel: str
    principal_id: str | None = None
    conversation_id: str | None = None
    agent_id: str | None = None
    external_subject: str | None = None
    scopes: set[str] = Field(default_factory=set)
    allowed_source_ids: set[str] = Field(default_factory=set)
    confirmed: bool = False


def coerce_execution_context(
    value: "ToolExecutionContext | str | None",
    *,
    request_id: str,
) -> ToolExecutionContext:
    if isinstance(value, ToolExecutionContext):
        return value
    return ToolExecutionContext(
        request_id=request_id,
        channel="whatsapp" if value else "api",
        external_subject=str(value) if value else None,
    )


class ToolResult(BaseModel):
    """
    Resultado estándar de una tool.

    Política clave sobre tamaño:
      - `result` es la representación completa de datos para el usuario
        (puede ser grande). Nunca se debe truncar este valor en la tool;
        si el dataset es grande, la tool debe adjuntar el contenido en
        `file_content` (Excel u otro) y/o exponer un texto enumerado.
      - `llm_summary` es la versión reducida y estructurada que se le pasa
        al LLM para generar la respuesta conversacional. Si está vacío,
        el pipeline usará `result` (manteniendo el comportamiento actual).
        Las tools que devuelven datasets grandes DEBEN poblar `llm_summary`
        con totales, conteos, primeros N ítems y metadata relevante.
    """

    request_id: str
    tool_name: str
    status: str
    result: dict[str, Any] = Field(default_factory=dict)
    # Resumen reducido para alimentar al LLM sin saturar contexto/costos.
    # Excluido de la serialización JSON pública del endpoint /internal/tools/invoke.
    llm_summary: dict[str, Any] | None = Field(default=None, exclude=True)
    duration_ms: int | None = None
    error: str | None = None
    # Channel-neutral artifact returned to the delivery adapter.
    file_content: bytes | None = Field(default=None, exclude=True)
    # Referencia interna a un archivo persistido. Permite streaming sin cargar
    # binarios grandes en memoria; nunca se serializa ni se expone al LLM.
    file_storage_key: str | None = Field(default=None, exclude=True)
    file_name: str | None = Field(default=None, exclude=True)
    file_mime: str | None = Field(default=None, exclude=True)
