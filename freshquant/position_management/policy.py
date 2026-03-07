# -*- coding: utf-8 -*-

from datetime import datetime, timezone

from freshquant.position_management.models import (
    ALLOW_OPEN,
    FORCE_PROFIT_REDUCE,
    HOLDING_ONLY,
)


class PositionPolicy:
    def __init__(
        self,
        allow_open_min_bail=800000,
        holding_only_min_bail=100000,
        state_stale_after_seconds=15,
        default_state=HOLDING_ONLY,
    ):
        self.allow_open_min_bail = float(allow_open_min_bail)
        self.holding_only_min_bail = float(holding_only_min_bail)
        self.state_stale_after_seconds = int(state_stale_after_seconds)
        self.default_state = default_state

    def state_from_bail(self, available_bail_balance):
        if float(available_bail_balance) > self.allow_open_min_bail:
            return ALLOW_OPEN
        if float(available_bail_balance) > self.holding_only_min_bail:
            return HOLDING_ONLY
        return FORCE_PROFIT_REDUCE

    def effective_state(self, current_state, now_value=None):
        if current_state is None:
            return self.default_state
        state = current_state.get("state")
        if not state:
            return self.default_state
        if self._is_stale(current_state, now_value=now_value):
            return self.default_state
        return state

    def _is_stale(self, current_state, now_value=None):
        evaluated_at = current_state.get("evaluated_at")
        if not evaluated_at:
            return True
        now_dt = now_value or datetime.now(timezone.utc)
        try:
            evaluated_dt = datetime.fromisoformat(str(evaluated_at))
        except ValueError:
            return True
        if evaluated_dt.tzinfo is None:
            evaluated_dt = evaluated_dt.replace(tzinfo=now_dt.tzinfo or timezone.utc)
        return (now_dt - evaluated_dt).total_seconds() > self.state_stale_after_seconds
