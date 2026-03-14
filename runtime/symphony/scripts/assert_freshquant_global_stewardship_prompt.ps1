[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$PromptPath
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path $PromptPath)) {
    throw "Global Stewardship prompt file not found: $PromptPath"
}

$content = Get-Content -Path $PromptPath -Raw
$requiredPatterns = @(
    @{ Name = 'global stewardship scope rule'; Pattern = 'Inspect all open issues that are in `Global Stewardship`' },
    @{ Name = 'batch deploy rule'; Pattern = 'Batch deploy when safe and useful' },
    @{ Name = 'current main rule'; Pattern = 'Read the current `main` state before deciding any deployment batch' },
    @{ Name = 'deploy plan script rule'; Pattern = 'freshquant_deploy_plan\.py' },
    @{ Name = 'host runtime control rule'; Pattern = 'fqnext_host_runtime_ctl\.ps1' },
    @{ Name = 'symphony pre-sync rule'; Pattern = 'sync `runtime/symphony/\*\*` to the formal service root and restart `fq-symphony-orchestrator` before other deploy actions' },
    @{ Name = 'runtime ops baseline rule'; Pattern = 'If the current round performs a real deploy,\s*capture a runtime baseline before deploy' },
    @{ Name = 'runtime ops skip rule'; Pattern = 'If the current round does not perform a deploy,\s*do not run the runtime ops check' },
    @{ Name = 'runtime ops coverage rule'; Pattern = 'The runtime ops check must cover Docker container state,\s*host service state,\s*and host critical process state' },
    @{ Name = 'runtime ops failure guardrail'; Pattern = 'If the runtime ops check fails,\s*do not cleanup or close the original issue' },
    @{ Name = 'runtime ops script rule'; Pattern = 'check_freshquant_runtime_post_deploy\.ps1' },
    @{ Name = 'follow-up issue only rule'; Pattern = 'When code repair is needed,\s*only create a follow-up issue for the next Symphony round' },
    @{ Name = 'no repair PR rule'; Pattern = 'Do not create a repair PR directly from the global automation' },
    @{ Name = 'dedupe rule'; Pattern = 'Deduplicate follow-up issues by `Source Issue \+ Symptom Class` before creating a new one' },
    @{ Name = 'done guardrail'; Pattern = 'Close the original issue only after `deploy \+ health check \+ runtime ops check \+ cleanup` are complete and no open follow-up issue still blocks `Done`' }
)

$missing = @()
foreach ($entry in $requiredPatterns) {
    if ($content -notmatch $entry.Pattern) {
        $missing += $entry.Name
    }
}

if ($missing.Count -gt 0) {
    throw "Global Stewardship prompt contract failed for $PromptPath. Missing: $($missing -join ', ')"
}

Write-Host "[freshquant] global stewardship prompt contract OK: $PromptPath"
