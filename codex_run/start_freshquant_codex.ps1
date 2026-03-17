[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('cli', 'app-server')]
    [string]$Mode,

    [string]$ServiceRoot = 'D:\fqpack\runtime\symphony-service',

    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$CodexArgs
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
    param([Parameter(Mandatory = $true)][string]$RepoRoot)

    $venvPython = Join-Path $RepoRoot '.venv\Scripts\python.exe'
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

$repoRoot = Split-Path -Parent $PSScriptRoot
$bootstrapScript = Join-Path $repoRoot 'runtime\memory\scripts\bootstrap_freshquant_memory.py'

if (-not (Test-Path $bootstrapScript)) {
    throw "Memory bootstrap script not found: $bootstrapScript"
}

$pythonLauncher = Resolve-PythonLauncher -RepoRoot $repoRoot
$codexPath = Resolve-CommandPath -Name 'codex'

Push-Location $repoRoot
try {
    $bootstrapArgs = @()
    if ($pythonLauncher.Prefix) {
        $bootstrapArgs += $pythonLauncher.Prefix
    }
    $bootstrapArgs += @(
        $bootstrapScript,
        '--repo-root',
        $repoRoot,
        '--service-root',
        $ServiceRoot
    )

    $bootstrapOutput = & $pythonLauncher.Path @bootstrapArgs
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }

    $bootstrapPayloadText = ($bootstrapOutput | Select-Object -Last 1)
    if ([string]::IsNullOrWhiteSpace($bootstrapPayloadText)) {
        throw 'Memory bootstrap did not return a JSON payload.'
    }

    $bootstrapPayload = $bootstrapPayloadText | ConvertFrom-Json
    if ([string]::IsNullOrWhiteSpace($bootstrapPayload.context_pack_path)) {
        throw 'Memory bootstrap returned an empty context_pack_path.'
    }

    [Environment]::SetEnvironmentVariable(
        'FQ_MEMORY_CONTEXT_PATH',
        $bootstrapPayload.context_pack_path,
        'Process'
    )
    [Environment]::SetEnvironmentVariable(
        'FQ_MEMORY_CONTEXT_ROLE',
        $bootstrapPayload.role,
        'Process'
    )
    [Environment]::SetEnvironmentVariable(
        'FQ_MEMORY_ISSUE_IDENTIFIER',
        $bootstrapPayload.issue_identifier,
        'Process'
    )

    if ($Mode -eq 'app-server') {
        $commandArgs = @(
            '--config',
            'shell_environment_policy.inherit=all',
            'app-server'
        )
        if ($CodexArgs) {
            $commandArgs += $CodexArgs
        }
        & $codexPath @commandArgs
        exit $LASTEXITCODE
    }

    if ($CodexArgs) {
        & $codexPath @CodexArgs
        exit $LASTEXITCODE
    }

    & $codexPath
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
