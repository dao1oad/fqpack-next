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
    @{ Name = 'global stewardship state rule'; Pattern = 'Global Stewardship' },
    @{ Name = 'merge handoff state rule'; Pattern = '-\s+`Merging`:\s+merge the PR,\s+write the merge handoff comment,\s+and move the issue to `Global Stewardship`\.' },
    @{ Name = 'global stewardship ownership rule'; Pattern = '-\s+`Global Stewardship`:\s+global Codex automation handles deploy,\s+health check,\s+runtime ops check,\s+cleanup,\s+and follow-up issue creation\.' },
    @{ Name = 'global stewardship state label config'; Pattern = 'state_labels:\s*(?:\r?\n\s*[a-z_]+:\s*[^\r\n]+)+\r?\n\s*global_stewardship:\s*global-stewardship' },
    @{ Name = 'post-approval no reapproval rule'; Pattern = 'Once Design Review is approved, do not ask for new human approval to handle CI, merge conflicts, deploy failures, or cleanup failures within the same issue scope\.\s*Route that work to `Rework` or `Global Stewardship` by default;\s*use `Blocked` only when a new real external blocker appears' },
    @{ Name = 'blocked auto recovery truth rule'; Pattern = 'merged PR,\s*pending ops -> `Global Stewardship`;\s*open non-draft PR -> `Rework`;\s*approved draft PR -> `In Progress`' },
    @{ Name = 'follow-up issue only rule'; Pattern = 'If code repair is needed after merge,\s*only create a follow-up issue for the next Symphony round;\s*do not create a repair PR directly from the global automation' },
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

if ($content -match 'active_states:\s*(?:\r?\n\s*-\s+[^\r\n]+)+\r?\n\s*-\s+Global Stewardship') {
    throw "Workflow prompt contract failed for $WorkflowPath. Global Stewardship must not be in tracker.active_states because it is owned by the single global Codex automation."
}

if ($content -match 'max_concurrent_agents_by_state:\s*(?:\r?\n\s*[a-z_]+:\s*\d+)+\r?\n\s*global_stewardship:\s*\d+') {
    throw "Workflow prompt contract failed for $WorkflowPath. Global Stewardship must not have a per-issue Symphony concurrency limit."
}

Write-Host "[freshquant] workflow prompt contract OK: $WorkflowPath"
