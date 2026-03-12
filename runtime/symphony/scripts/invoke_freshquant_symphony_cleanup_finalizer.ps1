[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$ServiceRoot = 'D:\fqpack\runtime\symphony-service',
    [Parameter(Mandatory = $true)]
    [string]$IssueIdentifier,
    [Parameter(Mandatory = $true)]
    [string]$WorkspacePath,
    [string[]]$ActiveIssueIdentifiers,
    [switch]$SkipRemoteBranchDelete,
    [switch]$SkipLinearUpdate,
    [switch]$SkipGitHubUpdate
)

$ErrorActionPreference = 'Stop'

function Write-Utf8NoBomFile {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Content
    )

    $encoding = [System.Text.UTF8Encoding]::new($false)
    [System.IO.File]::WriteAllText($Path, $Content, $encoding)
}

function Get-EnvValue {
    param([Parameter(Mandatory = $true)][string]$Name)

    foreach ($scope in 'Process', 'User', 'Machine') {
        $value = [Environment]::GetEnvironmentVariable($Name, $scope)
        if (-not [string]::IsNullOrWhiteSpace($value)) {
            return $value
        }
    }

    return $null
}

function Get-NormalizedPath {
    param([Parameter(Mandatory = $true)][string]$Path)

    return [System.IO.Path]::GetFullPath($Path).TrimEnd('\')
}

function Assert-IssueIdentifier {
    param([Parameter(Mandatory = $true)][string]$Value)

    if ($Value -notmatch '^GH-(?<number>\d+)$') {
        throw "Issue identifier must match GH-NUMBER: $Value"
    }

    return @{
        IssueNumber = [double]$Matches.number
    }
}

function Assert-WorkspacePathSafe {
    param(
        [Parameter(Mandatory = $true)][string]$WorkspacePath,
        [Parameter(Mandatory = $true)][string]$WorkspaceRoot,
        [Parameter(Mandatory = $true)][string]$IssueIdentifier
    )

    $normalizedWorkspacePath = Get-NormalizedPath -Path $WorkspacePath
    $normalizedWorkspaceRoot = Get-NormalizedPath -Path $WorkspaceRoot
    $separator = [System.IO.Path]::DirectorySeparatorChar
    $expectedPrefix = if ($normalizedWorkspaceRoot.EndsWith([string]$separator, [System.StringComparison]::Ordinal)) {
        $normalizedWorkspaceRoot
    }
    else {
        "$normalizedWorkspaceRoot$separator"
    }

    if (
        $normalizedWorkspacePath -eq $normalizedWorkspaceRoot -or
        -not $normalizedWorkspacePath.StartsWith($expectedPrefix, [System.StringComparison]::OrdinalIgnoreCase)
    ) {
        throw "Workspace path must be inside workspace root. workspace=$normalizedWorkspacePath workspaceRoot=$normalizedWorkspaceRoot"
    }

    if ((Split-Path -Leaf $normalizedWorkspacePath) -ne $IssueIdentifier) {
        throw "Workspace leaf directory must equal issue identifier. workspace=$normalizedWorkspacePath issue=$IssueIdentifier"
    }

    return $normalizedWorkspacePath
}

function Resolve-OriginUrl {
    param(
        [string]$OriginUrl,
        [Parameter(Mandatory = $true)][string]$WorkspacePath
    )

    if (-not [string]::IsNullOrWhiteSpace($OriginUrl)) {
        return $OriginUrl.Trim()
    }

    if (-not (Test-Path $WorkspacePath)) {
        throw 'Cleanup request is missing originUrl and workspace path is unavailable.'
    }

    $resolvedOriginUrl = (& git -C $WorkspacePath config --get remote.origin.url)
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($resolvedOriginUrl)) {
        throw "Unable to resolve remote.origin.url from workspace: $WorkspacePath"
    }

    return $resolvedOriginUrl.Trim()
}

function Get-GitHubAuthToken {
    foreach ($name in 'GITHUB_TOKEN', 'GH_TOKEN') {
        $token = Get-EnvValue -Name $name
        if (-not [string]::IsNullOrWhiteSpace($token)) {
            return $token
        }
    }

    throw 'GITHUB_TOKEN or GH_TOKEN is not configured.'
}

