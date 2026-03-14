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

function Resolve-PythonLauncher {
    param([Parameter(Mandatory = $true)][string]$WorkspacePath)

    $venvPython = Join-Path $WorkspacePath '.venv\Scripts\python.exe'
    if (Test-Path $venvPython) {
        return @{
            Path = $venvPython
            Prefix = @()
        }
    }

    $pyCommand = Get-Command py -ErrorAction SilentlyContinue
    if ($pyCommand) {
        return @{
            Path = $pyCommand.Source
            Prefix = @('-3.12')
        }
    }

    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCommand) {
        return @{
            Path = $pythonCommand.Source
            Prefix = @()
        }
    }

    throw 'Python launcher not found in PATH.'
}

function Get-GitBranchName {
    param([Parameter(Mandatory = $true)][string]$WorkspacePath)

    Push-Location $WorkspacePath
    try {
        $branchName = (& git branch --show-current 2>$null)
        if ([string]::IsNullOrWhiteSpace($branchName)) {
            return 'unknown'
        }

        return $branchName.Trim()
    }
    finally {
        Pop-Location
    }
}

function Get-GitStatusSummary {
    param([Parameter(Mandatory = $true)][string]$WorkspacePath)

    Push-Location $WorkspacePath
    try {
        $statusLines = (& git status --short 2>$null)
        if (-not $statusLines) {
            return 'clean'
        }

        return (($statusLines | ForEach-Object { $_.Trim() }) -join '; ')
    }
    finally {
        Pop-Location
    }
}

function Get-MemoryContextRole {
    param(
        [string]$IssueState
    )

    if (-not [string]::IsNullOrWhiteSpace($env:FQ_MEMORY_CONTEXT_ROLE)) {
        return $env:FQ_MEMORY_CONTEXT_ROLE.Trim()
    }

    if ([string]::IsNullOrWhiteSpace($IssueState)) {
        return 'codex'
    }

    switch ($IssueState.Trim()) {
        'Global Stewardship' { return 'global-stewardship' }
        default { return 'codex' }
    }
}

$workspacePath = (Get-Location).Path
$issueIdentifier = Split-Path -Leaf $workspacePath
$wrapperRoot = $ServiceRoot
$finalizerScript = Join-Path $PSScriptRoot 'invoke_freshquant_symphony_cleanup_finalizer.ps1'
$requestPath = Join-Path (Join-Path (Join-Path $ServiceRoot 'artifacts') 'cleanup-requests') "$issueIdentifier.json"
$codexPath = Resolve-CommandPath -Name 'codex'
$pythonLauncher = Resolve-PythonLauncher -WorkspacePath $workspacePath
$refreshMemoryScript = Join-Path $workspacePath 'runtime\memory\scripts\refresh_freshquant_memory.py'
$compileContextPackScript = Join-Path $workspacePath 'runtime\memory\scripts\compile_freshquant_context_pack.py'

if (-not (Test-Path $refreshMemoryScript)) {
    throw "Memory refresh script not found: $refreshMemoryScript"
}

if (-not (Test-Path $compileContextPackScript)) {
    throw "Context pack compiler script not found: $compileContextPackScript"
}

Set-Location $wrapperRoot
Push-Location $workspacePath
try {
    $issueState = if (-not [string]::IsNullOrWhiteSpace($env:SYMPHONY_ISSUE_STATE)) {
        $env:SYMPHONY_ISSUE_STATE
    }
    elseif (-not [string]::IsNullOrWhiteSpace($env:FRESHQUANT_ISSUE_STATE)) {
        $env:FRESHQUANT_ISSUE_STATE
    }
    else {
        'unknown'
    }
    $branchName = Get-GitBranchName -WorkspacePath $workspacePath
    $gitStatus = Get-GitStatusSummary -WorkspacePath $workspacePath
    $memoryContextRole = Get-MemoryContextRole -IssueState $issueState

    & $pythonLauncher.Path @(
        $pythonLauncher.Prefix
        + @(
            $refreshMemoryScript,
            '--repo-root',
            $workspacePath,
            '--service-root',
            $ServiceRoot,
            '--issue-identifier',
            $issueIdentifier,
            '--issue-state',
            $issueState,
            '--branch-name',
            $branchName,
            '--git-status',
            $gitStatus
        )
    )
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }

    $contextPackOutput = & $pythonLauncher.Path @(
        $pythonLauncher.Prefix
        + @(
            $compileContextPackScript,
            '--repo-root',
            $workspacePath,
            '--service-root',
            $ServiceRoot,
            '--issue-identifier',
            $issueIdentifier,
            '--role',
            $memoryContextRole
        )
    )
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }

    $contextPackPath = ($contextPackOutput | Select-Object -Last 1).Trim()
    if ([string]::IsNullOrWhiteSpace($contextPackPath)) {
        throw 'Memory context pack compiler did not return a path.'
    }

    [Environment]::SetEnvironmentVariable('FQ_MEMORY_CONTEXT_PATH', $contextPackPath, 'Process')
    [Environment]::SetEnvironmentVariable('FQ_MEMORY_CONTEXT_ROLE', $memoryContextRole, 'Process')
    [Environment]::SetEnvironmentVariable('FQ_MEMORY_ISSUE_IDENTIFIER', $issueIdentifier, 'Process')

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
