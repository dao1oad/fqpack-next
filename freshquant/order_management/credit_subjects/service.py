# -*- coding: utf-8 -*-

from datetime import datetime, timezone

from freshquant.order_management.credit_subjects.models import (
    build_credit_subject_document,
)
from freshquant.order_management.credit_subjects.repository import (
    CreditSubjectRepository,
)
from freshquant.position_management.credit_client import PositionCreditClient


class XtCreditSubjectClient(PositionCreditClient):
    def query_credit_subjects(self):
        trader, account = self._ensure_credit_connection()
        return trader.query_credit_subjects(account)


class CreditSubjectSyncService:
    def __init__(self, repository=None, client=None, now_provider=None):
        self.repository = repository or CreditSubjectRepository()
        self.client = client or XtCreditSubjectClient()
        self.now_provider = now_provider or (lambda: datetime.now(timezone.utc))

    def sync_once(self):
        raw_subjects = self.client.query_credit_subjects()
        subjects = list(raw_subjects or [])
        updated_at = self.now_provider().isoformat()
        account_id = getattr(self.client, "account_id", None)

        for subject in subjects:
            document = build_credit_subject_document(
                subject,
                account_id=account_id,
                updated_at=updated_at,
            )
            self.repository.upsert_subject(document)

        deleted_count = 0
        if raw_subjects is not None:
            deleted_count = self.repository.delete_missing_subjects(
                account_id,
                [getattr(subject, "instrument_id", None) for subject in subjects],
            )

        return {
            "count": len(subjects),
            "account_id": account_id,
            "account_type": getattr(self.client, "account_type", None),
            "updated_at": updated_at,
            "deleted_count": deleted_count,
        }


def sync_credit_subjects_once(client=None, repository=None, now_provider=None):
    service = CreditSubjectSyncService(
        repository=repository,
        client=client,
        now_provider=now_provider,
    )
    return service.sync_once()
