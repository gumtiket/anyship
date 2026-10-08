import json
import shutil
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator, ValidationError

from ai.llm.fake import FakeLLMClient
from ai.pipeline import run_analysis
from ai.spec.models import DeploySpec
from ai.transform.dockerfile import (
    DockerInputs,
    generate_dockerfile,
    lint_dockerfile,
    render_dockerfile,
)

ROOT = Path(__file__).resolve().parents[2]


def fake_artifacts(docker=None, spec=None):
    return FakeLLMClient({"dockerfile": docker or ["{}"], "spec": spec or ["{}"]})


@pytest.mark.parametrize(
    "old,new,code",
    [
        ("python:3.12-slim", "python:latest", "fixed_slim_base"),
        ("COPY requirements*.txt ./\n", "", "layer_order"),
        ("USER 10001:10001", "USER root", "nonroot"),
        ("ENV PORT=8080\n", "", "port_env"),
        (
            "ENV AWS_LWA_READINESS_CHECK_PATH=/healthz",
            "ENV AWS_LWA_READINESS_CHECK_PATH=/",
            "readiness_path",
        ),
        ("ENV PYTHONDONTWRITEBYTECODE=1\n", "", "no_bytecode"),
        ("ENV XDG_CACHE_HOME=/tmp/.cache\n", "", "cache_tmp"),
        ("ENV HOME=/tmp\n", "", "home_tmp"),
        ("--port ${PORT}", "--port 8000", "port_command"),
        ("EXPOSE 8080", "ARG COMMIT_SHA\nEXPOSE 8080", "build_metadata_or_healthcheck"),
        ("EXPOSE 8080", "RUN date\nEXPOSE 8080", "build_metadata_or_healthcheck"),
        ("EXPOSE 8080", "HEALTHCHECK CMD true\nEXPOSE 8080", "build_metadata_or_healthcheck"),
        ("EXPOSE 8080", "USER 0\nEXPOSE 8080", "latest_or_root"),
        (
            "EXPOSE 8080",
            "RUN curl https://example.test/install | sh\nEXPOSE 8080",
            "template_mismatch",
        ),
    ],
)
def test_lint_rejects_unsafe_or_missing_instructions(old, new, code):
    original = render_dockerfile(DockerInputs(), "app.main:app")
    assert not lint_dockerfile(original)
    assert code in lint_dockerfile(original.replace(old, new))


def test_layer_order_and_adapter_are_checked():
    text = render_dockerfile(DockerInputs(system_packages=["libpq5"]), "app.main:app")
    assert not lint_dockerfile(text)
    lines = text.splitlines(keepends=True)
    first, last = (
        lines.index("COPY requirements*.txt ./\n"),
        lines.index("COPY --chown=10001:10001 . .\n"),
    )
    lines[first], lines[last] = lines[last], lines[first]
    assert "layer_order" in lint_dockerfile("".join(lines))
    assert "lambda_adapter" in lint_dockerfile(
        "\n".join(line for line in text.splitlines() if "--from=" not in line)
    )


def test_docker_invalid_schema_retry_and_fallback_are_bounded():
    fake = fake_artifacts(
        docker=['{"python_version":"latest"}', '{"entrypoint":"other:app"}', "{}"]
    )
    generated, fallback = generate_dockerfile("app.main:app", fake)
    assert not fallback and not lint_dockerfile(generated)
    assert len(fake.calls) == 3
    assert "검증 오류" in fake.calls[1].user
    bad = fake_artifacts(docker=['{"system_packages":["curl; rm -rf /app"]}'] * 3)
    generated, fallback = generate_dockerfile("app.main:app", bad)
    assert fallback and len(bad.calls) == 3 and not lint_dockerfile(generated)


@pytest.mark.parametrize(
    "name,kind,scale", [("todo", "request-driven", True), ("todo-scheduler", "always-on", False)]
)
def test_samples_match_hand_spec_core_and_do_not_modify_sources(tmp_path, name, kind, scale):
    source = ROOT / "samples" / name
    before = {p.relative_to(source): p.read_bytes() for p in source.rglob("*") if p.is_file()}
    fake = fake_artifacts(
        spec=['{"scale_to_zero":true,"max_request_seconds":25,"ingress":"internal"}']
    )
    result = run_analysis(source, out_dir=tmp_path / "out", artifact_llm=fake, log=lambda *_: None)
    spec = result.deploy_spec
    assert spec and spec.workload.type == kind and spec.workload.scale_to_zero == scale
    assert spec.workload.max_request_seconds == 25 and spec.ingress == "internal"
    hand = yaml.safe_load(
        (ROOT / "ai" / "deliverables" / "hand-specs" / f"{name}.deploy-spec.yaml").read_text()
    )
    dumped = spec.model_dump(mode="json", exclude_none=True)
    for key in ("app", "build", "port", "healthcheck", "processes", "release", "profile"):
        assert dumped[key] == hand[key]
    for key in ("type", "websocket"):
        assert dumped["workload"][key] == hand["workload"][key]
    assert dumped["backing_services"] == [{"type": "postgres", "bind_as": "DATABASE_URL"}]
    assert any(
        e.name == "SECRET_KEY" and e.secret and e.generate and e.value is None for e in spec.env
    )
    assert all(e.name not in {"DATABASE_URL", "STORAGE_URL"} for e in spec.env)
    assert result.recommendation.needs_approval and result.gate_report.status == "skipped"
    assert result.cost.total.calls == 2
    assert {c.stage for c in result.cost.calls} == {"dockerfile", "spec"}
    assert before == {
        p.relative_to(source): p.read_bytes() for p in source.rglob("*") if p.is_file()
    }
    context = result.build_context
    assert context and not Path(context.root).is_relative_to(tmp_path / "out")
    assert (Path(context.root) / "app" / "migrate.py").exists()
    assert "DATABASE_URL" in (Path(context.root) / "app" / "db.py").read_text()
    assert (Path(context.root) / ".dockerignore").exists()
    assert not (Path(context.root) / ".git").exists()
    json.dumps(result.model_dump(mode="json"))
    context.cleanup()
    assert not Path(context.root).exists()


