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
    @{ Name = 'cleanup request registration rule'; Pattern = 'register a cleanup request' },
    @{ Name = 'host finalizer rule'; Pattern = 'host cleanup finalizer' },
    @{ Name = 'watch guardrail'; Pattern = 'Do not use `gh pr checks --watch`, `gh run watch`, or custom polling loops with `Start-Sleep`' },
    @{ Name = 'one-shot check rule'; Pattern = 'Do a one-shot check and then end the turn; let the orchestrator schedule the next turn instead of blocking inside the current session' },
    @{ Name = 'cleanup request script rule'; Pattern = 'Register cleanup only through `runtime/symphony/scripts/request_freshquant_symphony_cleanup\.ps1`' },
    @{ Name = 'workspace delete guardrail'; Pattern = 'Do not run `Remove-Item`, `git worktree remove`, or other direct workspace-deletion commands against the task workspace from the Codex session' },
    @{ Name = 'stay in merging during cleanup retry rule'; Pattern = 'Do not move a merged issue to `Blocked` only because cleanup or host-side retries still need to finish; keep it in `Merging` unless there is a real external blocker' }
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
