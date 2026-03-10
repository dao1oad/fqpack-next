[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$ServiceRoot = 'D:\fqpack\runtime\symphony-service'
)

$ErrorActionPreference = 'Stop'

$repoRuntimeRoot = Split-Path -Parent $PSScriptRoot
$configRoot = Join-Path $ServiceRoot 'config'
$scriptsRoot = Join-Path $ServiceRoot 'scripts'
$logsRoot = Join-Path $ServiceRoot 'logs'
$workspacesRoot = Join-Path $ServiceRoot 'workspaces'
$artifactsRoot = Join-Path $ServiceRoot 'artifacts'

$directories = @(
    $configRoot,
    (Join-Path $configRoot 'prompts'),
    (Join-Path $configRoot 'templates'),
    $scriptsRoot,
    $logsRoot,
    $workspacesRoot,
    $artifactsRoot
)

foreach ($directory in $directories) {
    if ($PSCmdlet.ShouldProcess($directory, 'Create directory')) {
        New-Item -ItemType Directory -Force -Path $directory | Out-Null
    }
}

$copyMap = @(
    @{
        Source = (Join-Path $repoRuntimeRoot 'WORKFLOW.freshquant.md')
        Destination = (Join-Path $configRoot 'WORKFLOW.freshquant.md')
    },
    @{
        Source = (Join-Path $repoRuntimeRoot 'prompts\todo.md')
        Destination = (Join-Path $configRoot 'prompts\todo.md')
    },
    @{
        Source = (Join-Path $repoRuntimeRoot 'prompts\in_progress.md')
        Destination = (Join-Path $configRoot 'prompts\in_progress.md')
    },
    @{
        Source = (Join-Path $repoRuntimeRoot 'templates\human_review_comment.md')
        Destination = (Join-Path $configRoot 'templates\human_review_comment.md')
    },
    @{
        Source = (Join-Path $PSScriptRoot 'freshquant_runner.exs')
        Destination = (Join-Path $scriptsRoot 'freshquant_runner.exs')
    },
    @{
        Source = (Join-Path $PSScriptRoot 'start_freshquant_symphony.ps1')
        Destination = (Join-Path $scriptsRoot 'start_freshquant_symphony.ps1')
    },
    @{
        Source = (Join-Path $PSScriptRoot 'install_freshquant_symphony_service.ps1')
        Destination = (Join-Path $scriptsRoot 'install_freshquant_symphony_service.ps1')
    },
    @{
        Source = (Join-Path $PSScriptRoot 'reinstall_freshquant_symphony_service.ps1')
        Destination = (Join-Path $scriptsRoot 'reinstall_freshquant_symphony_service.ps1')
    }
)

foreach ($entry in $copyMap) {
    if (-not (Test-Path $entry.Source)) {
        throw "Source file not found: $($entry.Source)"
    }

    if ($PSCmdlet.ShouldProcess($entry.Destination, "Copy from $($entry.Source)")) {
        Copy-Item -Path $entry.Source -Destination $entry.Destination -Force
    }
}

Write-Host "[freshquant] synchronized symphony service runtime to $ServiceRoot"
