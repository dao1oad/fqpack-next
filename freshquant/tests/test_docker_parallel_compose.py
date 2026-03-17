import importlib.util
import sys
from pathlib import Path


def load_module():
    module_path = Path("script/docker_parallel_compose.py")
    spec = importlib.util.spec_from_file_location(
        "docker_parallel_compose", module_path
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_matching_images_force_no_build_on_repeated_up() -> None:
    module = load_module()

    args = ["up", "-d", "--build", "fq_webui", "fq_apiserver"]
    service_images = {
        "fq_webui": "fqnext_webui:2026.2.23",
        "fq_apiserver": "fqnext_rear:2026.2.23",
    }
    image_revisions = {
        "fqnext_webui:2026.2.23": "abc123",
        "fqnext_rear:2026.2.23": "abc123",
    }

    rewritten = module.rewrite_compose_args_for_cached_images(
        args=args,
        all_services=["fq_webui", "fq_apiserver", "fq_dagster_webserver"],
        service_images=service_images,
        image_revisions=image_revisions,
        current_revision="abc123",
    )

    assert rewritten == ["up", "-d", "--no-build", "fq_webui", "fq_apiserver"]


def test_mismatched_or_missing_image_revision_keeps_build_flag() -> None:
    module = load_module()

    args = ["up", "-d", "--build", "fq_webui"]
    service_images = {"fq_webui": "fqnext_webui:2026.2.23"}

    rewritten = module.rewrite_compose_args_for_cached_images(
        args=args,
        all_services=["fq_webui", "fq_apiserver"],
        service_images=service_images,
        image_revisions={"fqnext_webui:2026.2.23": "old-sha"},
        current_revision="new-sha",
    )

    assert rewritten == args


def test_non_build_commands_are_left_unchanged() -> None:
    module = load_module()

    args = ["ps", "fq_webui"]

    rewritten = module.rewrite_compose_args_for_cached_images(
        args=args,
        all_services=["fq_webui"],
        service_images={"fq_webui": "fqnext_webui:2026.2.23"},
        image_revisions={"fqnext_webui:2026.2.23": "abc123"},
        current_revision="abc123",
    )

    assert rewritten == args


def test_matching_images_also_force_no_build_for_plain_up_command() -> None:
    module = load_module()

    args = ["up", "-d", "fq_webui"]

    rewritten = module.rewrite_compose_args_for_cached_images(
        args=args,
        all_services=["fq_webui", "fq_apiserver"],
        service_images={"fq_webui": "fqnext_webui:2026.2.23"},
        image_revisions={"fqnext_webui:2026.2.23": "abc123"},
        current_revision="abc123",
    )

    assert rewritten == ["up", "-d", "--no-build", "fq_webui"]


def test_parser_collects_repeated_compose_args() -> None:
    module = load_module()

    parsed = module.build_parser().parse_args(
        [
            "--compose-arg=up",
            "--compose-arg=-d",
            "--compose-arg=--build",
            "--compose-arg=fq_webui",
        ]
    )

    assert parsed.compose_arg == ["up", "-d", "--build", "fq_webui"]


def test_compute_rewrite_result_prefers_remote_cached_images(monkeypatch) -> None:
    module = load_module()

    monkeypatch.setattr(module, "load_current_revision", lambda _: "abc123")
    monkeypatch.setattr(
        module,
        "load_compose_service_images",
        lambda _: (
            ["fq_webui"],
            {"fq_webui": "fqnext_webui:2026.2.23"},
        ),
    )
    monkeypatch.setattr(
        module,
        "load_local_image_revisions",
        lambda _: {},
    )
    monkeypatch.setattr(
        module,
        "load_remote_image_revisions",
        lambda _: {"ghcr.io/dao1oad/fqnext-webui:abc123": "abc123"},
    )
    monkeypatch.setattr(
        module,
        "build_registry_service_images",
        lambda revision: {"fq_webui": f"ghcr.io/dao1oad/fqnext-webui:{revision}"},
    )
    monkeypatch.setattr(module, "load_dirty_paths", lambda _: [])

    result = module.compute_rewrite_result(
        repo_root=Path("."),
        compose_file=Path("docker/compose.parallel.yaml"),
        compose_args=["up", "-d", "--build", "fq_webui"],
    )

    assert result["skip_build"] is True
    assert result["mode"] == "remote_cached"
    assert result["compose_args"] == ["up", "-d", "--no-build", "fq_webui"]
    assert result["pull_images"] == ["ghcr.io/dao1oad/fqnext-webui:abc123"]
    assert result["image_overrides"] == {
        "FQNEXT_WEBUI_IMAGE": "ghcr.io/dao1oad/fqnext-webui:abc123"
    }


def test_compute_rewrite_result_keeps_build_when_dirty_path_hits_target_context(
    monkeypatch,
) -> None:
    module = load_module()

    monkeypatch.setattr(module, "load_current_revision", lambda _: "abc123")
    monkeypatch.setattr(
        module,
        "load_compose_service_images",
        lambda _: (
            ["fq_webui"],
            {"fq_webui": "fqnext_webui:2026.2.23"},
        ),
    )
    monkeypatch.setattr(
        module,
        "load_local_image_revisions",
        lambda _: {"fqnext_webui:2026.2.23": "abc123"},
    )
    monkeypatch.setattr(module, "load_remote_image_revisions", lambda _: {})
    monkeypatch.setattr(
        module,
        "build_registry_service_images",
        lambda revision: {"fq_webui": f"ghcr.io/dao1oad/fqnext-webui:{revision}"},
    )
    monkeypatch.setattr(
        module,
        "load_dirty_paths",
        lambda _: ["morningglory/fqwebui/src/views/RuntimeObservability.vue"],
    )

    result = module.compute_rewrite_result(
        repo_root=Path("."),
        compose_file=Path("docker/compose.parallel.yaml"),
        compose_args=["up", "-d", "--build", "fq_webui"],
    )

    assert result["skip_build"] is False
    assert result["mode"] == "build_required"
    assert result["compose_args"] == ["up", "-d", "--build", "fq_webui"]


def test_compute_rewrite_result_keeps_no_build_when_dirty_paths_are_unrelated(
    monkeypatch,
) -> None:
    module = load_module()

    monkeypatch.setattr(module, "load_current_revision", lambda _: "abc123")
    monkeypatch.setattr(
        module,
        "load_compose_service_images",
        lambda _: (
            ["fq_webui"],
            {"fq_webui": "fqnext_webui:2026.2.23"},
        ),
    )
    monkeypatch.setattr(
        module,
        "load_local_image_revisions",
        lambda _: {"fqnext_webui:2026.2.23": "abc123"},
    )
    monkeypatch.setattr(module, "load_remote_image_revisions", lambda _: {})
    monkeypatch.setattr(
        module,
        "build_registry_service_images",
        lambda revision: {"fq_webui": f"ghcr.io/dao1oad/fqnext-webui:{revision}"},
    )
    monkeypatch.setattr(
        module,
        "load_dirty_paths",
        lambda _: ["docs/plans/2026-03-17-docker-deploy-full-optimization.md"],
    )

    result = module.compute_rewrite_result(
        repo_root=Path("."),
        compose_file=Path("docker/compose.parallel.yaml"),
        compose_args=["up", "-d", "--build", "fq_webui"],
    )

    assert result["skip_build"] is True
    assert result["mode"] == "local_cached"
    assert result["compose_args"] == ["up", "-d", "--no-build", "fq_webui"]


def test_compute_rewrite_result_rebuilds_when_dagsterconfig_changes(
    monkeypatch,
) -> None:
    module = load_module()

    monkeypatch.setattr(module, "load_current_revision", lambda _: "abc123")
    monkeypatch.setattr(
        module,
        "load_compose_service_images",
        lambda _: (
            ["fq_dagster_webserver"],
            {"fq_dagster_webserver": "fqnext_rear:2026.2.23"},
        ),
    )
    monkeypatch.setattr(
        module,
        "load_local_image_revisions",
        lambda _: {"fqnext_rear:2026.2.23": "abc123"},
    )
    monkeypatch.setattr(module, "load_remote_image_revisions", lambda _: {})
    monkeypatch.setattr(
        module,
        "build_registry_service_images",
        lambda revision: {
            "fq_dagster_webserver": f"ghcr.io/dao1oad/fqnext-rear:{revision}"
        },
    )
    monkeypatch.setattr(
        module,
        "load_dirty_paths",
        lambda _: ["morningglory/fqdagsterconfig/workspace.yaml"],
    )

    result = module.compute_rewrite_result(
        repo_root=Path("."),
        compose_file=Path("docker/compose.parallel.yaml"),
        compose_args=["up", "-d", "--build", "fq_dagster_webserver"],
    )

    assert result["skip_build"] is False
    assert result["mode"] == "build_required"
    assert result["compose_args"] == ["up", "-d", "--build", "fq_dagster_webserver"]


def test_compute_rewrite_result_can_force_local_build(monkeypatch) -> None:
    module = load_module()

    monkeypatch.setenv("FQ_DOCKER_FORCE_LOCAL_BUILD", "1")
    monkeypatch.setattr(module, "load_current_revision", lambda _: "abc123")
    monkeypatch.setattr(
        module,
        "load_compose_service_images",
        lambda _: (
            ["fq_webui"],
            {"fq_webui": "fqnext_webui:2026.2.23"},
        ),
    )
    monkeypatch.setattr(
        module,
        "load_local_image_revisions",
        lambda _: {"fqnext_webui:2026.2.23": "abc123"},
    )
    monkeypatch.setattr(
        module,
        "load_remote_image_revisions",
        lambda _: {"ghcr.io/dao1oad/fqnext-webui:abc123": "abc123"},
    )
    monkeypatch.setattr(
        module,
        "build_registry_service_images",
        lambda revision: {"fq_webui": f"ghcr.io/dao1oad/fqnext-webui:{revision}"},
    )
    monkeypatch.setattr(module, "load_dirty_paths", lambda _: [])

    result = module.compute_rewrite_result(
        repo_root=Path("."),
        compose_file=Path("docker/compose.parallel.yaml"),
        compose_args=["up", "-d", "--build", "fq_webui"],
    )

    assert result["skip_build"] is False
    assert result["mode"] == "build_required"
    assert result["reason"] == "local build forced by FQ_DOCKER_FORCE_LOCAL_BUILD"
    assert result["compose_args"] == ["up", "-d", "--build", "fq_webui"]
