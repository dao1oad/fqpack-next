from __future__ import annotations

from types import SimpleNamespace


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


def test_pipeline_service_execute_run_success_path_records_summary(monkeypatch):
    from freshquant.daily_screening.pipeline_service import (
        DailyScreeningPipelineService,
    )

    monkeypatch.setattr(
        "freshquant.daily_screening.pipeline_service.uuid.uuid4",
        lambda: type("FixedUUID", (), {"hex": "run2234567890"})(),
    )
    repo = FakeRepository()
    pipeline = DailyScreeningPipelineService(repository=repo)
    created = pipeline.start_run({"model": "clxs"}, trigger_type="manual_api")
    events = []

    run = pipeline.execute_run(
        created["id"],
        {"model": "clxs", "model_opt": 10001},
        execute_stage=lambda stage_name, stage_config: (
            [
                SimpleNamespace(code="000001"),
                SimpleNamespace(code="000002"),
            ],
            1,
        ),
        on_event=lambda event, payload: events.append((event, payload)),
    )

    assert [event for event, _payload in events] == [
        "run_started",
        "stage_started",
        "stage_completed",
        "run_completed",
    ]
    assert run["status"] == "completed"
    assert run["summary"] == {
        "accepted_count": 2,
        "persisted_count": 1,
        "stage_count": 1,
    }
    assert repo.get_run(created["id"])["stage_summaries"]["clxs"]["accepted_count"] == 2


def test_pipeline_service_execute_run_failure_path_emits_run_failed(monkeypatch):
    from freshquant.daily_screening.pipeline_service import (
        DailyScreeningPipelineService,
    )

    monkeypatch.setattr(
        "freshquant.daily_screening.pipeline_service.uuid.uuid4",
        lambda: type("FixedUUID", (), {"hex": "run3234567890"})(),
    )
    repo = FakeRepository()
    pipeline = DailyScreeningPipelineService(repository=repo)
    created = pipeline.start_run({"model": "clxs"}, trigger_type="manual_api")
    events = []

    run = pipeline.execute_run(
        created["id"],
        {"model": "clxs", "model_opt": 10001},
        execute_stage=lambda stage_name, stage_config: (_ for _ in ()).throw(
            RuntimeError("boom")
        ),
        on_event=lambda event, payload: events.append((event, payload)),
    )

    assert [event for event, _payload in events] == [
        "run_started",
        "stage_started",
        "run_failed",
    ]
    assert run["status"] == "failed"
    assert run["error"] == "boom"
    assert run["stage_summaries"]["clxs"]["status"] == "failed"
