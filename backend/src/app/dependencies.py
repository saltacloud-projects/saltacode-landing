from fastapi import Request

from app.config import Settings
from app.gateway import AgentGateway
from app.rate_limit import RateLimiter


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_rate_limiter(request: Request) -> RateLimiter:
    return request.app.state.rate_limiter


def get_agent_gateway(request: Request) -> AgentGateway:
    return request.app.state.agent_gateway
