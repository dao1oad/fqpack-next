# -*- coding: utf-8 -*-


class InvalidOrderTransition(ValueError):
    pass


class OrderStateMachine:
    _allowed_transitions = {
        "ACCEPTED": {"QUEUED", "SUBMITTING", "SUBMITTED", "CANCEL_REQUESTED", "FAILED"},
        "QUEUED": {"SUBMITTING", "SUBMITTED", "CANCEL_REQUESTED", "FAILED"},
        "SUBMITTING": {"SUBMITTED", "FAILED", "CANCEL_REQUESTED"},
        "SUBMITTED": {
            "PARTIAL_FILLED",
            "FILLED",
            "CANCEL_REQUESTED",
            "CANCELED",
            "FAILED",
        },
        "PARTIAL_FILLED": {"FILLED", "CANCEL_REQUESTED", "CANCELED", "FAILED"},
        "CANCEL_REQUESTED": {"CANCELED", "PARTIAL_FILLED", "FAILED"},
        "INFERRED_PENDING": {"INFERRED_CONFIRMED", "SUBMITTED", "FILLED", "FAILED"},
    }

    def transition(self, current_state: str, next_state: str) -> str:
        allowed = self._allowed_transitions.get(current_state, set())
        if next_state not in allowed:
            raise InvalidOrderTransition(
                f"Invalid order state transition: {current_state} -> {next_state}"
            )
        return next_state

