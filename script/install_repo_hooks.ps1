[CmdletBinding()]
param(
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
)

$ErrorActionPreference = "Stop"

$hookPath = Join-Path $RepoRoot ".githooks"
$prePushHook = Join-Path $hookPath "pre-push"

if (-not (Test-Path $prePushHook)) {
    throw "Repo-managed pre-push hook not found: $prePushHook"
}

& git -C $RepoRoot config core.hooksPath .githooks
if ($LASTEXITCODE -ne 0) {
    throw "Failed to set core.hooksPath for repo: $RepoRoot"
}

Write-Host "[freshquant] repo hooks installed via core.hooksPath=.githooks"
