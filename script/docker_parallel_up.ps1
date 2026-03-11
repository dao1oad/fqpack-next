param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Services
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$composeScript = Join-Path $repoRoot "script\docker_parallel_compose.ps1"
$composeArgs = @("up", "-d", "--build")

if ($Services) {
    $composeArgs += $Services
}

& powershell -NoProfile -ExecutionPolicy Bypass -File $composeScript @composeArgs
exit $LASTEXITCODE
