import argparse
import json
import sys
from pathlib import Path

from ai.gate.runner import DockerCliRunner, FakeRunner
from ai.llm import BedrockClient, FakeLLMClient
from ai.llm.fake import recommendation_response
from ai.llm.recording import DEFAULT_FIXTURES, PlaybackError, RecordingClient, ReplayClient
from ai.pipeline import run_analysis


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Team Bronze AI CLI: P5 추천·샘플 검증·재시도")
    commands = parser.add_subparsers(dest="command", required=True)
    analyze = commands.add_parser("analyze", help="로컬 레포 분석")
    analyze.add_argument("repo_path")
    analyze.add_argument("--env", choices=("aws", "onprem"), default="aws")
    analyze.add_argument("--out", default="out")
    analyze.add_argument(
        "--save-llm-trace",
        action="store_true",
        help="out에 마스킹된 프롬프트·응답·파싱·규칙 비교를 추가 저장",
    )
    analyze.add_argument(
        "--llm",
        choices=("none", "fake", "bedrock", "record", "replay"),
        default="none",
        help="none: 규칙/템플릿만, fake: 오프라인 응답, bedrock: 유료 실제 호출",
    )
    analyze.add_argument(
        "--artifact-llm",
        choices=("none", "fake", "bedrock"),
        default="none",
        help="Dockerfile/명세 제안에 쓸 LLM. bedrock은 추가 유료 호출",
    )
    analyze.add_argument("--source-repo", default=None)
    analyze.add_argument("--app-name", default=None, help="A가 확정한 앱 이름 (3~31자 DNS 라벨)")
    analyze.add_argument(
        "--max-request-seconds", type=int, default=10, help="사용자/A의 요청 시간 후보; 실측값 아님"
    )
    analyze.add_argument("--llm-fixtures", default=str(DEFAULT_FIXTURES))
    analyze.add_argument("--use-demo-cache", action="store_true")
    analyze.add_argument("--demo-cache-dir", default=None)
    analyze.add_argument("--commit", default=None)
    analyze.add_argument("--profile", choices=("dev", "prod"), default="dev")
    analyze.add_argument(
        "--gate",
        choices=("none", "fake", "docker"),
        default="none",
        help="none: 실행 생략, fake: 순서 검사, docker: 자체 샘플 실제 실행",
    )
    analyze.add_argument(
        "--no-gate", action="store_true", help="게이트 실행 생략 (--gate보다 우선)"
    )
    analyze.add_argument("--no-compare", action="store_true", help="원본 복사본 비교 실행 생략")
    analyze.add_argument(
        "--image-tag", default=None, help="A가 확정한 외부 이미지 식별자 (내용에 주입하지 않음)"
    )
    analyze.add_argument(
        "--tfvars-json", default=None, help="임시 변수 입력 JSON 파일; 범위 오류는 기본값 대체"
    )
    args = parser.parse_args(argv)
    result = None
    try:
        llm = (
            BedrockClient()
            if args.llm == "bedrock"
            else FakeLLMClient(
                {
                    "diagnose": ['{"explanations":[],"candidates":[]}'],
                    "recommend": [recommendation_response],
                }
            )
            if args.llm == "fake"
            else None
        )
        if args.llm == "record":
            llm = RecordingClient(BedrockClient(), args.repo_path, Path(args.llm_fixtures))
        elif args.llm == "replay":
            llm = ReplayClient(args.repo_path, Path(args.llm_fixtures))
        if args.llm in {"record", "replay"} and args.artifact_llm != "none":
            raise ValueError(
                "record/replay의 패키징은 고정 템플릿입니다. artifact-llm은 none으로 두세요."
            )
        artifact_llm = (
            llm
            if args.artifact_llm == "bedrock" and args.llm == "bedrock"
            else BedrockClient()
            if args.artifact_llm == "bedrock"
            else FakeLLMClient({"dockerfile": ["{}"], "spec": ["{}"]})
            if args.artifact_llm == "fake"
            else None
        )
        overrides = json.loads(Path(args.tfvars_json).read_text()) if args.tfvars_json else None
        if overrides is not None and not isinstance(overrides, dict):
            raise ValueError("tfvars JSON은 객체여야 합니다.")
        result = run_analysis(
            args.repo_path,
            target_env=args.env,
            out_dir=args.out,
            llm=llm,
            runner=DockerCliRunner()
            if args.gate == "docker"
            else FakeRunner()
            if args.gate == "fake"
            else None,
            artifact_llm=artifact_llm,
            decision_llm=llm,
            repair_llm=llm,
            image_reference=args.image_tag,
            tfvars_overrides=overrides,
            no_gate=args.no_gate,
            compare_original=not args.no_compare,
            source_repo=args.source_repo,
            app_name=args.app_name,
            max_request_seconds=args.max_request_seconds,
            commit=args.commit,
            profile=args.profile,
            save_llm_trace=args.save_llm_trace,
            use_demo_cache=args.use_demo_cache,
            demo_cache_dir=args.demo_cache_dir,
        )
        if isinstance(llm, ReplayClient) and result.execution_source != "demo_cache":
            llm.assert_consumed()
    except (ValueError, OSError, PlaybackError) as error:
        print(f"[실패] {error}", file=sys.stderr)
        return 2
    finally:
        if result is not None and result.build_context is not None:
            result.build_context.cleanup()
    return (
        1
        if result.status in {"failed", "unsupported"}
        or result.diagnosis.enrichment_status == "failed"
        else 0
    )
