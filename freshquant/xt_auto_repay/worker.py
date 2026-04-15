# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import logging
import time
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from freshquant.xt_auto_repay.executor import XtAutoRepayExecutor
from freshquant.xt_auto_repay.service import (
    HARD_SETTLE_MODE,
    INTRADAY_MODE,
    RETRY_MODE,
    XtAutoRepayService,
)

try:
    from freshquant.database.redis import redis_db  # type: ignore
except Exception:  # pragma: no cover
    redis_db = None  # type: ignore

SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
DEFAULT_INTRADAY_INTERVAL_SECONDS = 1800.0
DEFAULT_COOLDOWN_SECONDS = 1800.0
DEFAULT_LOCK_TTL_SECONDS = 120
DEFAULT_RETRY_DELAY_SECONDS = 5.0
DEFAULT_RETRY_DELAY_MAX_SECONDS = 60.0
HARD_SETTLE_TIME = (14, 55)
RETRY_TIME = (15, 5)

logger = logging.getLogger(__name__)
_REDIS_RELEASE_LOCK_LUA = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
end
return 0
"""


class XtAutoRepayWorker:
    def __init__(
        self,
        *,
        service=None,
        executor=None,
        executor_factory=None,
        lock_client=None,
        intraday_interval_seconds=DEFAULT_INTRADAY_INTERVAL_SECONDS,
        cooldown_seconds=DEFAULT_COOLDOWN_SECONDS,
        lock_ttl_seconds=DEFAULT_LOCK_TTL_SECONDS,
        retry_delay_seconds=DEFAULT_RETRY_DELAY_SECONDS,
        retry_delay_max_seconds=DEFAULT_RETRY_DELAY_MAX_SECONDS,
        retry_sleep_fn=None,
        now_provider=None,
    ):
        self.service = service or XtAutoRepayService()
        self.executor = executor or XtAutoRepayExecutor()
        self.executor_factory = executor_factory or (
            XtAutoRepayExecutor if executor is None else None
        )
        self.lock_client = lock_client or _CooldownLockClient(redis_db)
        self.intraday_interval_seconds = max(
            float(intraday_interval_seconds or DEFAULT_INTRADAY_INTERVAL_SECONDS), 1.0
        )
        self.cooldown_seconds = max(float(cooldown_seconds or 0.0), 0.0)
        self.lock_ttl_seconds = max(int(lock_ttl_seconds or 0), 1)
        self.retry_delay_seconds = max(
            float(retry_delay_seconds or DEFAULT_RETRY_DELAY_SECONDS),
            1.0,
        )
        self.retry_delay_max_seconds = max(
            float(retry_delay_max_seconds or DEFAULT_RETRY_DELAY_MAX_SECONDS),
            self.retry_delay_seconds,
        )
        self.retry_sleep_fn = retry_sleep_fn or time.sleep
        self.now_provider = now_provider or _shanghai_now

    def run_mode(self, mode, *, now=None):
        resolved_mode = _normalize_mode(mode)
        resolved_now = now or self.now_provider()
        if not self._refresh_settings():
            return self._volatile_skip(
                mode=resolved_mode, reason="settings_unavailable"
            )
        checked_at = resolved_now.isoformat()
        state = dict(self.service.get_state() or {})
        snapshot_decision = None

        precheck_reason = _precheck_skip_reason(self.service)
        if precheck_reason:
            return self._skip(
                mode=resolved_mode,
                now=resolved_now,
                reason=precheck_reason,
            )

        if resolved_mode == INTRADAY_MODE:
            if self._in_cooldown(state, resolved_now):
                return self._skip(
                    mode=resolved_mode,
                    now=resolved_now,
                    reason="cooldown",
                )
            snapshot = self.service.load_latest_snapshot()
            snapshot_decision = self.service.evaluate_snapshot(
                snapshot,
                now=resolved_now,
                mode=resolved_mode,
            )
            self.service.update_state(last_checked_at=checked_at)
            if not snapshot_decision.get("eligible"):
                return self._skip(
                    mode=resolved_mode,
                    now=resolved_now,
                    reason=snapshot_decision.get("reason"),
                    snapshot_decision=snapshot_decision,
                )

        lock_key = f"xt_auto_repay:{self.service.account_id}"
        if not self.lock_client.acquire(
            lock_key,
            ttl_seconds=self.lock_ttl_seconds,
        ):
            return self._skip(
                mode=resolved_mode,
                now=resolved_now,
                reason="lock_unavailable",
                snapshot_decision=snapshot_decision,
                mark_mode_completed=False,
            )
        try:
            detail = self._query_credit_detail_with_xt_retry()
            confirmed_decision = self.service.evaluate_confirmed_detail(
                detail,
                mode=resolved_mode,
                now=resolved_now,
            )
            if not confirmed_decision.get("eligible"):
                return self._skip(
                    mode=resolved_mode,
                    now=resolved_now,
                    reason=confirmed_decision.get("reason"),
                    snapshot_decision=snapshot_decision,
                    confirmed_decision=confirmed_decision,
                )

            state_updates = {
                "last_checked_at": checked_at,
                "last_status": (
                    "observe_only" if self.service.observe_only else "submitted"
                ),
                "last_reason": confirmed_decision.get("reason"),
                "last_submit_amount": confirmed_decision.get("repay_amount"),
            }
            state_updates.update(_mode_timestamp_fields(resolved_mode, checked_at))

            if self.service.observe_only:
                self.service.record_event(
                    event_type="observe_only",
                    mode=resolved_mode,
                    reason="observe_only",
                    snapshot_available_amount=_decision_value(
                        snapshot_decision,
                        "snapshot_available_amount",
                    ),
                    snapshot_fin_debt=_decision_value(
                        snapshot_decision, "snapshot_fin_debt"
                    ),
                    confirmed_available_amount=_decision_value(
                        confirmed_decision,
                        "confirmed_available_amount",
                    ),
                    confirmed_fin_debt=_decision_value(
                        confirmed_decision,
                        "confirmed_fin_debt",
                    ),
                    candidate_amount=_decision_value(
                        snapshot_decision, "candidate_amount"
                    ),
                    submitted_amount=_decision_value(
                        confirmed_decision, "repay_amount"
                    ),
                )
                self.service.update_state(**state_updates)
                return {
                    "mode": resolved_mode,
                    "status": "observe_only",
                    "repay_amount": confirmed_decision.get("repay_amount"),
                }

            repay_amount = confirmed_decision.get("repay_amount")
            try:
                broker_order_id = self.executor.submit_direct_cash_repay(
                    repay_amount=repay_amount,
                    remark=f"xt_auto_repay:{resolved_mode}:{checked_at}",
                )
            except Exception as error:
                failure_reason = _submit_failure_reason(error)
                logger.warning(
                    "xt auto repay submit failed for %s: %s",
                    resolved_mode,
                    failure_reason,
                    exc_info=True,
                )
                state_updates["last_status"] = "failed"
                state_updates["last_reason"] = failure_reason
                state_updates["last_submit_order_id"] = None
                self.service.record_event(
                    event_type="failed",
                    mode=resolved_mode,
                    reason=failure_reason,
                    snapshot_available_amount=_decision_value(
                        snapshot_decision,
                        "snapshot_available_amount",
                    ),
                    snapshot_fin_debt=_decision_value(
                        snapshot_decision, "snapshot_fin_debt"
                    ),
                    confirmed_available_amount=_decision_value(
                        confirmed_decision,
                        "confirmed_available_amount",
                    ),
                    confirmed_fin_debt=_decision_value(
                        confirmed_decision, "confirmed_fin_debt"
                    ),
                    candidate_amount=_decision_value(
                        snapshot_decision, "candidate_amount"
                    ),
                    submitted_amount=repay_amount,
                )
                self.service.update_state(**state_updates)
                return {
                    "mode": resolved_mode,
                    "status": "failed",
                    "repay_amount": repay_amount,
                    "reason": failure_reason,
                }
            broker_order_id_value = _positive_order_id_value(broker_order_id)
            event_type = "submitted" if broker_order_id_value is not None else "failed"
            state_updates["last_submit_order_id"] = (
                None if broker_order_id_value is None else str(broker_order_id_value)
            )
            if event_type == "submitted":
                state_updates["last_submit_at"] = checked_at
                event_reason = confirmed_decision.get("reason")
            else:
                event_reason = "xtquant direct cash repay returned no order id"
                state_updates["last_status"] = "failed"
                state_updates["last_reason"] = event_reason
            self.service.record_event(
                event_type=event_type,
                mode=resolved_mode,
                reason=event_reason,
                snapshot_available_amount=_decision_value(
                    snapshot_decision,
                    "snapshot_available_amount",
                ),
                snapshot_fin_debt=_decision_value(
                    snapshot_decision, "snapshot_fin_debt"
                ),
                confirmed_available_amount=_decision_value(
                    confirmed_decision,
                    "confirmed_available_amount",
                ),
                confirmed_fin_debt=_decision_value(
                    confirmed_decision, "confirmed_fin_debt"
                ),
                candidate_amount=_decision_value(snapshot_decision, "candidate_amount"),
                submitted_amount=repay_amount,
                broker_order_id=broker_order_id,
            )
            self.service.update_state(**state_updates)
            return {
                "mode": resolved_mode,
                "status": event_type,
                "repay_amount": repay_amount,
                "broker_order_id": broker_order_id,
            }
        finally:
            self.lock_client.release(lock_key)

    def run_pending(self, *, now=None):
        resolved_now = now or self.now_provider()
        if not self._refresh_settings():
            return []
        state = dict(self.service.get_state() or {})
        modes = _due_modes(resolved_now, state)
        if not modes:
            if not self._should_run_intraday(resolved_now, state):
                return []
            modes = [INTRADAY_MODE]
        return [self.run_mode(mode, now=resolved_now) for mode in modes]

    def next_sleep_seconds(self, *, now=None):
        resolved_now = now or self.now_provider()
        if not self._refresh_settings():
            return 1.0
        state = dict(self.service.get_state() or {})
        candidates = [
            _next_intraday_delay_seconds(
                resolved_now, state, self.intraday_interval_seconds
            )
        ]
        for scheduled_time, field_name in (
            (HARD_SETTLE_TIME, "last_hard_settle_at"),
            (RETRY_TIME, "last_retry_at"),
        ):
            if _ran_today(state.get(field_name), resolved_now):
                continue
            scheduled_at = resolved_now.replace(
                hour=scheduled_time[0],
                minute=scheduled_time[1],
                second=0,
                microsecond=0,
            )
            delta_seconds = (scheduled_at - resolved_now).total_seconds()
            if delta_seconds > 0:
                candidates.append(delta_seconds)
        return max(1.0, min(candidates))

    def _should_run_intraday(self, now_value, state):
        last_checked_at = _parse_datetime(state.get("last_checked_at"))
        if last_checked_at is None:
            return True
        return (
            now_value - last_checked_at
        ).total_seconds() >= self.intraday_interval_seconds

    def _in_cooldown(self, state, now_value):
        last_submit_at = _parse_datetime(state.get("last_submit_at"))
        if last_submit_at is None or self.cooldown_seconds <= 0:
            return False
        return (now_value - last_submit_at).total_seconds() < self.cooldown_seconds

    def _skip(
        self,
        *,
        mode,
        now,
        reason,
        snapshot_decision=None,
        confirmed_decision=None,
        mark_mode_completed=True,
    ):
        checked_at = now.isoformat()
        self.service.record_event(
            event_type="skip",
            mode=mode,
            reason=reason,
            snapshot_available_amount=_decision_value(
                snapshot_decision,
                "snapshot_available_amount",
            ),
            snapshot_fin_debt=_decision_value(snapshot_decision, "snapshot_fin_debt"),
            confirmed_available_amount=_decision_value(
                confirmed_decision,
                "confirmed_available_amount",
            ),
            confirmed_fin_debt=_decision_value(
                confirmed_decision, "confirmed_fin_debt"
            ),
            candidate_amount=_decision_value(snapshot_decision, "candidate_amount"),
            submitted_amount=_decision_value(confirmed_decision, "repay_amount"),
        )
        state_updates = {
            "last_checked_at": checked_at,
            "last_status": "skip",
            "last_reason": reason,
        }
        if mark_mode_completed:
            state_updates.update(_mode_timestamp_fields(mode, checked_at))
        self.service.update_state(**state_updates)
        return {"mode": mode, "status": "skip", "reason": reason}

    def _refresh_settings(self):
        refresh_fn = getattr(self.service, "refresh_settings", None)
        if not callable(refresh_fn):
            return True
        return bool(refresh_fn(strict=False))

    def _volatile_skip(self, *, mode, reason):
        logger.warning("xt auto repay worker skipped without persistence: %s", reason)
        return {"mode": mode, "status": "skip", "reason": reason}

    def _query_credit_detail_with_xt_retry(self):
        delay_seconds = self.retry_delay_seconds
        while True:
            try:
                return self.executor.query_credit_detail()
            except Exception as error:
                if not _is_retryable_xt_auto_repay_error(error):
                    raise
                logger.warning(
                    "xt auto repay XT unavailable; retrying in %.1f seconds: %s",
                    delay_seconds,
                    error,
                )
                self._reset_executor_after_retryable_xt_error()
                self.retry_sleep_fn(delay_seconds)
                delay_seconds = min(delay_seconds * 2, self.retry_delay_max_seconds)

    def _reset_executor_after_retryable_xt_error(self):
        credit_client = getattr(self.executor, "credit_client", None)
        reset_fn = getattr(credit_client, "reset_connection", None)
        if callable(reset_fn):
            try:
                reset_fn()
            except Exception:
                logger.debug(
                    "xt auto repay credit client reset failed",
                    exc_info=True,
                )
        if self.executor_factory is not None:
            self.executor = self.executor_factory()


class _CooldownLockClient:
    def __init__(self, redis_client):
        self.redis_client = redis_client
        self._memory = {}
        self._tokens = {}

    def acquire(self, key, *, ttl_seconds):
        ttl = max(int(ttl_seconds or 0), 0)
        if ttl <= 0:
            return True
        token = uuid.uuid4().hex
        if self.redis_client is not None:
            try:
                acquired = bool(self.redis_client.set(key, token, ex=ttl, nx=True))
            except Exception as exc:
                raise RuntimeError("xt auto repay redis lock failed") from exc
            if acquired:
                self._tokens[key] = token
            return acquired
        now_value = time.time()
        entry = self._memory.get(key)
        expires_at = float(entry["expires_at"]) if isinstance(entry, dict) else 0.0
        if expires_at > now_value:
            return False
        self._memory[key] = {
            "token": token,
            "expires_at": now_value + ttl,
        }
        self._tokens[key] = token
        return True

    def release(self, key):
        token = self._tokens.pop(key, None)
        if token is None:
            return False
        if self.redis_client is not None:
            try:
                released = self.redis_client.eval(
                    _REDIS_RELEASE_LOCK_LUA,
                    1,
                    key,
                    token,
                )
            except Exception as exc:
                raise RuntimeError("xt auto repay redis lock release failed") from exc
            return bool(int(released or 0) > 0)
        entry = self._memory.get(key)
        if not isinstance(entry, dict):
            return False
        if str(entry.get("token") or "") != str(token):
            return False
        self._memory.pop(key, None)
        return True


def run_once(worker=None, *, now=None):
    auto_repay_worker = worker or XtAutoRepayWorker()
    return auto_repay_worker.run_pending(now=now)


def run_forever(worker=None, *, sleep_fn=time.sleep, now_provider=None):
    auto_repay_worker = worker or XtAutoRepayWorker(now_provider=now_provider)
    while True:
        current_now = auto_repay_worker.now_provider()
        try:
            auto_repay_worker.run_pending(now=current_now)
            sleep_seconds = auto_repay_worker.next_sleep_seconds(now=current_now)
        except Exception:
            logger.exception("xt auto repay worker loop failed")
            sleep_seconds = 1.0
        sleep_fn(sleep_seconds)


def main(argv=None, worker=None):
    parser = argparse.ArgumentParser(description="XT auto repay worker")
    parser.add_argument("--once", action="store_true", help="run pending tasks once")
    args = parser.parse_args(argv)
    if args.once:
        run_once(worker=worker)
        return 0
    run_forever(worker=worker)
    return 0


def _due_modes(now_value, state):
    modes = []
    if _is_due(now_value, HARD_SETTLE_TIME) and not _ran_today(
        state.get("last_hard_settle_at"),
        now_value,
    ):
        modes.append(HARD_SETTLE_MODE)
    if _is_due(now_value, RETRY_TIME) and not _ran_today(
        state.get("last_retry_at"),
        now_value,
    ):
        modes.append(RETRY_MODE)
    return modes


def _mode_timestamp_fields(mode, checked_at):
    if mode == HARD_SETTLE_MODE:
        return {"last_hard_settle_at": checked_at}
    if mode == RETRY_MODE:
        return {"last_retry_at": checked_at}
    return {}


def _decision_value(decision, key):
    if not isinstance(decision, dict):
        return None
    return decision.get(key)


def _ran_today(value, now_value):
    parsed = _parse_datetime(value)
    return parsed is not None and parsed.date() == now_value.date()


def _is_due(now_value, scheduled_time):
    return (now_value.hour, now_value.minute) >= scheduled_time


def _parse_datetime(value):
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _normalize_mode(mode):
    normalized = str(mode or INTRADAY_MODE).strip().lower() or INTRADAY_MODE
    if normalized not in {INTRADAY_MODE, HARD_SETTLE_MODE, RETRY_MODE}:
        raise ValueError(f"unsupported auto repay mode: {normalized}")
    return normalized


def _shanghai_now():
    return datetime.now(SHANGHAI_TZ)


def _precheck_skip_reason(service):
    if not str(getattr(service, "account_id", "") or "").strip():
        return "missing_account_id"
    if str(getattr(service, "account_type", "STOCK") or "STOCK").upper() != "CREDIT":
        return "non_credit_account"
    if not bool(getattr(service, "enabled", True)):
        return "disabled"
    return None


def _next_intraday_delay_seconds(now_value, state, intraday_interval_seconds):
    last_checked_at = _parse_datetime(state.get("last_checked_at"))
    if last_checked_at is None:
        return max(1.0, float(intraday_interval_seconds or 1.0))
    due_at = last_checked_at + timedelta(
        seconds=float(intraday_interval_seconds or 0.0)
    )
    remaining_seconds = (due_at - now_value).total_seconds()
    if remaining_seconds <= 0:
        return 1.0
    return max(1.0, remaining_seconds)


def _is_retryable_xt_auto_repay_error(error):
    if (
        isinstance(error, ValueError)
        and str(error) == "query_credit_detail returned no records"
    ):
        return True
    message = str(error or "")
    normalized = message.lower()
    if normalized.startswith("xtquant connect failed:") or normalized.startswith(
        "xtquant subscribe failed:"
    ):
        return True
    if "无法连接xtquant" in message or "鏃犳硶杩炴帴xtquant" in message:
        return True
    return "xtquant" in normalized and "qmt" in normalized


def _submit_failure_reason(error):
    message = str(error or "").strip()
    if message:
        return message
    return error.__class__.__name__


def _positive_order_id_value(value):
    try:
        resolved = int(value or 0)
    except (TypeError, ValueError):
        return None
    if resolved <= 0:
        return None
    return resolved


if __name__ == "__main__":
    raise SystemExit(main())