function Resolve-GitHubRepository {
    param(
        [string]$Repository,
        [string]$IssueUrl,
        [string]$PullRequestUrl,
        [string]$OriginUrl
    )

    $candidates = @(
        $Repository,
        $IssueUrl,
        $PullRequestUrl,
        $OriginUrl,
        (Get-EnvValue -Name 'FRESHQUANT_GITHUB_REPO'),
        (Get-EnvValue -Name 'GITHUB_REPOSITORY'),
        'dao1oad/fqpack-next'
    )

    foreach ($candidate in $candidates) {
        if ([string]::IsNullOrWhiteSpace($candidate)) {
            continue
        }

        $trimmed = $candidate.Trim()

        if ($trimmed -match '^(?<owner>[A-Za-z0-9_.-]+)/(?<repo>[A-Za-z0-9_.-]+)$') {
            return "$($Matches.owner)/$($Matches.repo)"
        }

        if ($trimmed -match '^https://github\.com/(?<owner>[^/]+)/(?<repo>[^/]+?)(?:\.git)?(?:/|$)') {
            return "$($Matches.owner)/$($Matches.repo)"
        }

        if ($trimmed -match '^ssh://git@ssh\.github\.com:443/(?<owner>[^/]+)/(?<repo>[^/]+?)(?:\.git)?$') {
            return "$($Matches.owner)/$($Matches.repo)"
        }

        if ($trimmed -match '^git@github\.com:(?<owner>[^/]+)/(?<repo>[^/]+?)(?:\.git)?$') {
            return "$($Matches.owner)/$($Matches.repo)"
        }
    }

    throw 'Unable to resolve GitHub repository for cleanup finalizer.'
}

function Invoke-GitHubApi {
    param(
        [Parameter(Mandatory = $true)][ValidateSet('GET', 'POST', 'PATCH')][string]$Method,
        [Parameter(Mandatory = $true)][string]$Path,
        [hashtable]$Query,
        [object]$Body
    )

    $token = Get-GitHubAuthToken
    $headers = @{
        Authorization = "Bearer $token"
        Accept = 'application/vnd.github+json'
        'X-GitHub-Api-Version' = '2022-11-28'
    }

    $uri = "https://api.github.com$Path"
    if ($Query) {
        $pairs = @()
        foreach ($entry in $Query.GetEnumerator()) {
            if ($null -eq $entry.Value -or [string]::IsNullOrWhiteSpace([string]$entry.Value)) {
                continue
            }

            $pairs += ('{0}={1}' -f [uri]::EscapeDataString([string]$entry.Key), [uri]::EscapeDataString([string]$entry.Value))
        }

        if ($pairs.Count -gt 0) {
            $uri = "$uri?$(($pairs -join '&'))"
        }
    }

    $invokeParams = @{
        Uri = $uri
        Method = $Method
        Headers = $headers
    }

    if ($null -ne $Body) {
        $invokeParams['ContentType'] = 'application/json'
        $invokeParams['Body'] = ($Body | ConvertTo-Json -Depth 10 -Compress)
    }

    return Invoke-RestMethod @invokeParams
}

function Get-GitHubIssueStateName {
    param([Parameter(Mandatory = $true)]$Issue)

    if ($Issue.state -eq 'closed') {
        return 'Done'
    }

    $labels = @($Issue.labels | ForEach-Object { $_.name.ToString().ToLowerInvariant() })

    if ($labels -contains 'blocked') {
        return 'Blocked'
    }
    if ($labels -contains 'design-review') {
        return 'Design Review'
    }
    if ($labels -contains 'merging') {
        return 'Merging'
    }
    if ($labels -contains 'rework') {
        return 'Rework'
    }
    if ($labels -contains 'in-progress') {
        return 'In Progress'
    }

    return 'Todo'
}

function Get-GitHubIssueContext {
    param(
        [Parameter(Mandatory = $true)][string]$IssueIdentifier,
        [Parameter(Mandatory = $true)][string]$Repository
    )

    $parts = Assert-IssueIdentifier -Value $IssueIdentifier
    $issue = Invoke-GitHubApi -Method GET -Path "/repos/$Repository/issues/$($parts.IssueNumber)"

    if (-not $issue) {
        throw "Unable to resolve GitHub issue for $IssueIdentifier"
    }

    return @{
        IssueNumber = [int]$issue.number
        CurrentStateName = Get-GitHubIssueStateName -Issue $issue
        State = $issue.state
    }
}

function Get-ActiveIssueIdentifiersFromGitHub {
    param([Parameter(Mandatory = $true)][string]$Repository)

    $issues = Invoke-GitHubApi -Method GET -Path "/repos/$Repository/issues" -Query @{
        state = 'open'
        labels = 'symphony'
        per_page = 100
    }

    return @(
        $issues |
            Where-Object { -not $_.pull_request } |
            ForEach-Object { "GH-$($_.number)" }
    )
}

