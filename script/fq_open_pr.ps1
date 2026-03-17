[CmdletBinding()]
param(
    [string]$BaseRef,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$GhArgs
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$preflightScript = Join-Path $repoRoot "script\fq_local_preflight.ps1"

$preflightArgs = @("-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", $preflightScript, "-Mode", "Ensure")
if (-not [string]::IsNullOrWhiteSpace($BaseRef)) {
    $preflightArgs += @("-BaseRef", $BaseRef)
}

& powershell.exe @preflightArgs
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

$ghCommand = Get-Command gh -ErrorAction SilentlyContinue
if (-not $ghCommand) {
    throw "gh not found in PATH."
}

& $ghCommand.Source @("pr", "create") $GhArgs
exit $LASTEXITCODE
