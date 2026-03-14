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
    @{ Name = 'memory context env rule'; Pattern = 'FQ_MEMORY_CONTEXT_PATH' },
    @{ Name = 'memory context derived rule'; Pattern = 'does not replace GitHub,\s*`docs/current/\*\*`,\s*or deploy/health results' },
    @{ Name = 'issue execution contract rule'; Pattern = 'For Symphony-managed tasks,\s*GitHub Issue is the formal task entry and execution contract\.' },
    @{ Name = 'direct pr coexistence rule'; Pattern = 'Repository-level work may also enter through direct `feature branch -> PR` outside Symphony\.' },
    @{ Name = 'rework state rule'; Pattern = '-\s+`Rework`:\s+fix deterministic repository-side failures before merge\.' },
    @{ Name = 'merge truth rule'; Pattern = 'Use GitHub PR truth as the only merge truth:\s*required checks,\s*unresolved review threads,\s*mergeability,\s*and ruleset policy\.' },
    @{ Name = 'pending checks stay merging rule'; Pattern = 'Keep the issue in `Merging` while required checks are pending\.' },
    @{ Name = 'rework structured record rule'; Pattern = 'If the issue enters `Rework`, record `blocker_class`, `evidence`, `next_action`, and `exit_condition` in GitHub\.' },
    @{ Name = 'blocked structured recovery rule'; Pattern = 'If the issue enters `Blocked`, record the blocker, clear condition, evidence, and target recovery state in GitHub' },
    @{ Name = 'global stewardship state rule'; Pattern = 'Global Stewardship' },
    @{ Name = 'merge handoff state rule'; Pattern = '-\s+`Merging`:\s+perform one-shot GitHub truth check,\s+merge the PR,\s+write the merge handoff comment,\s+and move the issue to `Global Stewardship`\.' },
    @{ Name = 'global stewardship ownership rule'; Pattern = '-\s+`Global Stewardship`:\s+global Codex automation handles deploy,\s+health check,\s+runtime ops check,\s+cleanup,\s+and follow-up issue creation\.' },
    @{ Name = 'global stewardship state label config'; Pattern = 'state_labels:\s*(?:\r?\n\s*[a-z_]+:\s*[^\r\n]+)+\r?\n\s*global_stewardship:\s*global-stewardship' },
    @{ Name = 'no merge retry without truth change rule'; Pattern = 'Do not retry merge when GitHub truth has not changed\.' },
    @{ Name = 'blocked auto recovery truth rule'; Pattern = 'merged PR,\s*pending ops -> `Global Stewardship`;\s*open PR with pending checks -> `Merging`;\s*open PR with deterministic repository-side failure -> `Rework`;\s*no open PR -> `In Progress`' },
    @{ Name = 'follow-up issue only rule'; Pattern = 'If code repair is needed after merge,\s*only create a follow-up issue for the next Symphony round;\s*do not create a repair PR directly from the global automation' },
    @{ Name = 'issue branch checkout rule'; Pattern = 'Before any non-`Blocked` implementation turn starts,\s*switch the workspace to the deterministic issue branch instead of local `main`' },
    @{ Name = 'workspace self-heal rule'; Pattern = 'If `before_run` fails because the workspace is not a git repository,\s*rebuild the workspace once and retry before surfacing the failure' },
    @{ Name = 'default issue labels rule'; Pattern = 'Treat newly created GitHub issues as `symphony` \+ `in-progress` by default\.' },
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

if ($content -match 'active_states:\s*(?:\r?\n\s*-\s+[^\r\n]+)+\r?\n\s*-\s+Todo') {
    throw "Workflow prompt contract failed for $WorkflowPath. Todo must not remain in tracker.active_states under the simplified governance flow."
}

if ($content -match 'Design Review|design-review') {
    throw "Workflow prompt contract failed for $WorkflowPath. Design Review must not appear in the simplified governance flow."
}

if ($content -match 'max_concurrent_agents_by_state:\s*(?:\r?\n\s*[a-z_]+:\s*\d+)+\r?\n\s*global_stewardship:\s*\d+') {
    throw "Workflow prompt contract failed for $WorkflowPath. Global Stewardship must not have a per-issue Symphony concurrency limit."
}

Write-Host "[freshquant] workflow prompt contract OK: $WorkflowPath"
