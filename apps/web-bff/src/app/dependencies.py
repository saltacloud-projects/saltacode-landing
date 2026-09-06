from fastapi import Request

from app.chat_v2.ports import WebChatV2Client
from app.config import Settings
from app.ports import AgentGateway, RateLimiter
from app.session import SignedSessionManager


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_rate_limiter(request: Request) -> RateLimiter:
    return request.app.state.rate_limiter


def get_agent_gateway(request: Request) -> AgentGateway:
    return request.app.state.agent_gateway


def get_session_manager(request: Request) -> SignedSessionManager:
    return request.app.state.session_manager


def get_web_chat_v2_client(request: Request) -> WebChatV2Client:
    return request.app.state.web_chat_v2_client
