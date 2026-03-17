from __future__ import annotations


class FakeRepository:
    def __init__(self) -> None:
        self.runs: dict[str, dict] = {}

    def save_run(self, run=None, **document):
        payload = dict(run or {})
        payload.update(document)
        run_id = payload["run_id"]
        existing = dict(self.runs.get(run_id, {}))
        existing.update(payload)
        self.runs[run_id] = existing
        return dict(existing)

    def get_run(self, run_id):
        row = self.runs.get(run_id)
        return dict(row) if row is not None else None


def test_pipeline_service_records_stage_summaries(monkeypatch):
    from freshquant.daily_screening.pipeline_service import (
        DailyScreeningPipelineService,
    )

    monkeypatch.setattr(
        "freshquant.daily_screening.pipeline_service.uuid.uuid4",
        lambda: type("FixedUUID", (), {"hex": "run1234567890"})(),
    )
    repo = FakeRepository()
    pipeline = DailyScreeningPipelineService(repository=repo)

    run = pipeline.start_run({"mode": "full"}, trigger_type="manual_api")

    assert run["status"] == "queued"
    assert run["stage_summaries"] == {}
    assert repo.get_run(run["id"])["trigger_type"] == "manual_api"
