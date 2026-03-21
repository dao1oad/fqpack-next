from pathlib import Path


def test_current_docs_cover_dagster_container_home_override() -> None:
    deployment_text = Path("docs/current/deployment.md").read_text(encoding="utf-8")
    troubleshooting_text = Path("docs/current/troubleshooting.md").read_text(
        encoding="utf-8"
    )

    assert "/opt/dagster/home" in deployment_text
    assert "DAGSTER_HOME" in troubleshooting_text
    assert "Windows 路径" in troubleshooting_text


def test_project_deploy_skill_exists_and_covers_formal_flow() -> None:
    skill_text = Path(".claude/skills/fq-deploy/SKILL.md").read_text(encoding="utf-8")

    assert "formal deploy" in skill_text
    assert "origin/main" in skill_text
    assert "main-deploy-production" in skill_text
    assert "run_formal_deploy.py" in skill_text
    assert "check_freshquant_runtime_post_deploy.ps1" in skill_text
