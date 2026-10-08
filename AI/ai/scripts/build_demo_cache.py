"""Opt-in paid Bedrock + real Docker capture on owned samples only."""

import argparse
from pathlib import Path

from ai.demo_cache import DEFAULT_CACHE, save_cache, settings_key
from ai.gate.runner import DockerCliRunner
from ai.llm import BedrockClient
from ai.llm.recording import DEFAULT_FIXTURES, RecordingClient
from ai.pipeline import run_analysis
from ai.stages import default_log


def main() -> int:
    parser = argparse.ArgumentParser(description="실제 Bedrock/Docker 사전 실행; 추론 요금 발생")
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--fixtures", type=Path, default=DEFAULT_FIXTURES)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    for name in ("todo", "todo-scheduler"):
        events = []

        def log(stage, message, captured=events):
            captured.append({"stage": stage.value, "message": message})
            default_log(stage, message)

        repo = root / "samples" / name
        client = RecordingClient(BedrockClient(), repo, args.fixtures)
        result = run_analysis(
            repo,
            out_dir=root / "out/demo-cache-build" / name,
            source_repo=f"sample://{name}",
            llm=client,
            decision_llm=client,
            repair_llm=client,
            runner=DockerCliRunner(),
            log=log,
            save_llm_trace=True,
        )
        try:
            save_cache(repo, result, events, root=args.cache_dir, settings=settings_key(name))
            print(f"{name}: 실제 사전 실행 결과 저장 완료")
        finally:
            if result.build_context is not None:
                result.build_context.cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
