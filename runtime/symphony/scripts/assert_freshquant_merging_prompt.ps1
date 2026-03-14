[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$PromptPath
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path $PromptPath)) {
    throw "Merging prompt file not found: $PromptPath"
}

$content = Get-Content -Path $PromptPath -Raw
$requiredPatterns = @(
    @{ Name = 'watch guardrail'; Pattern = 'Do not use `gh pr checks --watch`, `gh run watch`, or custom polling loops with `Start-Sleep`' },
    @{ Name = 'one-shot check rule'; Pattern = 'Do a one-shot check and then end the turn; let the orchestrator schedule the next turn instead of blocking inside the current session' },
    @{ Name = 'structured handoff packet rule'; Pattern = 'Write the merge handoff comment as a structured handoff packet' },
    @{ Name = 'handoff source issue field'; Pattern = 'Source Issue' },
    @{ Name = 'handoff contract version field'; Pattern = 'Contract Version' },
    @{ Name = 'move to global stewardship rule'; Pattern = 'Move the issue to `Global Stewardship`' },
    @{ Name = 'no deploy in merging rule'; Pattern = 'Do not deploy, run health checks, or cleanup in the `Merging` session' },
    @{ Name = 'handoff candidate truth rule'; Pattern = 'Treat the handoff packet as candidate input for `Global Stewardship`, not as runtime-delivery truth' }
)

$missing = @()
foreach ($entry in $requiredPatterns) {
    if ($content -notmatch $entry.Pattern) {
        $missing += $entry.Name
    }
}

if ($missing.Count -gt 0) {
    throw "Merging prompt contract failed for $PromptPath. Missing: $($missing -join ', ')"
}

Write-Host "[freshquant] merging prompt contract OK: $PromptPath"