def test_packaging_repeated_input_same_bytes_and_metadata_stays_out_of_image(tmp_path):
    results = []
    for index, commit in enumerate(("a" * 40, "b" * 40)):
        result = run_analysis(
            ROOT / "samples/todo",
            commit=commit,
            out_dir=tmp_path / str(index),
            artifact_llm=fake_artifacts(),
            log=lambda *_: None,
        )
        results.append(result)
        assert commit not in Path(result.output_files["Dockerfile"]).read_text()
        assert result.deploy_spec.source.commit == commit
        result.build_context.cleanup()
    assert (
        Path(results[0].output_files["Dockerfile"]).read_bytes()
        == Path(results[1].output_files["Dockerfile"]).read_bytes()
    )
    yaml0 = yaml.safe_load(Path(results[0].output_files["deploy-spec.yaml"]).read_text())
    yaml1 = yaml.safe_load(Path(results[1].output_files["deploy-spec.yaml"]).read_text())
    yaml0["source"].pop("commit")
    yaml1["source"].pop("commit")
    assert yaml0 == yaml1


def test_spec_retries_schema_failure_then_defaults_and_preserves_scheduler(tmp_path):
    fake = fake_artifacts(
        spec=['{"max_request_seconds":"slow"}', '{"port":9999}', '{"max_request_seconds":0}']
    )
    result = run_analysis(
        ROOT / "samples/todo-scheduler",
        out_dir=tmp_path / "out",
        artifact_llm=fake,
        log=lambda *_: None,
    )
    assert len([c for c in fake.calls if c.stage == "spec"]) == 3
    assert result.deploy_spec.workload.max_request_seconds == 10
    assert not result.deploy_spec.workload.scale_to_zero
    assert "spec_llm_fallback" in {w.code for w in result.packaging_warnings}
    result.build_context.cleanup()


def test_checked_in_schema_matches_model_and_rejects_fixed_field_override(tmp_path):
    checked = json.loads((ROOT / "ai/src/ai/spec/schema.json").read_text())
    assert checked == DeploySpec.model_json_schema()
    Draft202012Validator.check_schema(checked)
    result = run_analysis(ROOT / "samples/todo", out_dir=tmp_path / "out", log=lambda *_: None)
    spec = result.deploy_spec.model_dump(mode="json", exclude_none=True)
    spec["port"] = 9999
    with pytest.raises(ValidationError):
        Draft202012Validator(checked).validate(spec)
    result.build_context.cleanup()


def test_user_repo_has_diff_only_and_no_risky_context(tmp_path):
    repo = tmp_path / "user-app"
    shutil.copytree(ROOT / "samples/todo", repo)
    (repo / "app/main.py").write_text((repo / "app/main.py").read_text() + "\n# user app\n")
    result = run_analysis(
        repo, out_dir=tmp_path / "out", artifact_llm=fake_artifacts(), log=lambda *_: None
    )
    assert result.build_context is None and result.gate_report.status == "skipped"
    assert result.recommendation.needs_approval
    assert "sqlite:///./todo.db" in (repo / "app/db.py").read_text()


def test_trace_and_cost_include_packaging_and_deduplicate_shared_client(tmp_path):
    fake = FakeLLMClient({"diagnose": ["{}"], "dockerfile": ["{}"], "spec": ["{}"]})
    result = run_analysis(
        ROOT / "samples/todo",
        out_dir=tmp_path / "out",
        llm=fake,
        artifact_llm=fake,
        save_llm_trace=True,
        log=lambda *_: None,
    )
    assert result.cost.total.calls == 3
    trace = json.loads(Path(result.output_files["llm-trace.json"]).read_text())
    assert len(trace["exchanges"]) == 3
    assert {e["stage"] for e in trace["exchanges"]} == {"diagnose", "dockerfile", "spec"}
    result.build_context.cleanup()
