import json
from collections import defaultdict
from pathlib import Path

from pydantic import Field

from ai.models import CallCost, CostReport, CostSummary, OutputModel


class ModelPricing(OutputModel):
    input_usd_per_million: float | None = Field(default=None, ge=0)
    output_usd_per_million: float | None = Field(default=None, ge=0)


class CostTracker:
    def __init__(self, prices: dict[str, ModelPricing] | None = None) -> None:
        self.prices = prices or {}
        self.calls: list[CallCost] = []
        self.unobserved_stages: list[str] = []

    def record_unobserved(self, stage: str) -> None:
        """An attempted request failed before validated usage was available."""
        self.unobserved_stages.append(stage)

    @classmethod
    def from_file(cls, path: str | Path) -> "CostTracker":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(
            {
                key: ModelPricing.model_validate(value)
                for key, value in data.get("models", {}).items()
            }
        )

    def record(
        self,
        *,
        stage: str,
        model_id: str,
        input_tokens: int,
        output_tokens: int,
        latency_s: float = 0,
    ) -> CallCost:
        # Validate token counts before computing a price.
        call = CallCost(
            stage=stage,
            model_id=model_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_s=latency_s,
        )
        price = self.prices.get(model_id)
        if (
            price is not None
            and price.input_usd_per_million is not None
            and price.output_usd_per_million is not None
        ):
            call.cost_usd = (
                input_tokens * price.input_usd_per_million
                + output_tokens * price.output_usd_per_million
            ) / 1_000_000
        self.calls.append(call)
        return call

    @staticmethod
    def _summary(calls: list[CallCost], unobserved_requests: int = 0) -> CostSummary:
        known = sum(call.cost_usd for call in calls if call.cost_usd is not None)
        complete = all(call.cost_usd is not None for call in calls)
        return CostSummary(
            calls=len(calls),
            input_tokens=sum(c.input_tokens for c in calls),
            output_tokens=sum(c.output_tokens for c in calls),
            known_cost_usd=known,
            cost_usd=known if complete and not unobserved_requests else None,
            pricing_complete=complete,
            unobserved_requests=unobserved_requests,
            usage_complete=not unobserved_requests,
        )

    def report(self) -> CostReport:
        groups: dict[str, list[CallCost]] = defaultdict(list)
        for call in self.calls:
            groups[call.stage].append(call)
        for stage in self.unobserved_stages:
            groups.setdefault(stage, [])
        return CostReport(
            calls=[call.model_copy() for call in self.calls],
            stages={
                stage: self._summary(calls, self.unobserved_stages.count(stage))
                for stage, calls in sorted(groups.items())
            },
            total=self._summary(self.calls, len(self.unobserved_stages)),
        )

    def save(self, path: str | Path) -> None:
        Path(path).write_text(
            json.dumps(self.report().model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
