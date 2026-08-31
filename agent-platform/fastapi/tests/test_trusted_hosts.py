"""Production trusted-host contract tests."""

from app.main import _PRODUCTION_TRUSTED_HOSTS


def test_production_allows_agent_platform_compose_hostname():
    assert "agent-platform" in _PRODUCTION_TRUSTED_HOSTS
