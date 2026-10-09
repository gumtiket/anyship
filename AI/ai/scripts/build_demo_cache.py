"""Opt-in paid Bedrock + real Docker capture on owned samples only."""

import argparse
from pathlib import Path
from tempfile import mkdtemp

from ai.demo_cache import DEFAULT_CACHE, save_cache, settings_key
from ai.gate.runner import DockerCliRunner
from ai.llm import BedrockClient, LLMResult
from ai.llm.recording import DEFAULT_FIXTURES, RecordingClient, ReplayClient
from ai.pipeline import run_analysis
from ai.stages import default_log


def main() -> int:
    parser = argparse.ArgumentParser(description="실제 Bedrock/Docker 사전 실행; 추론 요금 발생")
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES)
    parser.add_argument(
        "--llm",
        choices=("bedrock", "replay"),
        default="bedrock",
        help="replay: 동일 해시의 기존 실제 응답 + 새 Docker 검증. 새 AWS 호출 없음",
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    (root / "out").mkdir(exist_ok=True)
    output = Path(mkdtemp(prefix="demo-cache-build-", dir=root / "out"))
    print(f"실행 기록 (LLM={args.llm}): {output}")
    for name in ("todo", "todo-scheduler"):
        events = []

        def log(stage, message, captured=events):
            captured.append({"stage": stage.value, "message": message})
            default_log(stage, message)

        repo = root / "samples" / name
        client = (
            RecordingClient(BedrockClient(), repo, args.fixtures)
            if args.llm == "bedrock"
            else ReplayClient(repo, args.fixtures)
        )
        result = run_analysis(
            repo,
            out_dir=output / name,
            source_repo=f"sample://{name}",
            llm=client,
            decision_llm=client,
            repair_llm=client,
            runner=DockerCliRunner(),
            log=log,
            save_llm_trace=True,
        )
        try:
            usage = None
            if isinstance(client, ReplayClient):
                client.assert_consumed()
                if any(f.origin != "BedrockClient" for f in client.fixtures.values()):
                    raise ValueError("cache_replay_requires_original_bedrock_recordings")
                original = [
                    LLMResult.model_validate(e.response)
                    for f in client.fixtures.values()
                    for e in f.entries
                ]
                usage = {
                    "calls": len(original),
                    "input_tokens": sum(e.input_tokens for e in original),
                    "output_tokens": sum(e.output_tokens for e in original),
                    "cost_usd": sum(e.cost_usd for e in original)
                    if all(e.cost_usd is not None for e in original)
                    else None,
                    "historical": True,
                    "new_external_calls": 0,
                }
            save_cache(
                repo,
                result,
                events,
                root=args.cache_dir,
                settings=settings_key(name),
                allow_replay=args.llm == "replay",
                recorded_llm_usage=usage,
            )
            print(f"{name}: {args.llm} 응답 + 새 Docker 검증 결과 저장 완료")
        finally:
            if result.build_context is not None:
                result.build_context.cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
