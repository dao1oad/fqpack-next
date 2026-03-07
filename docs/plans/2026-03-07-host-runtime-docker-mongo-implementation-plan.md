# Host Runtime Docker Mongo Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 将宿主机 broker、xtdata producer、xtdata consumer 的 Mongo 连接切到 Docker Mongo，并完成 Docker `freshquant` 初始化与 `params` 同步。

**Architecture:** 通过宿主机 supervisor 共享环境文件 `D:/fqpack/config/envs.conf` 统一覆盖 `mongodb.host/port`，再在 Docker Mongo 上运行一次初始化脚本，最后把宿主机 `params` 按 `code` upsert 过去并重启三个宿主机进程验证。

**Tech Stack:** Dynaconf、PyMongo、supervisor、Docker Compose、Python 3.12/3.10

---

### Task 1: 记录当前运行状态并备份参数

**Files:**
- Read: `D:/fqpack/config/envs.conf`
- Read: `D:/fqpack/config/supervisord.fqnext.conf`

**Step 1: 导出宿主机 `freshquant.params` 备份**

Run:

```powershell
@'
from pymongo import MongoClient
import json
from pathlib import Path

docs = list(MongoClient("mongodb://127.0.0.1:27017")["freshquant"]["params"].find({}, {"_id": 0}))
path = Path("runtime/backups/host-freshquant-params-2026-03-07.json")
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(docs, ensure_ascii=False, indent=2), encoding="utf-8")
print(path)
print(len(docs))
'@ | D:\fqpack\miniconda3\envs\fqkit\python.exe -
```

**Step 2: 记录三个宿主机进程当前状态**

Run:

```powershell
D:\fqpack\supervisord\supervisord.exe ctl -c D:\fqpack\config\supervisord.fqnext.conf status
```

### Task 2: 切换宿主机 Mongo 配置

**Files:**
- Modify: `D:/fqpack/config/envs.conf`

**Step 1: 添加 Docker Mongo 端口**

在 `envs.conf` 中加入：

```text
FRESHQUANT_MONGODB__PORT=27027
```

### Task 3: 初始化 Docker Mongo 并同步 params

**Files:**
- Read: `D:/fqpack/freshquant-2026.2.23/freshquant/initialize.py`

**Step 1: 在 Docker Mongo 环境下执行初始化**

Run:

```powershell
$env:FRESHQUANT_MONGODB__HOST="127.0.0.1"
$env:FRESHQUANT_MONGODB__PORT="27027"
D:\fqpack\miniconda3\envs\fqkit\python.exe -m freshquant.initialize --quiet
```

**Step 2: 同步宿主机 `params` 到 Docker `params`**

Run:

```powershell
@'
from pymongo import MongoClient

src = MongoClient("mongodb://127.0.0.1:27017")["freshquant"]["params"]
dst = MongoClient("mongodb://127.0.0.1:27027")["freshquant"]["params"]
count = 0
for doc in src.find({}, {"_id": 0}):
    dst.update_one({"code": doc["code"]}, {"$set": doc}, upsert=True)
    count += 1
print(count)
'@ | D:\fqpack\miniconda3\envs\fqkit\python.exe -
```

### Task 4: 重启宿主机进程并验证

**Files:**
- Read: `D:/fqpack/config/supervisord.fqnext.conf`

**Step 1: 重启三个宿主机进程**

Run:

```powershell
D:\fqpack\supervisord\supervisord.exe ctl -c D:\fqpack\config\supervisord.fqnext.conf restart fqnext_xtquant_broker fqnext_realtime_xtdata_producer fqnext_realtime_xtdata_consumer
```

**Step 2: 验证配置与功能**

Run:

```powershell
D:\fqpack\supervisord\supervisord.exe ctl -c D:\fqpack\config\supervisord.fqnext.conf status
```

Run:

```powershell
@'
from freshquant.config import settings
from freshquant.carnation.param import findParam
print(getattr(settings.mongodb, "host", None), getattr(settings.mongodb, "port", None))
print(findParam("xtquant"))
'@ | D:\fqpack\miniconda3\envs\fqkit\python.exe -
```

Run:

```powershell
@'
from pymongo import MongoClient
db = MongoClient("mongodb://127.0.0.1:27027")["freshquant"]
print(sorted(db.list_collection_names()))
print(db["params"].find_one({"code": "xtquant"}, {"_id": 0}))
'@ | D:\fqpack\miniconda3\envs\fqkit\python.exe -
```

**Step 3: 触发一次 broker 仓位同步并确认写入 Docker**

Run:

```powershell
@'
import json
from datetime import datetime
import redis

r = redis.Redis(host="127.0.0.1", port=6379, db=1, decode_responses=True)
payload = {"action": "sync-positions", "force": True, "fire_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
r.lpush("freshquant_order_queue", json.dumps(payload, ensure_ascii=False))
print(payload)
'@ | D:\fqpack\miniconda3\envs\fqkit\python.exe -
```

Run:

```powershell
@'
from pymongo import MongoClient
db = MongoClient("mongodb://127.0.0.1:27027")["freshquant"]
print(db["xt_positions"].count_documents({}))
print(list(db["xt_positions"].find({}, {"_id": 0, "stock_code": 1}).limit(5)))
'@ | D:\fqpack\miniconda3\envs\fqkit\python.exe -
```
