"""Bounded Agno adapter; persistence, access and budget belong to the supervisor."""

from dataclasses import dataclass
from typing import Any, Protocol

from agno.agent import Agent

from ares.agents.catalog import COMMERCIAL_AGENTS, AgentDefinition
from ares.agents.commercial_contracts import commercial_fallback
from ares.agents.contracts import AnalysisInput, AnalysisOutput
from ares.agents.specialists import (
    SpecialistInput,
    specialist_fallback,
)
from ares.ai.models import response_model
from ares.ai.usage import UsageObservation, observe


@dataclass(frozen=True)
class AgentOutcome:
    output: Any
    usage: UsageObservation
    degraded: bool = False


class AgentExecutor(Protocol):
    async def execute(
        self, definition: AgentDefinition, payload: AnalysisInput | SpecialistInput, model_id: str
    ) -> AgentOutcome: ...


class AgnoExecutor:
    def __init__(self, api_key: str) -> None:
        self._api_key = api_key

    async def execute(
        self, definition: AgentDefinition, payload: AnalysisInput | SpecialistInput, model_id: str
    ) -> AgentOutcome:
        if not self._api_key:
            if definition.agent_id == "outcome-evaluator" and isinstance(payload, SpecialistInput):
                from ares.impact.evaluation import fallback

                return AgentOutcome(
                    fallback(payload), UsageObservation(status="not_called"), degraded=True
                )
            if definition.agent_id in COMMERCIAL_AGENTS and isinstance(payload, SpecialistInput):
                return AgentOutcome(
                    commercial_fallback(definition.agent_id, payload),
                    UsageObservation(status="not_called"),
                    degraded=True,
                )
            if isinstance(payload, SpecialistInput):
                return AgentOutcome(
                    specialist_fallback(
                        payload,
                        diagnosis=definition.agent_id
                        in {"opportunity-diagnosis", "sentinel-interpreter"},
                    ),
                    UsageObservation(status="not_called"),
                    degraded=True,
                )
            return AgentOutcome(
                AnalysisOutput(
                    summary="Contexto registrado; a interpretação por IA está indisponível.",
                    evidence_refs=payload.evidence_refs,
                    limitations=["Modelo não configurado. Revisão humana necessária."],
                    needs_human_review=True,
                ),
                UsageObservation(status="not_called"),
                degraded=True,
            )
        agent = Agent(
            name=definition.agent_id,
            model=response_model(model_id, self._api_key),
            instructions=definition.instructions,
            input_schema=definition.input_schema,
            output_schema=definition.output_schema,
            tools=[],
            tool_call_limit=0,
            search_knowledge=False,
            add_memories_to_context=False,
            add_learnings_to_context=False,
            retries=0,
            telemetry=False,
        )
        response = await agent.arun(payload)
        # Record measured usage even when output validation fails downstream.
        output = response.content
        usage = observe(response.metrics, model_id)
        try:
            validated = definition.output_schema.model_validate(output)
        except ValueError as error:
            raise InvalidAgentOutput(usage) from error
        return AgentOutcome(validated, usage)


class InvalidAgentOutput(Exception):
    def __init__(self, usage: UsageObservation) -> None:
        super().__init__("agent_output_invalid")
        self.usage = usage
