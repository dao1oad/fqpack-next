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
    @{ Name = 'follow-up issue only rule'; Pattern = 'When code repair is needed,\s*only create a follow-up issue for the next Symphony round' },
    @{ Name = 'no repair PR rule'; Pattern = 'Do not create a repair PR directly from the global automation' },
    @{ Name = 'dedupe rule'; Pattern = 'Deduplicate follow-up issues by `Source Issue \+ Symptom Class` before creating a new one' },
    @{ Name = 'done guardrail'; Pattern = 'Close the original issue only after `deploy \+ health check \+ cleanup` are complete and no open follow-up issue still blocks `Done`' }
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
