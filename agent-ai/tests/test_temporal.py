from datetime import UTC, datetime

import pytest

from saltacode_agent.domain.temporal import (
    ARGENTINA_TIMEZONE_NAME,
    build_temporal_context,
    render_temporal_prompt_section,
)


def test_utc_midnight_does_not_advance_salta_date() -> None:
    before_midnight = build_temporal_context(datetime(2026, 8, 6, 1, 30, tzinfo=UTC))
    after_midnight = build_temporal_context(datetime(2026, 8, 6, 3, 1, tzinfo=UTC))

    assert before_midnight.today.isoformat() == "2026-08-05"
    assert before_midnight.yesterday.isoformat() == "2026-08-04"
    assert after_midnight.today.isoformat() == "2026-08-06"


def test_naive_datetime_is_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        build_temporal_context(datetime(2026, 8, 5, 12, 0))


def test_temporal_prompt_has_highest_precedence_and_exact_date() -> None:
    context = build_temporal_context(datetime(2026, 8, 5, 15, 0, tzinfo=UTC))
    section = render_temporal_prompt_section(context)

    assert section.precedence == 0
    assert ARGENTINA_TIMEZONE_NAME in section.content
    assert "Current date: 2026-08-05" in section.content
    assert "override conflicting dates" in section.content
