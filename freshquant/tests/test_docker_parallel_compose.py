import importlib.util
import sys
from pathlib import Path


def load_module():
    module_path = Path("script/docker_parallel_compose.py")
    spec = importlib.util.spec_from_file_location("docker_parallel_compose", module_path)
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
