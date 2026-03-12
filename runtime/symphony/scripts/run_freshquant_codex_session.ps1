[CmdletBinding()]
param(
    [string]$ServiceRoot = 'D:\fqpack\runtime\symphony-service'
)

$ErrorActionPreference = 'Stop'

function Resolve-CommandPath {
    param([Parameter(Mandatory = $true)][string]$Name)

    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if (-not $command) {
        throw "$Name not found in PATH."
    }

    return $command.Source
}

$workspacePath = (Get-Location).Path
$issueIdentifier = Split-Path -Leaf $workspacePath
$wrapperRoot = $ServiceRoot
$finalizerScript = Join-Path $PSScriptRoot 'invoke_freshquant_symphony_cleanup_finalizer.ps1'
$requestPath = Join-Path (Join-Path (Join-Path $ServiceRoot 'artifacts') 'cleanup-requests') "$issueIdentifier.json"
$codexPath = Resolve-CommandPath -Name 'codex'

Set-Location $wrapperRoot
Push-Location $workspacePath
try {
    & $codexPath --config shell_environment_policy.inherit=all app-server
    $codexExitCode = $LASTEXITCODE
}
finally {
    Pop-Location
    Set-Location $wrapperRoot
}

if ($codexExitCode -ne 0) {
    exit $codexExitCode
}

if (-not (Test-Path $requestPath)) {
    exit 0
}

& $finalizerScript -ServiceRoot $ServiceRoot -IssueIdentifier $issueIdentifier -WorkspacePath $workspacePath
exit $LASTEXITCODE
