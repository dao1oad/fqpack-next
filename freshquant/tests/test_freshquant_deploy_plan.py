import importlib.util
import sys
from pathlib import Path


def load_module():
    module_path = Path("script/freshquant_deploy_plan.py")
    spec = importlib.util.spec_from_file_location("freshquant_deploy_plan", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_order_management_paths_expand_to_api_and_host_runtime() -> None:
    module = load_module()

    plan = module.build_deploy_plan(
        changed_paths=["freshquant/order_management/submit_service.py"]
    )

    assert plan["deployment_surfaces"] == ["api", "order_management"]
    assert plan["docker_services"] == ["fq_apiserver"]
    assert plan["host_surfaces"] == ["order_management"]
    assert "fqnext_xtquant_broker" in plan["host_programs"]
    assert "fqnext_credit_subjects_worker" in plan["host_programs"]


def test_runtime_symphony_paths_emit_sync_restart_step() -> None:
    module = load_module()

    plan = module.build_deploy_plan(
        changed_paths=["runtime/symphony/prompts/global_stewardship.md"]
    )

    summaries = [item["summary"] for item in plan["pre_deploy_steps"]]
    assert plan["deployment_surfaces"] == ["symphony"]
    assert any("sync_freshquant_symphony_service.ps1" in item for item in summaries)
    assert "http://127.0.0.1:40123/api/v1/state" in plan["health_checks"]


def test_webui_paths_use_web_surface_and_correct_port() -> None:
    module = load_module()

    plan = module.build_deploy_plan(
        changed_paths=["morningglory/fqwebui/src/views/GanttUnified.vue"]
    )

    assert plan["deployment_surfaces"] == ["web"]
    assert plan["docker_services"] == ["fq_webui"]
    assert plan["host_surfaces"] == []
    assert "http://127.0.0.1:18080/" in plan["health_checks"]


def test_summary_render_includes_host_and_docker_sections() -> None:
    module = load_module()
    plan = module.build_deploy_plan(
        changed_paths=[
            "freshquant/order_management/routes.py",
            "morningglory/fqwebui/src/views/PositionManagement.vue",
        ]
    )

    summary = module.render_summary(plan)

    assert "deployment_surfaces: api, web, order_management" in summary
    assert "docker_services: fq_apiserver, fq_webui" in summary
    assert "host_surfaces: order_management" in summary


def test_parser_accepts_release_context_arguments() -> None:
    module = load_module()

    args = module.build_parser().parse_args(
        [
            "--base-sha",
            "abc123",
            "--head-sha",
            "def456",
            "--issue-number",
            "157",
            "--merge-commit",
            "fb4907f",
        ]
    )

    assert args.base_sha == "abc123"
    assert args.head_sha == "def456"
    assert args.issue_number == "157"
    assert args.merge_commit == "fb4907f"


def test_deploy_plan_emits_release_scope_proxyless_mode_and_cleanup_hints() -> None:
    module = load_module()

    plan = module.build_deploy_plan(
        changed_paths=[
            "morningglory/fqwebui/src/views/runtime-observability/index.ts",
            "runtime/symphony/prompts/global_stewardship.md",
            "morningglory/fqwebui/src/views/runtime-observability/panel.ts",
        ],
        explicit_surfaces=["api", "web"],
        base_sha="abc123",
        head_sha="def456",
        issue_number="157",
        merge_commit="fb4907f",
    )

    assert plan["base_sha"] == "abc123"
    assert plan["head_sha"] == "def456"
    assert plan["issue_number"] == "157"
    assert plan["merge_commit"] == "fb4907f"
    assert plan["effective_release_scope"] == ["api", "web", "symphony"]
    assert plan["health_check_mode"] == "proxyless"
    assert plan["verification_markers"]["web"] == ["runtime-observability"]
    assert plan["verification_markers"]["symphony"] == [
        "http://127.0.0.1:40123/api/v1/state"
    ]
    assert plan["cleanup_targets"]["issue_number"] == "157"
    assert plan["cleanup_targets"]["merge_commit"] == "fb4907f"
    assert any("157" in item for item in plan["cleanup_targets"]["workspace_hints"])
