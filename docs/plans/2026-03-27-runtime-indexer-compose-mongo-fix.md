# Runtime Indexer Compose Mongo Fix Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make `fq_runtime_indexer` always use Docker-internal Mongo/Redis addresses after any compose recreate, and add regression coverage so CI blocks future config drift.

**Architecture:** Keep the current host-vs-container configuration split. Host processes continue using `127.0.0.1:27027`, while Docker services that talk to Mongo/Redis must explicitly override those values in `docker/compose.parallel.yaml`. Add one compose policy test to enforce the override for `fq_runtime_indexer`, then document the failure signature in troubleshooting.

**Tech Stack:** Docker Compose YAML, pytest, Markdown docs.

---

### Task 1: Lock the regression with a failing compose policy test

**Files:**
- Modify: `freshquant/tests/test_docker_runtime_policy.py`

**Step 1: Write the failing test**

Add a test that extracts the `fq_runtime_indexer` service block from `docker/compose.parallel.yaml` and asserts it explicitly contains:
- `FRESHQUANT_MONGODB__HOST: fq_mongodb`
- `FRESHQUANT_MONGODB__PORT: "27017"`
- `MONGODB: fq_mongodb`
- `MONGODB_PORT: "27017"`

**Step 2: Run test to verify it fails**

Run: `py -3.12 -m uv run pytest freshquant/tests/test_docker_runtime_policy.py -q`

Expected: FAIL because the current `fq_runtime_indexer` block does not override Mongo.

### Task 2: Add the missing compose overrides

**Files:**
- Modify: `docker/compose.parallel.yaml`

**Step 1: Write minimal implementation**

Inside the `fq_runtime_indexer` service `environment:` block, add the four Mongo overrides listed above. Keep the existing ClickHouse and Redis overrides unchanged.

**Step 2: Run tests to verify they pass**

Run: `py -3.12 -m uv run pytest freshquant/tests/test_docker_runtime_policy.py -q`

Expected: PASS.

### Task 3: Document the runtime failure mode

**Files:**
- Modify: `docs/current/troubleshooting.md`

**Step 1: Update the Runtime Observability section**

Document that if `fq_runtime_indexer` is up but indexing stalls, inspect its env for `FRESHQUANT_MONGODB__HOST` / `MONGODB`. If they resolve to `127.0.0.1` inside the container, compose recreate picked up host defaults instead of container overrides, and the service must be recreated from fixed compose config.

**Step 2: Verify docs wording remains consistent**

Run: `py -3.12 -m uv run pytest freshquant/tests/test_runtime_observability_docs.py -q`

Expected: PASS.

### Task 4: Verify runtime behavior after compose recreate

**Files:**
- Modify: none

**Step 1: Recreate `fq_runtime_indexer` from compose**

Run: `powershell -ExecutionPolicy Bypass -File script/docker_parallel_compose.ps1 up -d --force-recreate fq_runtime_indexer`

**Step 2: Verify env and ingestion**

Run:
- `docker inspect fqnext_20260223-fq_runtime_indexer-1 --format "{{range .Config.Env}}{{println .}}{{end}}"`
- `docker exec fqnext_20260223-fq_runtime_indexer-1 sh -lc "/freshquant/.venv/bin/python - <<'PY' ... query_instrument_info('600104') ... PY"`
- Runtime API checks for `xt_producer`

Expected:
- container env shows `fq_mongodb` / `27017`
- symbol lookup returns quickly
- `xt_producer` heartbeat remains visible in Runtime Observability API
