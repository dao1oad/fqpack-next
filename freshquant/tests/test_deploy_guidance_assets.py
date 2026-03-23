from pathlib import Path


def test_current_docs_cover_dagster_container_home_override() -> None:
    deployment_text = Path("docs/current/deployment.md").read_text(encoding="utf-8")
    troubleshooting_text = Path("docs/current/troubleshooting.md").read_text(
        encoding="utf-8"
    )

    assert "/opt/dagster/home" in deployment_text
    assert "DAGSTER_HOME" in troubleshooting_text
    assert "Windows 路径" in troubleshooting_text


def test_current_docs_cover_host_runtime_dependency_drift() -> None:
    deployment_text = Path("docs/current/deployment.md").read_text(encoding="utf-8")
    troubleshooting_text = Path("docs/current/troubleshooting.md").read_text(
        encoding="utf-8"
    )

    assert "site-packages" in deployment_text
    assert (
        "resolve_stock_account() got an unexpected keyword argument 'settings_provider'"
        in troubleshooting_text
    )
    assert "fqxtrade" in troubleshooting_text


def test_current_docs_cover_transient_fqchan04_build_failure() -> None:
    deployment_text = Path("docs/current/deployment.md").read_text(encoding="utf-8")
    troubleshooting_text = Path("docs/current/troubleshooting.md").read_text(
        encoding="utf-8"
    )

    assert "fqchan04" in deployment_text
    assert "fq_apiserver" in deployment_text
    assert "internal compiler error" in troubleshooting_text
    assert "原样重跑 1 次" in troubleshooting_text


def test_project_deploy_skill_exists_and_covers_formal_flow() -> None:
    skill_text = Path(".claude/skills/fq-deploy/SKILL.md").read_text(encoding="utf-8")

    assert "formal deploy" in skill_text
    assert "origin/main" in skill_text
    assert "main-deploy-production" in skill_text
    assert "run_formal_deploy.py" in skill_text
    assert "check_freshquant_runtime_post_deploy.ps1" in skill_text
    assert "fqnext_host_runtime_ctl.ps1 -Mode Status" in skill_text
    assert "site-packages" in skill_text
    assert "fqchan04" in skill_text
    assert "原样重跑 1 次" in skill_text
