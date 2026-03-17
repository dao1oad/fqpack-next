import importlib.util
import sys
from pathlib import Path


def load_module():
    module_path = Path("script/ci/resolve_docker_image_publish_plan.py")
    spec = importlib.util.spec_from_file_location(
        "resolve_docker_image_publish_plan", module_path
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_rear_publish_plan_builds_when_shared_rear_inputs_change() -> None:
    module = load_module()

    plan = module.compute_publish_plan(
        changed_paths=["morningglory/fqdagsterconfig/workspace.yaml"],
        bootstrap=False,
    )

    assert plan["rear"]["action"] == "build"
    assert plan["webui"]["action"] == "retag"
    assert plan["ta-backend"]["action"] == "retag"
    assert plan["ta-frontend"]["action"] == "retag"


def test_web_publish_plan_retags_when_only_docs_change() -> None:
    module = load_module()

    plan = module.compute_publish_plan(
        changed_paths=["docs/current/deployment.md"],
        bootstrap=False,
    )

    assert {item["action"] for item in plan.values()} == {"retag"}


def test_bootstrap_mode_builds_all_images() -> None:
    module = load_module()

    plan = module.compute_publish_plan(
        changed_paths=[],
        bootstrap=True,
    )

    assert {item["action"] for item in plan.values()} == {"build"}
