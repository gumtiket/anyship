"""B-side handoff example. No HTTP server, repository fetch, PR, or deployment.

The envelope below is a proposal for A; it does not replace AIProvider's current
analyze/modify contract. Keep safety and provenance alongside display fields.
"""

import argparse
import json
import re
import sys
from pathlib import Path

from ai.llm import BedrockClient, FakeLLMClient
from ai.llm.fake import recommendation_response
from ai.models import AnalysisResult
from ai.pipeline import run_analysis
from ai.stages import LogFn, Stage


def service_payload(
    result: AnalysisResult, base_sha: str, *, llm_mode: str = "not_provided"
) -> dict:
    """Serializable display envelope, excluding private paths and runtime logs.

    SHA syntax is checked here; A must bind the provided code to the actual SHA.
    Findings are diagnostic items, not individually applicable patch hunks.
    """
    if not re.fullmatch(r"[0-9a-fA-F]{7,40}", base_sha):
        raise ValueError("invalid_base_sha")
    if llm_mode not in {"not_provided", "none", "fake", "bedrock", "replay", "cache"}:
        raise ValueError("invalid_mode")
    gate = result.gate_report
    return {
        "contract_status": "proposal_needs_A_confirmation",
        "llm_mode": llm_mode,
        "base_sha": base_sha,
        "analysis_status": result.status,
        "diagnosis": result.diagnosis.model_dump(mode="json"),
        "transformation": result.transformation.model_dump(mode="json"),
        "recommendation": result.recommendation.model_dump(mode="json"),
        "packaging_warnings": [w.model_dump(mode="json") for w in result.packaging_warnings],
        "gate": {
            "status": gate.status,
            "reason": gate.reason,
            "pr_eligible": gate.pr_eligible,
            "scope": gate.scope,
            "execution_source": gate.execution_source,
            "historical_status": gate.historical_status,
            "attempts": [
                {
                    "number": a.number,
                    "status": a.status,
                    "reason": a.reason,
                    "repair_status": a.repair_status,
                }
                for a in gate.attempts
            ],
            "retry_stop_reason": gate.retry_stop_reason,
        },
        "cost": result.cost.model_dump(mode="json"),
        "execution_source": result.execution_source,
        "timings_s": result.timings_s,
        "integration": {
            "selection_mapping": "not_implemented",
            "publication": "not_implemented",
            "deployment": "not_implemented",
        },
    }


def run_handoff(
    repo_path: str | Path,
    out_dir: str | Path,
    *,
    base_sha: str,
    mode: str = "fake",
    log: LogFn = lambda *_: None,
) -> dict:
    """Run a new request without containers; never automatically falls back.

    Credentials come from the process's AWS credential provider. No GitHub
    token, cloud key, service DB, or user secret is accepted as an argument.
    """
    if not re.fullmatch(r"[0-9a-fA-F]{7,40}", base_sha):
        raise ValueError("invalid_base_sha")
    if mode not in {"none", "fake", "bedrock"}:
        raise ValueError("invalid_mode")
    client = (
        BedrockClient()
        if mode == "bedrock"
        else FakeLLMClient(
            {
                "diagnose": ['{"explanations":[],"candidates":[]}'],
                "recommend": [recommendation_response],
                "transform": ['{"diff":"","violation_ids":[]}'],
            }
        )
        if mode == "fake"
        else None
    )
    result = run_analysis(
        repo_path,
        out_dir=out_dir,
        commit=base_sha,
        llm=client,
        decision_llm=client,
        log=log,
        no_gate=True,
    )
    try:
        return service_payload(result, base_sha, llm_mode=mode)
    finally:
        if result.build_context is not None:
            result.build_context.cleanup()


def main() -> int:
    parser = argparse.ArgumentParser(description="B 결과 전달 예제; 웹 제공자/PR/배포 연결은 별도")
    parser.add_argument("repo", type=Path)
    parser.add_argument("--out", required=True, type=Path, help="입력과 분리된 새 폴더")
    parser.add_argument("--base-sha", required=True, help="A가 제공한 코드의 기준 SHA")
    parser.add_argument("--mode", choices=("none", "fake", "bedrock"), default="fake")
    args = parser.parse_args()

    def log(stage: Stage, message: str) -> None:
        print(f"[{stage.value}] {message}", file=sys.stderr)

    payload = run_handoff(args.repo, args.out, base_sha=args.base_sha, mode=args.mode, log=log)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    # CLI success means display data was produced, not PR/deployment approval.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
