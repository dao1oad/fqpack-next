[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$ServiceRoot = 'D:\fqpack\runtime\symphony-service',
    [Parameter(Mandatory = $true)]
    [string]$IssueIdentifier,
    [Parameter(Mandatory = $true)]
    [string]$WorkspacePath,
    [string[]]$ActiveIssueIdentifiers,
    [switch]$SkipRemoteBranchDelete,
    [switch]$SkipLinearUpdate
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

    if ($Value -notmatch '^(?<team>[A-Z]+)-(?<number>\d+)$') {
        throw "Issue identifier must match TEAM-NUMBER: $Value"
    }

    return @{
        TeamKey = $Matches.team
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

function Invoke-LinearGraphQL {
    param(
        [Parameter(Mandatory = $true)][string]$Query,
        [hashtable]$Variables
    )

    $apiKey = Get-EnvValue -Name 'LINEAR_API_KEY'
    if ([string]::IsNullOrWhiteSpace($apiKey)) {
        throw 'LINEAR_API_KEY is not configured.'
    }

    $headers = @{
        Authorization = $apiKey
        'Content-Type' = 'application/json'
    }
    $body = @{
        query = $Query
        variables = $Variables
    } | ConvertTo-Json -Depth 10 -Compress

    $response = Invoke-RestMethod -Uri 'https://api.linear.app/graphql' -Method Post -Headers $headers -Body $body
    if ($response.errors) {
        $messages = ($response.errors | ForEach-Object { $_.message }) -join '; '
        throw "Linear GraphQL error: $messages"
    }

    return $response.data
}

function Get-LinearIssueContext {
    param([Parameter(Mandatory = $true)][string]$IssueIdentifier)

    $parts = Assert-IssueIdentifier -Value $IssueIdentifier
    $query = @'
query($teamKey: String!, $issueNumber: Float!, $doneState: String!) {
  issues(filter: { team: { key: { eq: $teamKey } }, number: { eq: $issueNumber } }, first: 1) {
    nodes {
      id
      identifier
      state {
        id
        name
      }
    }
  }
  workflowStates(filter: { team: { key: { eq: $teamKey } }, name: { eq: $doneState } }, first: 1) {
    nodes {
      id
      name
    }
  }
}
'@
    $data = Invoke-LinearGraphQL -Query $query -Variables @{
        teamKey = $parts.TeamKey
        issueNumber = $parts.IssueNumber
        doneState = 'Done'
    }

    $issue = $data.issues.nodes | Select-Object -First 1
    if (-not $issue) {
        throw "Unable to resolve Linear issue for $IssueIdentifier"
    }

    $doneState = $data.workflowStates.nodes | Select-Object -First 1
    if (-not $doneState) {
        throw "Unable to resolve Linear Done state for team $($parts.TeamKey)"
    }

    return @{
        IssueId = $issue.id
        CurrentStateName = $issue.state.name
        DoneStateId = $doneState.id
    }
}

function Get-ActiveIssueIdentifiersFromLinear {
    $query = @'
query($activeStates: [String!]) {
  issues(filter: { state: { name: { in: $activeStates } } }, first: 250) {
    nodes {
      identifier
    }
  }
}
'@
    $data = Invoke-LinearGraphQL -Query $query -Variables @{
        activeStates = @('Todo', 'In Progress', 'Rework', 'Merging')
    }

    return @($data.issues.nodes | ForEach-Object { $_.identifier })
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

function Post-LinearDeploymentComment {
    param(
        [Parameter(Mandatory = $true)][string]$IssueId,
        [Parameter(Mandatory = $true)][string]$Body
    )

    $mutation = @'
mutation($input: CommentCreateInput!) {
  commentCreate(input: $input) {
    success
    comment {
      id
    }
  }
}
'@
    $data = Invoke-LinearGraphQL -Query $mutation -Variables @{
        input = @{
            issueId = $IssueId
            body = $Body
        }
    }

    if (-not $data.commentCreate.success) {
        throw 'Linear commentCreate returned success=false'
    }
}

function Move-LinearIssueToDone {
    param(
        [Parameter(Mandatory = $true)][string]$IssueId,
        [Parameter(Mandatory = $true)][string]$DoneStateId
    )

    $mutation = @'
mutation($id: String!, $input: IssueUpdateInput!) {
  issueUpdate(id: $id, input: $input) {
    success
    issue {
      id
      state {
        name
      }
    }
  }
}
'@
    $data = Invoke-LinearGraphQL -Query $mutation -Variables @{
        id = $IssueId
        input = @{
            stateId = $DoneStateId
        }
    }

    if (-not $data.issueUpdate.success) {
        throw 'Linear issueUpdate returned success=false'
    }
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
        if ($entry.Name -notmatch '^[A-Z]+-\d+$') {
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
    linearCommentPosted = $false
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
        $result.linearCommentPosted = 'skipped'
        $result.doneTransitioned = 'skipped'
        Write-Utf8NoBomFile -Path $resultPath -Content ($result | ConvertTo-Json -Depth 8)
        Write-Host "[freshquant] no cleanup request found for $IssueIdentifier"
        exit 0
    }

    $request = Get-Content -Path $requestPath -Raw | ConvertFrom-Json
    $result.artifactsRetentionDays = [int]$request.artifactsRetentionDays
    $issueContext = $null

    if (-not $SkipLinearUpdate) {
        $issueContext = Get-LinearIssueContext -IssueIdentifier $IssueIdentifier
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
    elseif (-not $SkipLinearUpdate) {
        $activeIdentifiers = @(Get-ActiveIssueIdentifiersFromLinear)
    }

    $prunableEntries = Get-PrunableArtifactEntries -ArtifactsRoot $artifactsRoot -RetentionDays ([int]$request.artifactsRetentionDays) -ActiveIssueIdentifiers $activeIdentifiers
    foreach ($entry in $prunableEntries) {
        if ($PSCmdlet.ShouldProcess($entry.FullName, 'Remove stale artifact entry')) {
            Remove-Item -Path $entry.FullName -Recurse -Force
        }
        $result.prunedArtifacts += $entry.Name
    }

    if ($SkipLinearUpdate) {
        $result.linearCommentPosted = 'skipped'
        $result.doneTransitioned = 'skipped'
    }
    else {
        $commentBody = "$($request.deploymentCommentBody)$([string](Get-CleanupResultsSection -Result $result))"
        Post-LinearDeploymentComment -IssueId $issueContext.IssueId -Body $commentBody
        $result.linearCommentPosted = $true
        Move-LinearIssueToDone -IssueId $issueContext.IssueId -DoneStateId $issueContext.DoneStateId
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
