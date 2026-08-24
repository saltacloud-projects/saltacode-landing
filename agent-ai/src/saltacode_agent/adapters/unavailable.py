"""Fail-closed seed adapter used until approved integrations are wired."""

from saltacode_agent.application.errors import RuntimeUnavailableError
from saltacode_agent.application.ports import AgentRuntime, ReadinessProbe
from saltacode_agent.domain.contracts import ExecutionRequest, ExecutionResponse, ReadinessCheck


class UnavailableAgentRuntime(AgentRuntime, ReadinessProbe):
    async def execute(self, request: ExecutionRequest) -> ExecutionResponse:
        del request
        raise RuntimeUnavailableError("agent runtime is not configured")

    async def check(self) -> tuple[ReadinessCheck, ...]:
        return (
            ReadinessCheck(
                name="agent_runtime",
                ready=False,
                detail="provider, knowledge, and tool adapters are not configured",
            ),
        )
