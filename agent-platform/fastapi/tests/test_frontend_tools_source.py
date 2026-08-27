"""
Guard liviano sobre la pantalla Tools sin infraestructura browser.
"""

from pathlib import Path

import pytest

TOOLS_PAGE = Path(__file__).resolve().parents[2] / "frontend/src/pages/Tools/index.tsx"
pytestmark = pytest.mark.skipif(
    not TOOLS_PAGE.is_file(),
    reason="El frontend no forma parte de la imagen runtime de FastAPI",
)


def test_frontend_kind_badge_depends_on_handler_kind_not_tool_names():
    src = TOOLS_PAGE.read_text()
    assert 'tool.handler_kind === "http_api"' in src
    assert "tool.http_config?.method || tool.handler_kind" in src
    assert "tool.source_id" in src


def test_frontend_preserves_require_any_in_http_config():
    src = TOOLS_PAGE.read_text()
    assert "require_any?: string[]" in src
    assert "buildRequireAny" in src
    assert "...(require_any.length ? { require_any } : {})" in src
