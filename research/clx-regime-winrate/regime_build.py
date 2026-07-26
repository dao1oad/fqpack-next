"""Step 1-3: regime segmentation + h30/60/90 returns for 18 models x {ENGULFING, STRONG_FRACTAL}.

Regime rule (transparent, no lookahead): trailing 120-session index return r120 on signal reveal_date:
  r120 >= +10% -> UP; r120 <= -10% -> DOWN; else SIDEWAYS.
Entry: T+1 qfq open. Exit: qfq close 30/60/90 sessions after entry. Fee: 0.4% round trip.
Writes per-event parquet /tmp/regime_events.parquet + summary /tmp/regime_summary.json.
"""
import glob
import json

import numpy as np
import pandas as pd
import pyarrow.dataset as ds

SNAP = "/opt/clx-backtest/snapshots/cf579f3b0c081b7097de19eca8103c27f6643b64e5fa9ca6d7cb3e99491feec4"
EVENT_ROOT = "/opt/clx-backtest/events/clx-preview-99634853b/event-study/code_buckets"
FEE = 0.004
HORIZONS = [30, 60, 90]

# ---- regime segmentation on sh000001 ----
ix = pd.read_parquet("/tmp/sh000001.parquet").sort_values("trade_date").reset_index(drop=True)
ix["r120"] = ix["close"] / ix["close"].shift(120) - 1
ix["regime"] = np.select([ix["r120"] >= 0.10, ix["r120"] <= -0.10], ["UP", "DOWN"], default="SIDEWAYS")
ix.loc[ix["r120"].isna(), "regime"] = "SIDEWAYS"
regime_map = dict(zip(ix["trade_date"], ix["regime"]))
reg_counts = ix[ix["trade_date"] >= pd.Timestamp("2005-01-01").date()]["regime"].value_counts().to_dict()

# ---- calendar ----
cal = pd.read_parquet(SNAP + "/calendar/part-00000.parquet")
sess = dict(zip(cal["trade_date"], cal["session_no"]))

# ---- events ----
files = sorted(glob.glob(EVENT_ROOT + "/code_bucket=*/event_outcomes/reveal_year=*/part-*.parquet"))
dset = ds.dataset(files, format="parquet")
cols = ["code", "model_code", "direction", "reveal_date", "entry_trade_date", "entry_status",
        "split_boundary_status", "primary_trigger_semantic", "occurrence", "raw_entry_open"]
filt = ds.field("primary_trigger_semantic").isin(["ENGULFING", "STRONG_FRACTAL"])
ev = dset.to_table(columns=cols, filter=filt).to_pandas()
ev["reveal_date"] = pd.to_datetime(ev["reveal_date"])
ev = ev.sort_values("reveal_date").drop_duplicates(
    subset=["code", "model_code", "primary_trigger_semantic", "direction", "reveal_date"], keep="first")
ev = ev[(ev["split_boundary_status"] == "ELIGIBLE") & (ev["entry_status"] == "EXECUTABLE")]
ev = ev.dropna(subset=["entry_trade_date"]).copy()
n_events = len(ev)

# ---- bars: load qfq open/close for needed codes ----
need = set(ev["code"].unique())
bars = ds.dataset(sorted(glob.glob(SNAP + "/bars/code_bucket=*/code=*/part-*.parquet")), format="parquet")
bt = bars.to_table(columns=["code", "trade_date", "session_no", "qfq_open", "qfq_close"],
                   filter=ds.field("code").isin(list(need))).to_pandas()
max_sess = int(cal["session_no"].max())
price = {}
for code, g in bt.groupby("code"):
    a_open = np.full(max_sess + 1, np.nan)
    a_close = np.full(max_sess + 1, np.nan)
    sn = g["session_no"].to_numpy()
    a_open[sn] = g["qfq_open"].to_numpy()
    a_close[sn] = g["qfq_close"].to_numpy()
    price[code] = (a_open, a_close)

# ---- compute returns ----
ev["entry_sess"] = ev["entry_trade_date"].map(lambda d: sess.get(d, -1))
ev = ev[ev["entry_sess"] > 0]
rows_open = np.empty(len(ev)); rows_open[:] = np.nan
rets = {h: np.full(len(ev), np.nan) for h in HORIZONS}
codes_arr = ev["code"].to_numpy(); es = ev["entry_sess"].to_numpy()
for i in range(len(ev)):
    p = price.get(codes_arr[i])
    if p is None:
        continue
    eo = p[0][es[i]]
    if not np.isfinite(eo) or eo <= 0:
        continue
    rows_open[i] = eo
    for h in HORIZONS:
        xs = es[i] + h
        if xs <= max_sess:
            xc = p[1][xs]
            if np.isfinite(xc):
                rets[h][i] = xc / eo - 1
ev["qfq_entry_open"] = rows_open
for h in HORIZONS:
    ev[f"ret{h}"] = rets[h] * ev["direction"].to_numpy() - FEE
ev["regime"] = ev["reveal_date"].dt.date.map(regime_map).fillna("SIDEWAYS")

keep = ["code", "model_code", "primary_trigger_semantic", "direction", "reveal_date",
        "occurrence", "raw_entry_open", "regime"] + [f"ret{h}" for h in HORIZONS]
out_df = ev[keep].copy()
out_df.to_parquet("/tmp/regime_events.parquet", index=False)

# ---- summary: win rates per model x trigger x regime x horizon (both directions) ----
summary = {"regime_days_2005plus": reg_counts, "n_events": int(n_events), "n_priced": int(np.isfinite(rows_open).sum())}
tbl = []
for (m, t, d, r), g in out_df.groupby(["model_code", "primary_trigger_semantic", "direction", "regime"]):
    row = {"model": m, "trigger": t, "direction": int(d), "regime": r}
    for h in HORIZONS:
        v = g[f"ret{h}"].dropna()
        row[f"n{h}"] = int(len(v))
        row[f"win{h}"] = round(float((v > 0).mean()) * 100, 1) if len(v) else None
        row[f"net{h}"] = round(float(v.mean()) * 100, 2) if len(v) else None
    tbl.append(row)
summary["table"] = tbl
with open("/tmp/regime_summary.json", "w") as fp:
    json.dump(summary, fp)
print("WROTE", n_events, len(out_df), len(tbl))
