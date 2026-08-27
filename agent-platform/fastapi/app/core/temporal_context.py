"""Authoritative temporal context for every agent system prompt.

Time is runtime state, not editable knowledge.  This module is the only owner of
the values and interpretation rules that tell the model what "today" means.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

ARGENTINA_TIMEZONE_NAME = "America/Argentina/Buenos_Aires"
ARGENTINA_TIMEZONE = ZoneInfo(ARGENTINA_TIMEZONE_NAME)

TEMPORAL_CONTEXT_KEYS = (
    "fecha_actual",
    "ayer",
    "mes_actual",
    "mes_anterior",
    "inicio_semana",
    "abril_ejemplo",
)


def build_temporal_context(now: datetime | None = None) -> dict[str, str]:
    """Build one request-scoped context using Argentina's civil date.

    ``now`` exists for deterministic tests.  When supplied it must be timezone
    aware so a test cannot silently encode the host timezone into expectations.
    """
    if now is None:
        local_now = datetime.now(ARGENTINA_TIMEZONE)
    else:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        local_now = now.astimezone(ARGENTINA_TIMEZONE)

    today = local_now.date()
    first_day_of_month = today.replace(day=1)
    previous_month_last_day = first_day_of_month - timedelta(days=1)
    week_start = today - timedelta(days=today.weekday())
    return {
        "fecha_actual": today.isoformat(),
        "ayer": (today - timedelta(days=1)).isoformat(),
        "mes_actual": today.strftime("%Y-%m"),
        "mes_anterior": previous_month_last_day.strftime("%Y-%m"),
        "inicio_semana": week_start.isoformat(),
        "abril_ejemplo": f"{today.year}-04",
    }


def render_authoritative_temporal_context(ctx: dict[str, str]) -> str:
    """Render the mandatory, highest-precedence temporal system section."""
    missing = [key for key in TEMPORAL_CONTEXT_KEYS if not ctx.get(key)]
    if missing:
        raise ValueError(f"Missing temporal context values: {', '.join(missing)}")

    return f"""CONTEXTO TEMPORAL AUTORITATIVO DEL SISTEMA
Zona horaria: {ARGENTINA_TIMEZONE_NAME} (hora civil de Argentina).
Fecha actual exacta: {ctx["fecha_actual"]}.
Mes actual: {ctx["mes_actual"]}.
Mes anterior: {ctx["mes_anterior"]}.
Inicio de esta semana: {ctx["inicio_semana"]}.
Ayer: {ctx["ayer"]}.

INTERPRETACIÓN TEMPORAL OBLIGATORIA:
- "hoy" significa {ctx["fecha_actual"]}.
- "ayer" significa {ctx["ayer"]}.
- "este mes" significa {ctx["mes_actual"]}.
- "el mes pasado" o "mes anterior" significa {ctx["mes_anterior"]}.
- "esta semana" abarca desde {ctx["inicio_semana"]} hasta {ctx["fecha_actual"]}.
- Un nombre de mes sin año NO determina por sí solo el año. Usá únicamente un año explícito aportado en el pedido actual; si no existe, preguntá qué año corresponde antes de consultar. Nunca asumas el año solo a partir de fecha_actual, historial o memoria.

PRECEDENCIA OBLIGATORIA: este bloque es la única fuente de verdad para la fecha y los períodos relativos. Si el historial, la memoria conversacional, la evidencia RAG, un bloque de conocimiento o un ejemplo contienen otra fecha actual o una interpretación temporal incompatible, ignorá ese valor anterior y usá SIEMPRE este contexto del sistema."""
