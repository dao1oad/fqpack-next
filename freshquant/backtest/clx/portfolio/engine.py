"""Deterministic daily A-share long-only matching fixture.

Decisions are revealed after a session close.  Their orders first attempt at the
next supplied snapshot session's raw open.  Buy orders expire after one attempt;
blocked exits remain pending.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Generator, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal

from .fees import (
    DEFAULT_FEE_SCHEDULE,
    DEFAULT_SLIPPAGE_MODEL,
    FeeSchedule,
    SlippageModel,
)
from .limits import DEFAULT_LIMIT_SCHEDULE, LimitCheck, LimitRuleSchedule
from .models import (
    QUALITY_DEFAULT_LOT_SIZE,
    QUALITY_STALE_CLOSE,
    BlockedReason,
    BlockedRecord,
    EquitySnapshot,
    FillRecord,
    LotEvent,
    MarketBar,
    OrderAttempt,
    OrderStatus,
    PendingOrderSnapshot,
    PortfolioRunResult,
    PositionSnapshot,
    Side,
    SignalDecision,
    decimal,
)


class PortfolioInputError(ValueError):
    pass


class PortfolioReconciliationError(RuntimeError):
    pass


def _canonical(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _canonical(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    return value


@dataclass(frozen=True)
class PortfolioConfig:
    run_id: str
    combo_id: str
    initial_cash: Decimal
    target_weight: Decimal = Decimal("1")
    max_holdings: int = 10
    lot_sizes: tuple[tuple[str, int], ...] = ()
    fee_schedule: FeeSchedule = DEFAULT_FEE_SCHEDULE
    limit_schedule: LimitRuleSchedule = DEFAULT_LIMIT_SCHEDULE
    slippage_model: SlippageModel = DEFAULT_SLIPPAGE_MODEL
    reconciliation_floor: Decimal = Decimal("0.01")
    reconciliation_relative: Decimal = Decimal("0.00000001")
    replacement_policy: str = "NONE"

    def __post_init__(self) -> None:
        object.__setattr__(self, "initial_cash", decimal(self.initial_cash))
        object.__setattr__(self, "target_weight", decimal(self.target_weight))
        object.__setattr__(
            self, "reconciliation_floor", decimal(self.reconciliation_floor)
        )
        object.__setattr__(
            self, "reconciliation_relative", decimal(self.reconciliation_relative)
        )
        object.__setattr__(self, "lot_sizes", tuple(self.lot_sizes))
        if not self.run_id or not self.combo_id:
            raise ValueError("run_id and combo_id are required")
        if self.initial_cash <= 0:
            raise ValueError("initial_cash must be positive")
        if not Decimal("0") < self.target_weight <= Decimal("1"):
            raise ValueError("target_weight must be in (0, 1]")
        if self.max_holdings <= 0:
            raise ValueError("max_holdings must be positive")
        lot_codes = [code for code, _ in self.lot_sizes]
        if len(lot_codes) != len(set(lot_codes)):
            raise ValueError("lot_sizes contains duplicate codes")
        if any(size <= 0 for _, size in self.lot_sizes):
            raise ValueError("lot sizes must be positive")
        if self.reconciliation_floor <= 0 or self.reconciliation_relative <= 0:
            raise ValueError("reconciliation tolerances must be positive")
        if self.replacement_policy not in ("NONE", "SCORE_REPLACE_WEAKEST_HOLDING"):
            raise ValueError("unknown replacement_policy")

    @property
    def portfolio_id(self) -> str:
        identity = _canonical(asdict(self))
        if identity.get("replacement_policy") == "NONE":
            # Keep pre-replacement portfolio identities byte-stable.
            identity.pop("replacement_policy")
        payload = json.dumps(
            identity,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return "pf_" + hashlib.sha256(payload).hexdigest()

    def lot_size_for(self, code: str) -> tuple[int, int]:
        configured = dict(self.lot_sizes).get(code)
        if configured is not None:
            return configured, 0
        return 100, QUALITY_DEFAULT_LOT_SIZE


@dataclass
class _PendingOrder:
    order_id: str
    decision: SignalDecision
    side: Side
    requested_qty: int
    target_trade_date: date
    score: Decimal
    quality_mask: int
    attempt_no: int = 0


@dataclass
class _Lot:
    lot_id: str
    code: str
    acquired_date: date
    available_date: date
    original_qty: int
    remaining_qty: int
    unit_cost: Decimal
    quality_mask: int
    released: bool = False


class _Ledger:
    def __init__(self, initial_cash: Decimal, portfolio_id: str) -> None:
        self.cash = initial_cash
        self.portfolio_id = portfolio_id
        self.lots: list[_Lot] = []
        self._lot_sequence = 0

    def codes(self) -> set[str]:
        return {lot.code for lot in self.lots if lot.remaining_qty > 0}

    def quantity(self, code: str) -> int:
        return sum(lot.remaining_qty for lot in self.lots if lot.code == code)

    def quantities(self) -> dict[str, int]:
        return {code: self.quantity(code) for code in sorted(self.codes())}

    def available_quantity(self, code: str) -> int:
        return sum(
            lot.remaining_qty for lot in self.lots if lot.code == code and lot.released
        )

    def quality_mask(self, code: str) -> int:
        mask = 0
        for lot in self.lots:
            if lot.code == code and lot.remaining_qty > 0:
                mask |= lot.quality_mask
        return mask

    def cost_basis(self, code: str) -> Decimal:
        return sum(
            (
                lot.unit_cost * lot.remaining_qty
                for lot in self.lots
                if lot.code == code
            ),
            Decimal("0"),
        )

    def release(self, session: date) -> list[LotEvent]:
        events: list[LotEvent] = []
        for lot in self.lots:
            if lot.remaining_qty and not lot.released and lot.available_date <= session:
                lot.released = True
                events.append(
                    LotEvent(
                        self.portfolio_id,
                        lot.lot_id,
                        "T1_RELEASE",
                        session,
                        lot.code,
                        0,
                        lot.remaining_qty,
                        lot.acquired_date,
                        lot.available_date,
                        lot.unit_cost,
                        None,
                    )
                )
        return events

    def buy(
        self,
        *,
        trade_date: date,
        available_date: date,
        code: str,
        qty: int,
        unit_cost: Decimal,
        cash_delta: Decimal,
        fill_id: str,
        quality_mask: int,
    ) -> LotEvent:
        if qty <= 0 or cash_delta >= 0:
            raise PortfolioReconciliationError("invalid buy ledger mutation")
        if self.cash + cash_delta < 0:
            raise PortfolioReconciliationError("buy would create negative cash")
        self.cash += cash_delta
        self._lot_sequence += 1
        lot = _Lot(
            lot_id=f"L{self._lot_sequence:08d}",
            code=code,
            acquired_date=trade_date,
            available_date=available_date,
            original_qty=qty,
            remaining_qty=qty,
            unit_cost=unit_cost,
            quality_mask=quality_mask,
        )
        self.lots.append(lot)
        return LotEvent(
            self.portfolio_id,
            lot.lot_id,
            "BUY_LOT_OPEN",
            trade_date,
            code,
            qty,
            qty,
            trade_date,
            available_date,
            unit_cost,
            fill_id,
        )

    def sell(
        self,
        *,
        trade_date: date,
        code: str,
        qty: int,
        cash_delta: Decimal,
        fill_id: str,
    ) -> list[LotEvent]:
        if qty <= 0 or cash_delta <= 0:
            raise PortfolioReconciliationError("invalid sell ledger mutation")
        if self.available_quantity(code) < qty:
            raise PortfolioReconciliationError("sell exceeds T+1 available quantity")
        self.cash += cash_delta
        remaining = qty
        events: list[LotEvent] = []
        for lot in self.lots:
            if lot.code != code or not lot.released or not lot.remaining_qty:
                continue
            allocated = min(remaining, lot.remaining_qty)
            lot.remaining_qty -= allocated
            remaining -= allocated
            events.append(
                LotEvent(
                    self.portfolio_id,
                    lot.lot_id,
                    "SELL_LOT_FIFO",
                    trade_date,
                    code,
                    -allocated,
                    lot.remaining_qty,
                    lot.acquired_date,
                    lot.available_date,
                    lot.unit_cost,
                    fill_id,
                )
            )
            if remaining == 0:
                break
        if remaining:
            raise PortfolioReconciliationError("FIFO allocation did not close sell")
        return events


def _known_at(session: date) -> str:
    return f"{session.isoformat()}T15:00:00+08:00"


def _portfolio_coroutine(
    *,
    config: PortfolioConfig,
    sessions: Sequence[date],
    decisions: Iterable[SignalDecision],
) -> Generator[date, Mapping[str, MarketBar], PortfolioRunResult]:
    sessions = tuple(sessions)
    if not sessions or sessions != tuple(sorted(set(sessions))):
        raise PortfolioInputError("sessions must be non-empty, unique and ascending")
    session_set = set(sessions)
    next_session = {
        session: sessions[index + 1] if index + 1 < len(sessions) else None
        for index, session in enumerate(sessions)
    }

    decision_rows = tuple(decisions)
    decision_ids = [row.decision_id for row in decision_rows]
    if len(decision_ids) != len(set(decision_ids)):
        raise PortfolioInputError("decision ids must be unique")
    decisions_by_date: dict[date, list[SignalDecision]] = {}
    for decision in decision_rows:
        if decision.reveal_date not in session_set:
            raise PortfolioInputError(
                "decision reveal_date is outside snapshot sessions"
            )
        decisions_by_date.setdefault(decision.reveal_date, []).append(decision)

    portfolio_id = config.portfolio_id
    ledger = _Ledger(config.initial_cash, portfolio_id)
    order_attempts: list[OrderAttempt] = []
    fills: list[FillRecord] = []
    lot_events: list[LotEvent] = []
    position_rows: list[PositionSnapshot] = []
    equity_rows: list[EquitySnapshot] = []
    blocked_rows: list[BlockedRecord] = []
    buys_by_date: dict[date, list[_PendingOrder]] = {}
    pending_sells: list[_PendingOrder] = []
    entry_scores: dict[str, Decimal] = {}
    marks: dict[str, tuple[Decimal, int]] = {}
    order_sequence = 0
    fill_sequence = 0
    blocked_sequence = 0

    def add_blocked(
        *,
        decision: SignalDecision,
        reason: BlockedReason,
        side: Side | None,
        disposition: str,
        trade_date: date | None = None,
        order: _PendingOrder | None = None,
        quality_mask: int = 0,
    ) -> None:
        nonlocal blocked_sequence
        blocked_sequence += 1
        blocked_rows.append(
            BlockedRecord(
                portfolio_id=portfolio_id,
                blocked_id=f"B{blocked_sequence:08d}",
                decision_date=decision.reveal_date,
                trade_date=trade_date,
                code=decision.code,
                side=side,
                order_id=order.order_id if order else None,
                attempt_no=order.attempt_no if order else None,
                reason=reason,
                disposition=disposition,
                quality_mask=quality_mask,
            )
        )

    def make_order(
        *,
        decision: SignalDecision,
        side: Side,
        requested_qty: int,
        target_trade_date: date,
        quality_mask: int,
    ) -> _PendingOrder:
        nonlocal order_sequence
        order_sequence += 1
        return _PendingOrder(
            order_id=f"O{order_sequence:08d}",
            decision=decision,
            side=side,
            requested_qty=requested_qty,
            target_trade_date=target_trade_date,
            score=decision.score,
            quality_mask=quality_mask,
        )

    def append_blocked_attempt(
        order: _PendingOrder,
        *,
        trade_date: date,
        check: LimitCheck | None,
        reason: BlockedReason,
        sell_pending: bool,
    ) -> None:
        quality = order.quality_mask | (check.quality_mask if check else 0)
        status = (
            OrderStatus.BLOCKED_PENDING if sell_pending else OrderStatus.BLOCKED_EXPIRED
        )
        order_attempts.append(
            OrderAttempt(
                portfolio_id,
                order.order_id,
                order.attempt_no,
                order.decision.reveal_date,
                trade_date,
                order.decision.code,
                order.side,
                order.requested_qty,
                0,
                config.combo_id,
                order.decision.source_signal_fact_ids,
                status,
                reason,
                _known_at(order.decision.reveal_date),
                "PERSIST_UNTIL_FILLED" if sell_pending else "DAY",
                quality,
            )
        )
        add_blocked(
            decision=order.decision,
            reason=reason,
            side=order.side,
            disposition="PENDING_RETRY" if sell_pending else "EXPIRED",
            trade_date=trade_date,
            order=order,
            quality_mask=quality,
        )

    def execute(order: _PendingOrder, trade_date: date) -> bool:
        """Return True when a DAY order is done or a sell has filled."""

        nonlocal fill_sequence
        order.attempt_no += 1
        bar = bar_map.get(order.decision.code)
        check = config.limit_schedule.check(bar, order.side)
        if not check.tradable:
            blocked_reason = check.blocked_reason
            if blocked_reason is None:
                raise PortfolioReconciliationError("blocked limit check has no reason")
            append_blocked_attempt(
                order,
                trade_date=trade_date,
                check=check,
                reason=blocked_reason,
                sell_pending=order.side is Side.SELL,
            )
            return order.side is Side.BUY

        if bar is None or bar.raw_open is None:
            raise PortfolioReconciliationError("tradable check returned an invalid bar")
        if order.side is Side.BUY and ledger.quantity(order.decision.code):
            append_blocked_attempt(
                order,
                trade_date=trade_date,
                check=check,
                reason=BlockedReason.ALREADY_HELD,
                sell_pending=False,
            )
            return True
        if order.side is Side.BUY and len(ledger.codes()) >= config.max_holdings:
            append_blocked_attempt(
                order,
                trade_date=trade_date,
                check=check,
                reason=BlockedReason.MAX_HOLDINGS,
                sell_pending=False,
            )
            return True

        fill_price = config.slippage_model.apply(bar.raw_open, order.side)
        qty = order.requested_qty
        lot_size, lot_quality = config.lot_size_for(order.decision.code)
        if order.side is Side.BUY:
            while qty >= lot_size:
                notional = fill_price * qty
                fee = config.fee_schedule.calculate(
                    trade_date=trade_date,
                    code=order.decision.code,
                    side=order.side,
                    notional=notional,
                )
                if notional + fee.total_fee <= ledger.cash:
                    break
                qty -= lot_size
            if qty < lot_size:
                append_blocked_attempt(
                    order,
                    trade_date=trade_date,
                    check=check,
                    reason=BlockedReason.INSUFFICIENT_CASH,
                    sell_pending=False,
                )
                return True
        else:
            available = ledger.available_quantity(order.decision.code)
            if available < qty:
                raise PortfolioReconciliationError(
                    "pending sell exceeds available long position"
                )
            notional = fill_price * qty
            fee = config.fee_schedule.calculate(
                trade_date=trade_date,
                code=order.decision.code,
                side=order.side,
                notional=notional,
            )

        notional = fill_price * qty
        fee = config.fee_schedule.calculate(
            trade_date=trade_date,
            code=order.decision.code,
            side=order.side,
            notional=notional,
        )
        cash_delta = (
            -(notional + fee.total_fee)
            if order.side is Side.BUY
            else notional - fee.total_fee
        )
        fill_sequence += 1
        fill_id = f"F{fill_sequence:08d}"
        quality = order.quality_mask | lot_quality | check.quality_mask
        fill = FillRecord(
            portfolio_id,
            fill_id,
            order.order_id,
            trade_date,
            order.decision.code,
            order.side,
            qty,
            bar.raw_open,
            fill_price - bar.raw_open,
            fill_price,
            notional,
            fee.commission,
            fee.minimum_commission_adjustment,
            fee.stamp_tax,
            fee.transfer_fee,
            fee.total_fee,
            cash_delta,
            fee.fee_schedule_id,
            fee.stamp_tax_rule_id,
            fee.transfer_fee_rule_id,
            check.limit_rule_id,
            check.confidence,
            config.slippage_model.model_id,
        )
        fills.append(fill)
        if order.side is Side.BUY:
            available_date = next_session[trade_date] or date.max
            lot_events.append(
                ledger.buy(
                    trade_date=trade_date,
                    available_date=available_date,
                    code=order.decision.code,
                    qty=qty,
                    unit_cost=(notional + fee.total_fee) / qty,
                    cash_delta=cash_delta,
                    fill_id=fill_id,
                    quality_mask=quality,
                )
            )
            entry_scores[order.decision.code] = order.score
        else:
            lot_events.extend(
                ledger.sell(
                    trade_date=trade_date,
                    code=order.decision.code,
                    qty=qty,
                    cash_delta=cash_delta,
                    fill_id=fill_id,
                )
            )
            if ledger.quantity(order.decision.code) == 0:
                entry_scores.pop(order.decision.code, None)
        order_attempts.append(
            OrderAttempt(
                portfolio_id,
                order.order_id,
                order.attempt_no,
                order.decision.reveal_date,
                trade_date,
                order.decision.code,
                order.side,
                order.requested_qty,
                qty,
                config.combo_id,
                order.decision.source_signal_fact_ids,
                (
                    OrderStatus.FILLED
                    if qty == order.requested_qty
                    else OrderStatus.PARTIALLY_FILLED
                ),
                None,
                _known_at(order.decision.reveal_date),
                "PERSIST_UNTIL_FILLED" if order.side is Side.SELL else "DAY",
                quality,
            )
        )
        return True

    previous_equity = config.initial_cash
    peak_equity = config.initial_cash
    for session in sessions:
        bar_map = yield session
        if any(
            code != bar.code or bar.session != session for code, bar in bar_map.items()
        ):
            raise PortfolioInputError("session bar batch contains a mismatched key")
        lot_events.extend(ledger.release(session))
        start_cash = ledger.cash
        start_qty = ledger.quantities()
        fill_start = len(fills)

        remaining_sells: list[_PendingOrder] = []
        for order in sorted(pending_sells, key=lambda item: item.order_id):
            if order.target_trade_date != session:
                remaining_sells.append(order)
                continue
            complete = execute(order, session)
            if not complete:
                following = next_session[session]
                if following is not None:
                    order.target_trade_date = following
                remaining_sells.append(order)
        pending_sells = remaining_sells

        for order in sorted(
            buys_by_date.pop(session, []),
            key=lambda item: (-item.score, item.decision.code, item.order_id),
        ):
            execute(order, session)

        day_fills = fills[fill_start:]
        positions_today: list[PositionSnapshot] = []
        for code in sorted(ledger.codes()):
            valuation_bar = bar_map.get(code)
            if (
                valuation_bar is not None
                and valuation_bar.raw_close is not None
                and valuation_bar.raw_close > 0
            ):
                mark = valuation_bar.raw_close
                stale_sessions = 0
            elif code in marks:
                mark, previous_stale = marks[code]
                stale_sessions = previous_stale + 1
            else:
                raise PortfolioReconciliationError(
                    f"no raw close available to value {code} on {session}"
                )
            marks[code] = (mark, stale_sessions)
            qty = ledger.quantity(code)
            cost_basis = ledger.cost_basis(code)
            market_value = mark * qty
            quality = ledger.quality_mask(code)
            if stale_sessions:
                quality |= QUALITY_STALE_CLOSE
            positions_today.append(
                PositionSnapshot(
                    portfolio_id,
                    session,
                    code,
                    qty,
                    ledger.available_quantity(code),
                    cost_basis / qty,
                    mark,
                    market_value,
                    market_value - cost_basis,
                    stale_sessions,
                    quality,
                )
            )
        position_rows.extend(positions_today)

        market_value = sum((row.market_value for row in positions_today), Decimal("0"))
        equity = ledger.cash + market_value
        cash_delta = sum((fill.cash_delta for fill in day_fills), Decimal("0"))
        cash_error = ledger.cash - (start_cash + cash_delta)
        balance_error = equity - (ledger.cash + market_value)
        expected_qty = dict(start_qty)
        for fill in day_fills:
            signed = fill.qty if fill.side is Side.BUY else -fill.qty
            expected_qty[fill.code] = expected_qty.get(fill.code, 0) + signed
        expected_qty = {code: qty for code, qty in expected_qty.items() if qty}
        quantity_ok = expected_qty == ledger.quantities()
        tolerance = max(
            config.reconciliation_floor,
            abs(equity) * config.reconciliation_relative,
        )
        if (
            abs(cash_error) > tolerance
            or abs(balance_error) > tolerance
            or not quantity_ok
            or ledger.cash < -tolerance
        ):
            raise PortfolioReconciliationError(
                f"daily reconciliation failed on {session.isoformat()}"
            )

        gross_notional = sum((fill.gross_notional for fill in day_fills), Decimal("0"))
        fees_today = sum((fill.total_fee for fill in day_fills), Decimal("0"))
        daily_return = equity / previous_equity - Decimal("1")
        cumulative_return = equity / config.initial_cash - Decimal("1")
        turnover = gross_notional / previous_equity
        gross_exposure = market_value / equity if equity else Decimal("0")
        peak_equity = max(peak_equity, equity)
        drawdown = equity / peak_equity - Decimal("1")
        equity_rows.append(
            EquitySnapshot(
                portfolio_id,
                session,
                ledger.cash,
                market_value,
                equity,
                daily_return,
                cumulative_return,
                turnover,
                gross_exposure,
                fees_today,
                drawdown,
                len(positions_today),
                balance_error,
                cash_error,
                quantity_ok,
                tolerance,
            )
        )
        previous_equity = equity

        next_date = next_session[session]
        grouped: dict[str, list[SignalDecision]] = {}
        for decision in decisions_by_date.get(session, []):
            grouped.setdefault(decision.code, []).append(decision)
        pending_exit_codes = {order.decision.code for order in pending_sells}
        for code in sorted(grouped):
            rows = grouped[code]
            negatives = sorted(
                (row for row in rows if row.direction < 0),
                key=lambda row: row.decision_id,
            )
            positives = sorted(
                (row for row in rows if row.direction > 0),
                key=lambda row: (-row.score, row.decision_id),
            )
            if negatives:
                chosen = negatives[0]
                for duplicate in negatives[1:]:
                    add_blocked(
                        decision=duplicate,
                        reason=BlockedReason.DUPLICATE_NEGATIVE,
                        side=Side.SELL,
                        disposition="DEDUPLICATED",
                    )
                for positive in positives:
                    add_blocked(
                        decision=positive,
                        reason=BlockedReason.NEGATIVE_SIGNAL_VETO,
                        side=Side.BUY,
                        disposition="VETOED_AT_DECISION_CLOSE",
                    )
                if ledger.quantity(code) == 0:
                    add_blocked(
                        decision=chosen,
                        reason=BlockedReason.NEGATIVE_SIGNAL_NO_POSITION,
                        side=Side.SELL,
                        disposition="NO_LONG_POSITION",
                    )
                elif code in pending_exit_codes:
                    add_blocked(
                        decision=chosen,
                        reason=BlockedReason.PENDING_EXIT,
                        side=Side.SELL,
                        disposition="DEDUPLICATED",
                    )
                elif next_date is None:
                    add_blocked(
                        decision=chosen,
                        reason=BlockedReason.NO_NEXT_SESSION,
                        side=Side.SELL,
                        disposition="NO_TARGET_SESSION",
                    )
                else:
                    sell_order = make_order(
                        decision=chosen,
                        side=Side.SELL,
                        requested_qty=ledger.quantity(code),
                        target_trade_date=next_date,
                        quality_mask=ledger.quality_mask(code),
                    )
                    pending_sells.append(sell_order)
                    pending_exit_codes.add(code)
                continue

            if not positives:
                continue
            chosen = positives[0]
            for duplicate in positives[1:]:
                add_blocked(
                    decision=duplicate,
                    reason=BlockedReason.DUPLICATE_POSITIVE,
                    side=Side.BUY,
                    disposition="DEDUPLICATED",
                )
            if ledger.quantity(code):
                add_blocked(
                    decision=chosen,
                    reason=BlockedReason.ALREADY_HELD,
                    side=Side.BUY,
                    disposition="NO_PYRAMIDING",
                )
                continue
            if code in pending_exit_codes:
                add_blocked(
                    decision=chosen,
                    reason=BlockedReason.PENDING_EXIT,
                    side=Side.BUY,
                    disposition="EXIT_HAS_PRIORITY",
                )
                continue
            if next_date is None:
                add_blocked(
                    decision=chosen,
                    reason=BlockedReason.NO_NEXT_SESSION,
                    side=Side.BUY,
                    disposition="NO_TARGET_SESSION",
                )
                continue
            decision_bar = bar_map.get(code)
            if decision_bar is None:
                add_blocked(
                    decision=chosen,
                    reason=BlockedReason.NO_BAR,
                    side=Side.BUY,
                    disposition="CANNOT_SIZE_AT_CLOSE",
                )
                continue
            if decision_bar.raw_volume is None or decision_bar.raw_volume <= 0:
                add_blocked(
                    decision=chosen,
                    reason=BlockedReason.SUSPENDED,
                    side=Side.BUY,
                    disposition="CANNOT_SIZE_AT_CLOSE",
                )
                continue
            if decision_bar.raw_close is None or decision_bar.raw_close <= 0:
                add_blocked(
                    decision=chosen,
                    reason=BlockedReason.INVALID_CLOSE,
                    side=Side.BUY,
                    disposition="INVALID_RAW_CLOSE",
                )
                continue
            lot_size, lot_quality = config.lot_size_for(code)
            target_value = equity * config.target_weight
            requested_qty = (
                int(target_value / decision_bar.raw_close / lot_size) * lot_size
            )
            if requested_qty < lot_size:
                add_blocked(
                    decision=chosen,
                    reason=BlockedReason.BELOW_ONE_LOT,
                    side=Side.BUY,
                    disposition="EXPIRED_AT_DECISION_CLOSE",
                    quality_mask=lot_quality,
                )
                continue
            if config.replacement_policy == "SCORE_REPLACE_WEAKEST_HOLDING":
                held = ledger.codes()
                projected = len(held - pending_exit_codes) + len(
                    buys_by_date.get(next_date, [])
                )
                if projected >= config.max_holdings:
                    candidates = sorted(
                        (entry_scores.get(item, Decimal("0")), item)
                        for item in held
                        if item not in pending_exit_codes
                    )
                    if candidates and candidates[0][0] < chosen.score:
                        weakest_code = candidates[0][1]
                        replacement = SignalDecision(
                            decision_id=(
                                f"replacement:{chosen.decision_id}:{weakest_code}"
                            ),
                            reveal_date=session,
                            code=weakest_code,
                            direction=-1,
                            score=chosen.score,
                            source_signal_fact_ids=chosen.source_signal_fact_ids,
                        )
                        pending_sells.append(
                            make_order(
                                decision=replacement,
                                side=Side.SELL,
                                requested_qty=ledger.quantity(weakest_code),
                                target_trade_date=next_date,
                                quality_mask=ledger.quality_mask(weakest_code),
                            )
                        )
                        pending_exit_codes.add(weakest_code)
            buys_by_date.setdefault(next_date, []).append(
                make_order(
                    decision=chosen,
                    side=Side.BUY,
                    requested_qty=requested_qty,
                    target_trade_date=next_date,
                    quality_mask=lot_quality,
                )
            )

    approximations = (
        "Historical ST, IPO no-limit windows and delisting states are incomplete; default limit rules are APPROXIMATE.",
        "Pre-2015 transfer fees and the earliest stamp-tax periods are explicit schedule approximations; inspect rule ids.",
        "This fixture does not book corporate actions; raw-price share quantity continuity is assumed.",
        "Opening-auction volume capacity and partial market fills are not modeled; fills are deterministic all-or-affordable-lot.",
    )
    return PortfolioRunResult(
        portfolio_id=portfolio_id,
        orders=tuple(order_attempts),
        fills=tuple(fills),
        lots=tuple(lot_events),
        positions=tuple(position_rows),
        equity=tuple(equity_rows),
        blocked=tuple(blocked_rows),
        pending_orders=tuple(
            PendingOrderSnapshot(
                portfolio_id=portfolio_id,
                order_id=order.order_id,
                decision_date=order.decision.reveal_date,
                target_trade_date=order.target_trade_date,
                code=order.decision.code,
                side=order.side,
                requested_qty=order.requested_qty,
                reason_combo_id=config.combo_id,
                source_signal_fact_ids=order.decision.source_signal_fact_ids,
                attempt_no=order.attempt_no,
                known_at=_known_at(order.decision.reveal_date),
                quality_mask=order.quality_mask,
            )
            for order in sorted(pending_sells, key=lambda row: row.order_id)
        ),
        pending_sell_order_ids=tuple(
            order.order_id
            for order in sorted(pending_sells, key=lambda row: row.order_id)
        ),
        institutional_approximations=approximations,
    )


def _session_bar_map(session: date, bars: Iterable[MarketBar]) -> dict[str, MarketBar]:
    result: dict[str, MarketBar] = {}
    for bar in bars:
        if bar.session != session:
            raise PortfolioInputError("bar session differs from batch session")
        if bar.code in result:
            raise PortfolioInputError(f"duplicate bar {(session, bar.code)}")
        result[bar.code] = bar
    return result


def run_portfolios_shared(
    *,
    configs: Iterable[PortfolioConfig],
    sessions: Iterable[date],
    session_bars: Iterable[tuple[date, Iterable[MarketBar]]],
    decisions_by_combo: Mapping[str, Iterable[SignalDecision]],
) -> dict[str, PortfolioRunResult]:
    """Run many portfolios from one chronological market-data scan.

    Only the current session is materialized as ``MarketBar`` objects.  Every
    active portfolio receives the same immutable mapping before it advances to
    the next session, so N frozen combinations never trigger N full-market
    scans.
    """

    ordered_sessions = tuple(sessions)
    if not ordered_sessions or ordered_sessions != tuple(sorted(set(ordered_sessions))):
        raise PortfolioInputError("sessions must be non-empty, unique and ascending")
    config_rows = tuple(configs)
    combo_ids = [config.combo_id for config in config_rows]
    if not config_rows or len(combo_ids) != len(set(combo_ids)):
        raise PortfolioInputError("configs require unique combo ids")
    missing = sorted(set(combo_ids) - set(decisions_by_combo))
    extra = sorted(set(decisions_by_combo) - set(combo_ids))
    if missing or extra:
        raise PortfolioInputError(
            f"decision mapping mismatch; missing={missing}, extra={extra}"
        )

    machines: dict[
        str, Generator[date, Mapping[str, MarketBar], PortfolioRunResult]
    ] = {}
    for config in config_rows:
        machine = _portfolio_coroutine(
            config=config,
            sessions=ordered_sessions,
            decisions=decisions_by_combo[config.combo_id],
        )
        expected = next(machine)
        if expected != ordered_sessions[0]:
            raise PortfolioReconciliationError("portfolio clock failed to initialize")
        machines[config.combo_id] = machine

    batches = iter(session_bars)
    results: dict[str, PortfolioRunResult] = {}
    for index, session in enumerate(ordered_sessions):
        try:
            batch_session, raw_bars = next(batches)
        except StopIteration as exc:
            raise PortfolioInputError(
                f"market stream ended before {session.isoformat()}"
            ) from exc
        if batch_session != session:
            raise PortfolioInputError(
                f"market stream expected {session.isoformat()}, got {batch_session}"
            )
        bars = _session_bar_map(session, raw_bars)
        is_last = index + 1 == len(ordered_sessions)
        for combo_id in combo_ids:
            machine = machines[combo_id]
            try:
                next_expected = machine.send(bars)
            except StopIteration as completed:
                if not is_last:
                    raise PortfolioReconciliationError(
                        "portfolio clock completed before the market stream"
                    ) from completed
                results[combo_id] = completed.value
            else:
                if is_last or next_expected != ordered_sessions[index + 1]:
                    raise PortfolioReconciliationError(
                        "portfolio and shared market clocks diverged"
                    )
    try:
        extra_batch = next(batches)
    except StopIteration:
        pass
    else:
        raise PortfolioInputError(
            f"market stream has an extra session: {extra_batch[0]}"
        )
    return {combo_id: results[combo_id] for combo_id in combo_ids}


def run_portfolio(
    *,
    config: PortfolioConfig,
    sessions: Iterable[date],
    bars: Iterable[MarketBar],
    decisions: Iterable[SignalDecision],
) -> PortfolioRunResult:
    """Compatibility wrapper for the fixture API.

    Production artifact builds use :func:`run_portfolios_shared`; this wrapper
    intentionally favors compatibility with unordered small fixture inputs.
    """

    ordered_sessions = tuple(sessions)
    grouped: dict[date, list[MarketBar]] = {session: [] for session in ordered_sessions}
    for bar in bars:
        try:
            grouped[bar.session].append(bar)
        except KeyError as exc:
            raise PortfolioInputError(
                "bar session is outside snapshot sessions"
            ) from exc
    return run_portfolios_shared(
        configs=(config,),
        sessions=ordered_sessions,
        session_bars=((session, grouped[session]) for session in ordered_sessions),
        decisions_by_combo={config.combo_id: decisions},
    )[config.combo_id]