function Remove-RemoteBranch {
    param(
        [Parameter(Mandatory = $true)][string]$OriginUrl,
        [Parameter(Mandatory = $true)][string]$BranchName
    )

    if ([string]::IsNullOrWhiteSpace($BranchName)) {
        throw 'Branch name is required.'
    }
    if ($BranchName -eq 'main') {
        throw 'Refusing to delete remote main branch.'
    }

    $tempRepo = Join-Path ([System.IO.Path]::GetTempPath()) ("freshquant-symphony-cleanup-" + [guid]::NewGuid().ToString())
    New-Item -ItemType Directory -Force -Path $tempRepo | Out-Null
    try {
        & git -C $tempRepo init *> $null
        if ($LASTEXITCODE -ne 0) {
            throw 'git init failed for cleanup temp repo'
        }

        & git -C $tempRepo remote add origin $OriginUrl
        if ($LASTEXITCODE -ne 0) {
            throw "git remote add origin failed for $OriginUrl"
        }

        & git -C $tempRepo ls-remote --exit-code --heads origin $BranchName *> $null
        $lsRemoteExit = $LASTEXITCODE
        if ($lsRemoteExit -eq 2) {
            return $false
        }
        if ($lsRemoteExit -ne 0) {
            throw "git ls-remote failed for branch $BranchName"
        }

        & git -C $tempRepo push origin --delete $BranchName
        if ($LASTEXITCODE -ne 0) {
            throw "git push origin --delete failed for branch $BranchName"
        }
    }
    finally {
        Remove-Item -Path $tempRepo -Recurse -Force -ErrorAction SilentlyContinue
    }

    return $true
}

function Remove-WorkspaceDirectory {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not (Test-Path $Path)) {
        return $true
    }

    if ($PSCmdlet.ShouldProcess($Path, 'Remove workspace directory')) {
        Remove-Item -Path $Path -Recurse -Force
    }

    return -not (Test-Path $Path)
}

function Get-CleanupResultsSection {
    param(
        [Parameter(Mandatory = $true)][object]$Result
    )

    $artifactSummary = if ($Result.prunedArtifacts.Count -gt 0) {
        ($Result.prunedArtifacts | ForEach-Object { '- `{0}`' -f $_ }) -join "`r`n"
    }
    else {
        '- `none`'
    }

    return @(
        ''
        '## Cleanup Results'
        ''
        ('- Remote branch cleanup: `{0}`' -f $Result.remoteBranchDeleted)
        ('- Workspace cleanup: `{0}`' -f $Result.workspaceDeleted)
        ('- Artifacts retention days: `{0}`' -f $Result.artifactsRetentionDays)
        ''
        '### Pruned Artifacts'
        ''
        $artifactSummary
    ) -join "`r`n"
}

function Post-GitHubIssueComment {
    param(
        [Parameter(Mandatory = $true)][string]$Repository,
        [Parameter(Mandatory = $true)][int]$IssueNumber,
        [Parameter(Mandatory = $true)][string]$Body
    )

    [void](Invoke-GitHubApi -Method POST -Path "/repos/$Repository/issues/$IssueNumber/comments" -Body @{
        body = $Body
    })
}

function Close-GitHubIssue {
    param(
        [Parameter(Mandatory = $true)][string]$Repository,
        [Parameter(Mandatory = $true)][int]$IssueNumber
    )

    [void](Invoke-GitHubApi -Method PATCH -Path "/repos/$Repository/issues/$IssueNumber" -Body @{
        state = 'closed'
    })
}

function Get-PrunableArtifactEntries {
    param(
        [Parameter(Mandatory = $true)][string]$ArtifactsRoot,
        [Parameter(Mandatory = $true)][int]$RetentionDays,
        [string[]]$ActiveIssueIdentifiers = @()
    )

    if (-not (Test-Path $ArtifactsRoot)) {
        return @()
    }

    $cutoff = (Get-Date).AddDays(-1 * $RetentionDays)
    $activeSet = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
    foreach ($identifier in $ActiveIssueIdentifiers) {
        if (-not [string]::IsNullOrWhiteSpace($identifier)) {
            [void]$activeSet.Add($identifier)
        }
    }

    $systemNames = @('cleanup-requests', 'cleanup-results')
    $entries = Get-ChildItem -Path $ArtifactsRoot -Force -ErrorAction SilentlyContinue
    $prunable = @()

    foreach ($entry in $entries) {
        if ($systemNames -contains $entry.Name) {
            continue
        }
        if ($entry.Name -notmatch '^GH-\d+$') {
            continue
        }
        if ($activeSet.Contains($entry.Name)) {
            continue
        }
        if ($entry.LastWriteTime -gt $cutoff) {
            continue
        }

        $prunable += $entry
    }

    return $prunable
}

$workspaceRoot = Join-Path $ServiceRoot 'workspaces'
$artifactsRoot = Join-Path $ServiceRoot 'artifacts'
$requestPath = Join-Path (Join-Path $artifactsRoot 'cleanup-requests') "$IssueIdentifier.json"
$resultRoot = Join-Path $artifactsRoot 'cleanup-results'
$resultPath = Join-Path $resultRoot "$IssueIdentifier.json"
New-Item -ItemType Directory -Force -Path $resultRoot | Out-Null

