[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$WorkflowPath
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path $WorkflowPath)) {
    throw "Workflow file not found: $WorkflowPath"
}

$content = Get-Content -Path $WorkflowPath -Raw
$requiredPatterns = @(
    @{ Name = 'github remote bootstrap hook'; Pattern = 'git remote add github https://github\.com/dao1oad/fqpack-next\.git' },
    @{ Name = 'github remote self-heal hook'; Pattern = 'git remote set-url github https://github\.com/dao1oad/fqpack-next\.git' },
    @{ Name = 'default push remote hook'; Pattern = 'git config remote\.pushDefault github' },
    @{ Name = 'issue identifier placeholder'; Pattern = '\{\{\s*issue\.identifier\s*\}\}' },
    @{ Name = 'issue title placeholder'; Pattern = '\{\{\s*issue\.title\s*\}\}' },
    @{ Name = 'issue description placeholder'; Pattern = 'issue\.description' },
    @{ Name = 'issue state placeholder'; Pattern = 'Current state:\s*\{\{\s*issue\.state\s*\}\}' },
    @{ Name = 'issue url placeholder'; Pattern = 'URL:\s*\{\{\s*issue\.url\s*\}\}' },
    @{ Name = 'design review no-brainstorming rule'; Pattern = 'In\s+`Design Review`,\s+do not invoke\s+`brainstorming`\s+and do not ask for new human clarification inside the Codex session' },
    @{ Name = 'draft PR bootstrap rule'; Pattern = 'first create or switch to the issue branch,\s*create the Draft PR,\s*and publish the complete Design Review Packet in the PR body' },
    @{ Name = 'blocked structured recovery rule'; Pattern = 'If the issue enters `Blocked`, record the blocker, clear condition, evidence, and target recovery state in GitHub' },
    @{ Name = 'post-approval no reapproval rule'; Pattern = 'Once Design Review is approved, do not ask for new human approval to handle CI, merge conflicts, deploy failures, or cleanup failures within the same issue scope' },
    @{ Name = 'blocked auto recovery truth rule'; Pattern = 'merged PR -> `Merging`;\s*open non-draft PR -> `Rework`;\s*approved draft PR -> `In Progress`' },
    @{ Name = 'workspace self-heal rule'; Pattern = 'If `before_run` fails because the workspace is not a git repository, rebuild the workspace once and retry before surfacing the failure' },
    @{ Name = 'default issue labels rule'; Pattern = 'Treat newly created GitHub issues as `symphony` \+ `todo` by default\.' },
    @{ Name = 'github text language rule'; Pattern = 'All GitHub-facing text that you write must use Simplified Chinese by default' }
)

$missing = @()
foreach ($entry in $requiredPatterns) {
    if ($content -notmatch $entry.Pattern) {
        $missing += $entry.Name
    }
}

if ($missing.Count -gt 0) {
    throw "Workflow prompt contract failed for $WorkflowPath. Missing: $($missing -join ', ')"
}

Write-Host "[freshquant] workflow prompt contract OK: $WorkflowPath"
