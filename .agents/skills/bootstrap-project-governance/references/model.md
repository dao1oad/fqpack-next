# Autonomous Governance Model

## Authority boundary

`.governance/project.json` is the startup contract. `AUTONOMY_STARTED` freezes the canonical SHA-256 digest of the complete file, including preflight facts, Agent authority, fallbacks, budgets, and final claims.

Record credential and dependency readiness as status or identifiers only. Secret values stay in the project's secret store.

`.governance/work.json` is the rolling implementation plan. `AUTONOMY_STARTED` freezes every `requiredForFinal` item, its minimum `gateRefs` and `pathScopes`, and the complete specification of every referenced Gate. The Agent may add optional work, reorder buckets, and revise explicitly non-required soft Gates. A permitted soft-Gate change invalidates only evidence bound to the older Gate digest.

`.governance/events.jsonl` and `.governance/runs/` are append-only machine facts. `.governance/board.html` is a deterministic read-only projection.

## Minimal project contract

Keep the scaffold's `interactionPolicy` and `agentAuthority`. Fill the project-specific portions as follows:

```json
{
  "outcome": "A concrete observable result",
  "nonGoals": ["Explicit excluded scope"],
  "hardConstraints": ["A fixed boundary"],
  "budgets": {
    "deadlineAt": null,
    "maxCheckRuns": 40,
    "maxStopContinuations": 20,
    "maxNoProgressStops": 3,
    "sameFailureLimit": 2
  },
  "preflight": {
    "goalAndBoundariesConfirmed": true,
    "repositoryRootVerified": true,
    "credentialsAndPermissionsVerified": true,
    "externalDependenciesProbed": true,
    "fallbacksDefined": true,
    "budgetsConfirmed": true,
    "finalAcceptanceConfirmed": true,
    "hookTrustReviewed": true
  },
  "fallbacks": [
    {"when": "REAL_CHAIN_NOT_READY", "action": "CONTINUE_INDEPENDENT_V0_V1_WORK"}
  ],
  "finalAcceptance": {
    "claims": [
      {
        "id": "CLAIM-001",
        "description": "The end-to-end outcome",
        "itemRef": "WI-001",
        "gateRef": "e2e-real",
        "level": "V2",
        "dataMode": "real"
      }
    ]
  }
}
```

Keep all other scaffold fields. Numerical values above illustrate the shape; choose project budgets during startup grilling.

## Minimal rolling plan

```json
{
  "schemaVersion": 1,
  "revision": 1,
  "gates": [
    {
      "id": "e2e-real",
      "level": "V2",
      "dataMode": "real",
      "command": ["python3", "-m", "pytest", "tests/e2e"],
      "commandWindows": ["py", "-3", "-m", "pytest", "tests/e2e"],
      "cwd": ".",
      "subjectPaths": ["src/**", "tests/e2e/**"],
      "timeoutSeconds": 900,
      "maxAgeSeconds": null
    }
  ],
  "items": [
    {
      "id": "WI-001",
      "title": "Minimum vertical slice",
      "bucket": "NOW",
      "pathScopes": ["src/**"],
      "gateRefs": ["e2e-real"],
      "requiredForFinal": true,
      "nextCheckpoint": "Real-chain E2E passes"
    }
  ]
}
```

Buckets are `NOW`, `NEXT`, and `LATER`. Levels are `V0`, `V1`, and `V2`. Data modes are `mock`, `fixture`, `synthetic`, and `real`. Set `requiredForFinal` explicitly on every item; exploratory NEXT/LATER items normally use `false`. A work item with no Gate needs a non-empty `verificationExemption`.

## Lifecycle

| State | Derivation |
| --- | --- |
| `READY` | Readiness passes and autonomy has not started |
| `RUNNING` | `AUTONOMY_STARTED` exists and no stronger runtime state is active |
| `REPLANNING` | `REPLAN_STARTED` is not closed by `REPLAN_FINISHED` |
| `DEGRADED` | A degradation or fallback is active |
| `EXHAUSTED` | A locked resource budget is reached |
| `COMPLETED` | Required implementation, current checks, and final claims pass |

Terminal state wins over runtime state. `COMPLETED` wins when completion and exhaustion become eligible on the same evaluation.

## Independent dimensions

- Work: `planned`, `in_progress`, `implemented`, `deferred`.
- Verification: `missing`, `passed`, `failed`, `stale`.
- Final claim: evaluated separately from work and intermediate checks.

A fixture pass proves only its declared level and data mode. A V2 claim that requires `real` accepts only a current real-data Gate run.

## Evidence identity

A current run matches all of:

- work item and Gate;
- relevant source-content digest;
- Gate specification digest;
- locked project-contract digest;
- governance runner digest;
- declared data mode;
- optional maximum age.

The runner identity is a deliberate evidence-protocol digest rather than the complete runtime file hash. Host adapters and board-only releases retain it; changes to Gate execution or evidence identity must bump it so prior runs become stale.

The latest matching failure takes precedence over an earlier pass. If a check mutates its own subject files, the run is recorded as `stale_after_run`.

Each `CHECK_FINISHED` event seals its canonical `result.json` with `resultSha256` and repeats the run, item, Gate, outcome, Gate-spec, contract, and runner identities. Validation also requires the matching `stdout.log` and `stderr.log` hashes. Completion and Stop handling ignore evidence whose sealed record is missing or inconsistent.

## Stop behavior

Before `AUTONOMY_STARTED`, the active Codex or Devin Stop hook releases the turn. During autonomy it performs only deterministic inspection and board derivation; it does not run expensive tests. Missing or stale evidence produces an internal continuation with an exact `governance.py run` command. A failed Gate produces a route-change instruction. Terminal states release the turn after the final evidence report.

Devin CLI/Local loads `.devin/hooks.v1.json` as a host lifecycle hook. A Devin Cloud task that reaches a Windows checkout through XN runs the same protocol through the local gateway: after each Cloud terminal response, submit a Stop JSON payload to `tools/governance.py hook-stop`; `block` continues the same Cloud session with the returned reason and `approve` releases the result. Repository-local `.agents/skills` and `AGENTS.md` carry the Cloud-visible governance context.

## Board integrity

The generator hashes `project.json`, `work.json`, `events.jsonl`, and run result records in a fixed order. The digest is embedded in the HTML. Validation distinguishes stale derived input from direct HTML edits by comparing the full expected bytes.