$result = [ordered]@{
    issueIdentifier = $IssueIdentifier
    success = $false
    remoteBranchDeleted = $false
    workspaceDeleted = $false
    prunedArtifacts = @()
    artifactsRetentionDays = $null
    githubUpdated = $false
    issueClosed = $false
    issueCommentPosted = $false
    doneTransitioned = $false
    executedAt = (Get-Date).ToString('o')
    errors = @()
}

try {
    Assert-IssueIdentifier -Value $IssueIdentifier | Out-Null
    $normalizedWorkspacePath = Assert-WorkspacePathSafe -WorkspacePath $WorkspacePath -WorkspaceRoot $workspaceRoot -IssueIdentifier $IssueIdentifier

    if (-not (Test-Path $requestPath)) {
        $result.success = $true
        $result.remoteBranchDeleted = 'skipped'
        $result.workspaceDeleted = 'skipped'
        $result.issueCommentPosted = 'skipped'
        $result.doneTransitioned = 'skipped'
        Write-Utf8NoBomFile -Path $resultPath -Content ($result | ConvertTo-Json -Depth 8)
        Write-Host "[freshquant] no cleanup request found for $IssueIdentifier"
        exit 0
    }

    $request = Get-Content -Path $requestPath -Raw | ConvertFrom-Json
    $result.artifactsRetentionDays = [int]$request.artifactsRetentionDays
    $issueContext = $null
    $repository = Resolve-GitHubRepository -Repository $request.repository -IssueUrl $request.issueUrl -PullRequestUrl $request.pullRequestUrl -OriginUrl $request.originUrl

    $skipIssueUpdate = $SkipGitHubUpdate -or $SkipLinearUpdate

    if (-not $skipIssueUpdate) {
        $issueContext = Get-GitHubIssueContext -IssueIdentifier $IssueIdentifier -Repository $repository
        if ($issueContext.CurrentStateName -ne 'Merging') {
            throw "Refusing cleanup finalizer for $IssueIdentifier while issue is in state '$($issueContext.CurrentStateName)'."
        }
    }

    if ($SkipRemoteBranchDelete) {
        $result.remoteBranchDeleted = 'skipped'
    }
    else {
        $originUrl = Resolve-OriginUrl -OriginUrl $request.originUrl -WorkspacePath $normalizedWorkspacePath
        $result.remoteBranchDeleted = Remove-RemoteBranch -OriginUrl $originUrl -BranchName $request.branchName
    }

    $result.workspaceDeleted = Remove-WorkspaceDirectory -Path $normalizedWorkspacePath

    [string[]]$activeIdentifiers = @()
    if ($PSBoundParameters.ContainsKey('ActiveIssueIdentifiers')) {
        $activeIdentifiers = @($ActiveIssueIdentifiers)
    }
    elseif (-not $skipIssueUpdate) {
        $activeIdentifiers = @(Get-ActiveIssueIdentifiersFromGitHub -Repository $repository)
    }

    $prunableEntries = Get-PrunableArtifactEntries -ArtifactsRoot $artifactsRoot -RetentionDays ([int]$request.artifactsRetentionDays) -ActiveIssueIdentifiers $activeIdentifiers
    foreach ($entry in $prunableEntries) {
        if ($PSCmdlet.ShouldProcess($entry.FullName, 'Remove stale artifact entry')) {
            Remove-Item -Path $entry.FullName -Recurse -Force
        }
        $result.prunedArtifacts += $entry.Name
    }

    if ($skipIssueUpdate) {
        $result.githubUpdated = 'skipped'
        $result.issueClosed = 'skipped'
        $result.issueCommentPosted = 'skipped'
        $result.doneTransitioned = 'skipped'
    }
    else {
        $commentBody = "$($request.deploymentCommentBody)$([string](Get-CleanupResultsSection -Result $result))"
        Post-GitHubIssueComment -Repository $repository -IssueNumber $issueContext.IssueNumber -Body $commentBody
        $result.githubUpdated = $true
        $result.issueCommentPosted = $true
        Close-GitHubIssue -Repository $repository -IssueNumber $issueContext.IssueNumber
        $result.issueClosed = $true
        $result.doneTransitioned = $true
    }

    $result.success = $true
    Write-Utf8NoBomFile -Path $resultPath -Content ($result | ConvertTo-Json -Depth 8)
    Remove-Item -Path $requestPath -Force -ErrorAction SilentlyContinue
    Write-Host "[freshquant] cleanup finalizer succeeded for $IssueIdentifier"
}
catch {
    $result.errors = @($_.Exception.Message)
    Write-Utf8NoBomFile -Path $resultPath -Content ($result | ConvertTo-Json -Depth 8)
    throw
}
