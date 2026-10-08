import json

import pytest

from ai.llm import CostTracker, ModelPricing


def test_stage_totals_include_known_and_unknown_prices(tmp_path):
    tracker = CostTracker(
        {"dummy-priced": ModelPricing(input_usd_per_million=2, output_usd_per_million=4)}
    )
    tracker.record(stage="diagnose", model_id="dummy-priced", input_tokens=1000, output_tokens=500)
    tracker.record(stage="diagnose", model_id="dummy-unknown", input_tokens=20, output_tokens=10)
    tracker.record(stage="transform", model_id="dummy-priced", input_tokens=500, output_tokens=250)
    report = tracker.report()
    assert report.total.input_tokens == 1520
    assert report.total.output_tokens == 760
    assert report.total.known_cost_usd == pytest.approx(0.006)
    assert report.total.cost_usd is None
    assert not report.total.pricing_complete
    assert report.stages["diagnose"].cost_usd is None
    assert report.stages["transform"].cost_usd == pytest.approx(0.002)
    path = tmp_path / "cost.json"
    tracker.save(path)
    assert json.loads(path.read_text())["total"]["cost_usd"] is None


def test_all_known_total():
    tracker = CostTracker(
        {"dummy": ModelPricing(input_usd_per_million=1, output_usd_per_million=2)}
    )
    tracker.record(stage="check", model_id="dummy", input_tokens=1_000_000, output_tokens=500_000)
    assert tracker.report().total.cost_usd == 2


@pytest.mark.parametrize(
    "prices",
    [
        None,
        {"input_usd_per_million": None, "output_usd_per_million": None},
        {"input_usd_per_million": 1, "output_usd_per_million": None},
    ],
)
def test_null_or_missing_price_preserves_tokens(tmp_path, prices):
    path = tmp_path / "pricing.json"
    path.write_text(json.dumps({"models": {"dummy": prices} if prices is not None else {}}))
    tracker = CostTracker.from_file(path)
    tracker.record(stage="check", model_id="dummy", input_tokens=100, output_tokens=50)
    assert tracker.report().total.input_tokens == 100
    assert tracker.report().total.cost_usd is None


def test_report_is_snapshot():
    tracker = CostTracker()
    tracker.record(stage="check", model_id="dummy", input_tokens=1, output_tokens=2)
    snapshot = tracker.report()
    snapshot.calls[0].input_tokens = 999
    assert tracker.report().total.input_tokens == 1


def test_request_without_usage_preserves_unknown_cost_and_known_token_subtotal():
    tracker = CostTracker(
        {"dummy": ModelPricing(input_usd_per_million=1, output_usd_per_million=2)}
    )
    tracker.record(stage="diagnose", model_id="dummy", input_tokens=100, output_tokens=50)
    tracker.record_unobserved("diagnose")
    tracker.record_unobserved("transform")
    report = tracker.report()
    assert report.total.input_tokens == 100
    assert report.total.known_cost_usd == pytest.approx(0.0002)
    assert report.total.cost_usd is None and not report.total.usage_complete
    assert report.total.unobserved_requests == 2
    assert report.stages["transform"].calls == 0
    assert report.stages["transform"].cost_usd is None
