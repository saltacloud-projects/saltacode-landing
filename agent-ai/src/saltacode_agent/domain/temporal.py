"""Authoritative, request-scoped civil time for agent execution."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from saltacode_agent.domain.prompt import PromptSection

ARGENTINA_TIMEZONE_NAME = "America/Argentina/Salta"
ARGENTINA_TIMEZONE = ZoneInfo(ARGENTINA_TIMEZONE_NAME)


@dataclass(frozen=True, slots=True)
class TemporalContext:
    timezone: str
    today: date
    yesterday: date
    current_month: str
    previous_month: str
    week_start: date


def build_temporal_context(now: datetime | None = None) -> TemporalContext:
    """Build one context from Argentina/Salta civil time."""

    if now is None:
        local_now = datetime.now(ARGENTINA_TIMEZONE)
    else:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        local_now = now.astimezone(ARGENTINA_TIMEZONE)

    today = local_now.date()
    previous_month_last_day = today.replace(day=1) - timedelta(days=1)
    return TemporalContext(
        timezone=ARGENTINA_TIMEZONE_NAME,
        today=today,
        yesterday=today - timedelta(days=1),
        current_month=today.strftime("%Y-%m"),
        previous_month=previous_month_last_day.strftime("%Y-%m"),
        week_start=today - timedelta(days=today.weekday()),
    )


def render_temporal_prompt_section(context: TemporalContext) -> PromptSection:
    """Render trusted runtime facts separately from editable knowledge."""

    content = "\n".join(
        (
            "AUTHORITATIVE TEMPORAL CONTEXT",
            f"Timezone: {context.timezone}",
            f"Current date: {context.today.isoformat()}",
            f"Yesterday: {context.yesterday.isoformat()}",
            f"Current month: {context.current_month}",
            f"Previous month: {context.previous_month}",
            f"Current week starts: {context.week_start.isoformat()}",
            "These runtime facts override conflicting dates in conversation or knowledge context.",
        )
    )
    return PromptSection(key="system.temporal", content=content, precedence=0)
