"""Step 4: filter exploration on /tmp/regime_events.parquet (buy direction).

Filters tested: price bands, first occurrence, dual-model co-trigger, signal-burst days,
regime interaction, and combined recipes. Metric: win rate + mean net (fee 0.4% incl.) at h30/60/90.
"""
import json

import numpy as np
import pandas as pd

df = pd.read_parquet("/tmp/regime_events.parquet")
df = df[df["direction"] == 1].copy()
df["trigger"] = df["primary_trigger_semantic"]
df["day"] = df["reveal_date"].dt.date

# features
co = df.groupby(["code", "day", "trigger"])["model_code"].transform("nunique")
df["co2"] = co >= 2
df["co3"] = co >= 3
day_n = df.groupby("day")["code"].transform("size")
df["burst"] = day_n > 100  # 18-model universe is larger; use quantile too
df["crowdq"] = pd.qcut(day_n, [0, .25, .5, .75, 1.0], labels=["Q1", "Q2", "Q3", "Q4"])
df["band"] = pd.cut(df["raw_entry_open"], [0, 5, 10, 20, 1e9], labels=["<5", "5-10", "10-20", ">20"])
df["first"] = df["occurrence"] == 1

HS = ["ret30", "ret60", "ret90"]

def stat(sub):
    r = {}
    for h in HS:
        v = sub[h].dropna()
        r[h] = {"n": int(len(v)), "win": round(float((v > 0).mean()) * 100, 1) if len(v) else None,
                "net": round(float(v.mean()) * 100, 2) if len(v) else None}
    return r

out = {}
out["baseline_all"] = stat(df)
for reg in ["UP", "DOWN", "SIDEWAYS"]:
    out[f"baseline_{reg}"] = stat(df[df["regime"] == reg])

feats = {"co2": df["co2"], "co3": df["co3"], "first": df["first"], "burst": df["burst"]}
for name, m in feats.items():
    out[f"f_{name}"] = stat(df[m])
    out[f"f_not_{name}"] = stat(df[~m])
for b, sub in df.groupby("band", observed=True):
    out[f"band_{b}"] = stat(sub)
for q, sub in df.groupby("crowdq", observed=True):
    out[f"crowd_{q}"] = stat(sub)

# regime x key filters
for reg in ["UP", "DOWN", "SIDEWAYS"]:
    r = df[df["regime"] == reg]
    out[f"{reg}_co2"] = stat(r[r["co2"]])
    out[f"{reg}_burst"] = stat(r[r["burst"]])
    out[f"{reg}_lowprice"] = stat(r[r["raw_entry_open"] < 10])

# combined recipes
rec = {}
rec["co2+first"] = df[df["co2"] & df["first"]]
rec["co2+lowprice"] = df[df["co2"] & (df["raw_entry_open"] < 10)]
rec["co2+burst"] = df[df["co2"] & df["burst"]]
rec["co3+burst"] = df[df["co3"] & df["burst"]]
rec["co2+first+lowprice"] = df[df["co2"] & df["first"] & (df["raw_entry_open"] < 10)]
rec["co2+burst+lowprice"] = df[df["co2"] & df["burst"] & (df["raw_entry_open"] < 10)]
rec["DOWN+co2+burst"] = df[(df["regime"] == "DOWN") & df["co2"] & df["burst"]]
rec["SIDEWAYS+co2+burst"] = df[(df["regime"] == "SIDEWAYS") & df["co2"] & df["burst"]]
for k, sub in rec.items():
    out["recipe_" + k] = stat(sub)

# per trigger, per era robustness of best recipe
best = df[df["co2"] & df["burst"]]
out["best_pre2020"] = stat(best[best["reveal_date"] < "2020-01-01"])
out["best_post2020"] = stat(best[best["reveal_date"] >= "2020-01-01"])
for t in ["ENGULFING", "STRONG_FRACTAL"]:
    out[f"best_{t}"] = stat(best[best["trigger"] == t])

# top models under best recipe (h60)
tm = []
for m, g in best.groupby("model_code"):
    v = g["ret60"].dropna()
    if len(v) >= 100:
        tm.append({"model": m, "n": int(len(v)), "win60": round(float((v > 0).mean()) * 100, 1),
                   "net60": round(float(v.mean()) * 100, 2)})
out["best_models_h60"] = sorted(tm, key=lambda x: -x["win60"])

with open("/tmp/regime_filters.json", "w") as fp:
    json.dump(out, fp)
print("WROTE", len(df))
