from freshquant.market_data.xtdata.coalesce import CoalescingScheduler


def test_coalesce_only_submits_latest_per_key():
    calls = []

    def submit_fn(key, latest):
        calls.append((key, latest))

    sched = CoalescingScheduler(max_inflight=10, submit_fn=submit_fn)

    k = ("sz000001", "1min")
    sched.update(k, 1)
    sched.update(k, 2)
    sched.update(k, 3)

    # first update submits immediately; next ones are pending only
    assert calls == [(k, 1)]
    assert sched.snapshot()["pending"] == 1

    # when done, it submits the latest only
    sched.mark_done(k)
    assert calls == [(k, 1), (k, 3)]


def test_global_inflight_limit_blocks_new_submits():
    calls = []

    def submit_fn(key, latest):
        calls.append((key, latest))

    sched = CoalescingScheduler(max_inflight=1, submit_fn=submit_fn)
    k1 = ("sz000001", "1min")
    k2 = ("sz000002", "1min")

    sched.update(k1, "a")
    sched.update(k2, "b")
    assert calls == [(k1, "a")]
    assert sched.snapshot()["pending"] == 1

    # finishing k1 allows k2 to submit
    sched.mark_done(k1)
    # k2 is now inflight (submitted with latest "b")
    assert calls == [(k1, "a"), (k2, "b")]
