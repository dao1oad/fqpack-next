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
    assert "fqnext_xt_account_sync_worker" in plan["host_programs"]


def test_retired_runtime_paths_no_longer_emit_deploy_surface() -> None:
    module = load_module()

    plan = module.build_deploy_plan(changed_paths=["runtime/retired/workflow.md"])

    summaries = [item["summary"] for item in plan["pre_deploy_steps"]]
    assert plan["deployment_surfaces"] == []
    assert all("sync_freshquant_" not in item for item in summaries)
    assert "http://127.0.0.1:40123/api/v1/state" not in plan["health_checks"]


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


def test_shared_runtime_paths_expand_to_all_affected_surfaces() -> None:
    module = load_module()

    plan = module.build_deploy_plan(
        changed_paths=[
            "freshquant/__init__.py",
            "freshquant/runtime/network.py",
            "freshquant/message/dingtalk.py",
            "freshquant/trading/dt.py",
            "morningglory/fqxtrade/fqxtrade/__init__.py",
        ]
    )

    assert plan["deployment_surfaces"] == [
        "api",
        "dagster",
        "market_data",
        "guardian",
        "position_management",
        "tpsl",
        "order_management",
    ]
    assert plan["docker_services"] == [
        "fq_apiserver",
        "fq_dagster_webserver",
        "fq_dagster_daemon",
    ]
    assert plan["host_surfaces"] == [
        "market_data",
        "guardian",
        "position_management",
        "tpsl",
        "order_management",
    ]
    assert "fqnext_realtime_xtdata_consumer" in plan["host_programs"]
    assert "fqnext_xtquant_broker" in plan["host_programs"]
    assert "fqnext_xt_account_sync_worker" in plan["host_programs"]


def test_dagster_surface_requires_shared_rear_build_target() -> None:
    module = load_module()

    plan = module.build_deploy_plan(explicit_surfaces=["dagster"])

    assert plan["docker_build_targets"] == ["fq_apiserver"]
    assert plan["docker_up_services"] == [
        "fq_dagster_webserver",
        "fq_dagster_daemon",
    ]
    assert plan["docker_services"] == [
        "fq_apiserver",
        "fq_dagster_webserver",
        "fq_dagster_daemon",
    ]


def test_etf_adj_sync_path_requires_dagster_redeploy() -> None:
    module = load_module()

    plan = module.build_deploy_plan(
        changed_paths=["freshquant/data/etf_adj_sync.py"]
    )

    assert plan["deployment_surfaces"] == ["dagster"]
    assert plan["docker_build_targets"] == ["fq_apiserver"]
    assert plan["docker_up_services"] == [
        "fq_dagster_webserver",
        "fq_dagster_daemon",
    ]


def test_qa_surface_requires_shared_rear_build_target() -> None:
    module = load_module()

    plan = module.build_deploy_plan(explicit_surfaces=["qa"])

    assert plan["docker_build_targets"] == ["fq_apiserver"]
    assert plan["docker_up_services"] == ["fq_qawebserver"]
    assert plan["docker_services"] == ["fq_apiserver", "fq_qawebserver"]
