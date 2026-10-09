import json
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from ai.llm.base import LLMError, LLMResult, Tier, ValidatingClient
from ai.llm.cost import CostTracker

FakeResponse = str | LLMResult | Callable[[str, str], str]


def recommendation_response(system: str, user: str) -> str:
    payload, _ = json.JSONDecoder().raw_decode(user)
    selected = payload["selected_set"]
    return json.dumps(
        {
            "selected_set": selected,
            "text": f"규칙에 따라 {selected}가 선택됐습니다. 인프라 계약은 C의 확인이 필요합니다.",
        },
        ensure_ascii=False,
    )


@dataclass(frozen=True)
class RecordedCall:
    system: str
    user: str
    tier: Tier
    stage: str


class FakeLLMClient(ValidatingClient):
    def __init__(
        self,
        responses: Sequence[FakeResponse] | Mapping[str, Sequence[FakeResponse]],
        *,
        tracker: CostTracker | None = None,
        schema_retries: int = 2,
    ) -> None:
        super().__init__(tracker=tracker, schema_retries=schema_retries)
        self.by_stage = (
            {key: deque(values) for key, values in responses.items()}
            if isinstance(responses, Mapping)
            else None
        )
        self.responses = deque(responses) if self.by_stage is None else deque()
        self.calls: list[RecordedCall] = []

    def _invoke(self, system: str, user: str, *, tier: Tier, stage: str) -> LLMResult:
        self.calls.append(RecordedCall(system, user, tier, stage))
        queue = self.by_stage.get(stage) if self.by_stage is not None else self.responses
        if not queue:
            raise LLMError("Fake LLM 사전 응답이 부족합니다.")
        response = queue.popleft()
        if callable(response):
            response = response(system, user)
        if isinstance(response, LLMResult):
            return response.model_copy(deep=True)
        return LLMResult(text=response, input_tokens=0, output_tokens=0, model_id=f"fake-{tier}")
