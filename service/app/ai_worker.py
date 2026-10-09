"""Credential-free, bounded subprocess for the development fake AI provider."""
import json
import sys
from pathlib import Path

from anyship_adapters.redact import redact_json, redact_text

from .ai_snapshot import git_blob_sha, safe_path


def analyze(request):
    # Lazy imports keep unavailable/placeholder installations independent of AI startup.
    from ai import run_analysis
    from ai.detectors.repo import RepoView
    from ai.llm.fake import FakeLLMClient, recommendation_response
    from ai.security import SourceMasker
    from ai.transform.workspace import Workspace, patch_paths

    root = Path(request["source"])
    manifest = request["manifest"]

    def check_source():
        actual = {p.relative_to(root).as_posix(): git_blob_sha(p.read_bytes()) for p in root.rglob("*") if p.is_file()}
        if actual != manifest:
            raise ValueError("source_changed")

    check_source()
    client = FakeLLMClient({
        "diagnose": ['{"explanations":[],"candidates":[]}'],
        "recommend": [recommendation_response],
        "transform": ['{"diff":"","violation_ids":[]}'],
    })
    result = run_analysis(root, out_dir=request["output"], commit=request["base_sha"],
        source_repo="https://github.com/" + request["repository"], app_name=request["app_name"],
        llm=client, decision_llm=client, no_gate=True, log=lambda *_: None)
    try:
        check_source()
        diff = Path(result.output_files["changes.diff"]).read_bytes().decode("utf-8")
        if len(diff.encode("utf-8")) > 1024 * 1024:
            raise ValueError("patch_size_limit")
        files = {name: (root / name).read_bytes().decode("utf-8") for name in manifest}
        paths = patch_paths(diff, set(files) | {".dockerignore", "app/migrate.py"}) if diff else set()
        for name in paths:
            safe_path(name)
        # Validate the final diff, including packaging changes, against the exact snapshot.
        if diff:
            with Workspace(files) as workspace:
                workspace.apply(diff)
                if not workspace.compile():
                    raise ValueError("patch_compile_failed")
        masker = SourceMasker(RepoView(root))
        if masker.contains_sensitive(diff) or redact_text(diff) != diff:
            raise ValueError("sensitive_patch")
        gate = result.gate_report
        result.cost.external_calls = 0  # This worker can only construct FakeLLMClient.
        payload = {
            "contract_status": "service_fake_bundle_v1",
            "llm_mode": "fake", "base_sha": request["base_sha"],
            "analysis_status": result.status,
            "diagnosis": result.diagnosis.model_dump(mode="json"),
            "transformation": result.transformation.model_dump(mode="json"),
            "recommendation": result.recommendation.model_dump(mode="json"),
            "packaging_warnings": [w.model_dump(mode="json") for w in result.packaging_warnings],
            "gate": {"status": gate.status, "reason": gate.reason, "pr_eligible": gate.pr_eligible,
                "scope": gate.scope, "execution_source": gate.execution_source,
                "historical_status": gate.historical_status, "retry_stop_reason": gate.retry_stop_reason},
            "cost": result.cost.model_dump(mode="json"), "execution_source": result.execution_source,
            "timings_s": result.timings_s,
            "artifacts": {
                "Dockerfile": Path(result.output_files["Dockerfile"]).read_text(encoding="utf-8"),
                "deploy-spec.yaml": Path(result.output_files["deploy-spec.yaml"]).read_text(encoding="utf-8"),
            },
            "bundle": {"id": "all-changes", "paths": sorted(paths), "patch_valid": bool(diff)},
            "integration": {"selection_mapping": "whole_bundle", "publication": "disabled", "deployment": "disabled"},
        }
        if gate.status != "skipped" or gate.pr_eligible:
            raise ValueError("unexpected_gate")
        # Known source secrets are removed from display metadata as well as model inputs.
        payload = json.loads(masker.text(json.dumps(payload, ensure_ascii=False)))
        return {"result": redact_json(payload), "diff": diff}
    finally:
        if result.build_context is not None:
            result.build_context.cleanup()


def main():
    request = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    try:
        payload = analyze(request)
    except Exception:
        # Never copy source, local paths, credential-bearing exceptions, or raw logs.
        payload = {"error": "ai_analysis_failed"}
    Path(sys.argv[2]).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
