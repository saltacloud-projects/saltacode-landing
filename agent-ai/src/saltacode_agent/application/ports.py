"""Ports that keep providers, retrieval, tools, and transport replaceable."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from saltacode_agent.domain.contracts import (
    ExecutionRequest,
    ExecutionResponse,
    ReadinessCheck,
    ToolInvocation,
    ToolResult,
)
from saltacode_agent.domain.prompt import PromptSection


@dataclass(frozen=True, slots=True)
class KnowledgeItem:
    key: str
    content: str
    score: float


@dataclass(frozen=True, slots=True)
class ModelRequest:
    prompt: str
    user_input: str


@dataclass(frozen=True, slots=True)
class ModelReply:
    output: str
    tool_invocations: tuple[ToolInvocation, ...] = ()


class ModelProvider(Protocol):
    async def generate(self, request: ModelRequest) -> ModelReply: ...


class KnowledgeRetriever(Protocol):
    async def retrieve(self, query: str, *, limit: int) -> Sequence[KnowledgeItem]: ...


class ToolExecutor(Protocol):
    async def invoke(self, invocation: ToolInvocation) -> ToolResult: ...


class PromptComposer(Protocol):
    def compose(self, sections: Sequence[PromptSection]) -> str: ...


class AgentRuntime(Protocol):
    async def execute(self, request: ExecutionRequest) -> ExecutionResponse: ...


class ReadinessProbe(Protocol):
    async def check(self) -> Sequence[ReadinessCheck]: ...
