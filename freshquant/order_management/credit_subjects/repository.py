# -*- coding: utf-8 -*-

from freshquant.order_management.credit_subjects.models import split_instrument_id
from freshquant.order_management.repository import OrderManagementRepository


class CreditSubjectRepository:
    def __init__(self, order_repository=None):
        self.order_repository = order_repository or OrderManagementRepository()

    @property
    def collection(self):
        return self.order_repository.credit_subjects

    def upsert_subject(self, document):
        query = {"instrument_id": document["instrument_id"]}
        account_id = document.get("account_id")
        if account_id:
            query["account_id"] = account_id
        self.collection.replace_one(query, document, upsert=True)
        return self.find_one(document["instrument_id"], account_id=account_id)

    def find_one(self, instrument_id, account_id=None):
        query = {"instrument_id": str(instrument_id or "").strip().upper()}
        if account_id is not None:
            query["account_id"] = str(account_id).strip()
        return self.collection.find_one(query)

    def find_by_symbol(self, symbol, account_id=None):
        symbol_value = split_instrument_id(symbol)[0]
        query = {"symbol": symbol_value}
        if account_id is not None:
            query["account_id"] = str(account_id).strip()
        return self.collection.find_one(query)

    def has_any_subjects(self, account_id=None):
        query = {}
        if account_id is not None:
            query["account_id"] = str(account_id).strip()
        return self.collection.count_documents(query, limit=1) > 0
