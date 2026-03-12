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

function Get-SourceLayout {
    param(
        [string]$RepoRuntimeRoot,
        [string]$ServiceRoot,
        [string]$CurrentScriptsRoot
    )

    $repoWorkflow = Join-Path $RepoRuntimeRoot 'WORKFLOW.freshquant.md'
    $repoPrompts = Join-Path $RepoRuntimeRoot 'prompts'
    $repoTemplates = Join-Path $RepoRuntimeRoot 'templates'
    if ((Test-Path $repoWorkflow) -and (Test-Path $repoPrompts) -and (Test-Path $repoTemplates)) {
        return @{
            ConfigRoot = $RepoRuntimeRoot
            ScriptsRoot = $CurrentScriptsRoot
        }
    }

    $deployedConfigRoot = Join-Path $ServiceRoot 'config'
    $deployedWorkflow = Join-Path $deployedConfigRoot 'WORKFLOW.freshquant.md'
    $deployedPrompts = Join-Path $deployedConfigRoot 'prompts'
    $deployedTemplates = Join-Path $deployedConfigRoot 'templates'
    $deployedScripts = Join-Path $ServiceRoot 'scripts'
    if ((Test-Path $deployedWorkflow) -and (Test-Path $deployedPrompts) -and (Test-Path $deployedTemplates) -and (Test-Path $deployedScripts)) {
        return @{
            ConfigRoot = $deployedConfigRoot
            ScriptsRoot = $deployedScripts
        }
    }

    throw "Unable to resolve source layout from RepoRuntimeRoot=$RepoRuntimeRoot or ServiceRoot=$ServiceRoot"
}

function Get-NormalizedPath {
    param([string]$Path)

    return [System.IO.Path]::GetFullPath($Path).TrimEnd('\')
}

$sourceLayout = Get-SourceLayout -RepoRuntimeRoot $repoRuntimeRoot -ServiceRoot $ServiceRoot -CurrentScriptsRoot $PSScriptRoot
$sourceConfigRoot = $sourceLayout.ConfigRoot
$sourceScriptsRoot = $sourceLayout.ScriptsRoot

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
        Source = (Join-Path $sourceConfigRoot 'WORKFLOW.freshquant.md')
        Destination = (Join-Path $configRoot 'WORKFLOW.freshquant.md')
    },
    @{
        Source = (Join-Path $sourceConfigRoot 'prompts\todo.md')
        Destination = (Join-Path $configRoot 'prompts\todo.md')
    },
    @{
        Source = (Join-Path $sourceConfigRoot 'prompts\in_progress.md')
        Destination = (Join-Path $configRoot 'prompts\in_progress.md')
    },
    @{
        Source = (Join-Path $sourceConfigRoot 'prompts\merging.md')
        Destination = (Join-Path $configRoot 'prompts\merging.md')
    },
    @{
        Source = (Join-Path $sourceConfigRoot 'templates\human_review_comment.md')
        Destination = (Join-Path $configRoot 'templates\human_review_comment.md')
    },
    @{
        Source = (Join-Path $sourceConfigRoot 'templates\pr_completion_comment.md')
        Destination = (Join-Path $configRoot 'templates\pr_completion_comment.md')
    },
    @{
        Source = (Join-Path $sourceConfigRoot 'templates\deployment_comment.md')
        Destination = (Join-Path $configRoot 'templates\deployment_comment.md')
    },
    @{
        Source = (Join-Path $sourceConfigRoot 'templates\design_review_packet.md')
        Destination = (Join-Path $configRoot 'templates\design_review_packet.md')
    },
    @{
        Source = (Join-Path $sourceConfigRoot 'templates\done_summary.md')
        Destination = (Join-Path $configRoot 'templates\done_summary.md')
    },
    @{
        Source = (Join-Path $sourceScriptsRoot 'freshquant_runner.exs')
        Destination = (Join-Path $scriptsRoot 'freshquant_runner.exs')
    },
    @{
        Source = (Join-Path $sourceScriptsRoot 'run_freshquant_codex_session.ps1')
        Destination = (Join-Path $scriptsRoot 'run_freshquant_codex_session.ps1')
    },
    @{
        Source = (Join-Path $sourceScriptsRoot 'start_freshquant_symphony.ps1')
        Destination = (Join-Path $scriptsRoot 'start_freshquant_symphony.ps1')
    },
    @{
        Source = (Join-Path $sourceScriptsRoot 'install_freshquant_symphony_service.ps1')
        Destination = (Join-Path $scriptsRoot 'install_freshquant_symphony_service.ps1')
    },
    @{
        Source = (Join-Path $sourceScriptsRoot 'sync_freshquant_symphony_service.ps1')
        Destination = (Join-Path $scriptsRoot 'sync_freshquant_symphony_service.ps1')
    },
    @{
        Source = (Join-Path $sourceScriptsRoot 'request_freshquant_symphony_cleanup.ps1')
        Destination = (Join-Path $scriptsRoot 'request_freshquant_symphony_cleanup.ps1')
    },
    @{
        Source = (Join-Path $sourceScriptsRoot 'invoke_freshquant_symphony_cleanup_finalizer.ps1')
        Destination = (Join-Path $scriptsRoot 'invoke_freshquant_symphony_cleanup_finalizer.ps1')
    },
    @{
        Source = (Join-Path $sourceScriptsRoot 'reinstall_freshquant_symphony_service.ps1')
        Destination = (Join-Path $scriptsRoot 'reinstall_freshquant_symphony_service.ps1')
    }
)

foreach ($entry in $copyMap) {
    if (-not (Test-Path $entry.Source)) {
        throw "Source file not found: $($entry.Source)"
    }

    if ((Get-NormalizedPath $entry.Source) -eq (Get-NormalizedPath $entry.Destination)) {
        continue
    }

    if ($PSCmdlet.ShouldProcess($entry.Destination, "Copy from $($entry.Source)")) {
        Copy-Item -Path $entry.Source -Destination $entry.Destination -Force
    }
}

Write-Host "[freshquant] synchronized symphony service runtime to $ServiceRoot"
