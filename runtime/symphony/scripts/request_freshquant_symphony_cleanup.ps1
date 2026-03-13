[CmdletBinding()]
param(
    [string]$ServiceRoot = 'D:\fqpack\runtime\symphony-service',
    [Parameter(Mandatory = $true)]
    [string]$IssueIdentifier,
    [Parameter(Mandatory = $true)]
    [string]$BranchName,
    [Parameter(Mandatory = $true)]
    [string]$WorkspacePath,
    [Parameter(Mandatory = $true, ParameterSetName = 'InlineBody')]
    [string]$DeploymentCommentBody,
    [Parameter(Mandatory = $true, ParameterSetName = 'BodyPath')]
    [string]$DeploymentCommentBodyPath,
    [string]$OriginUrl,
    [string]$IssueUrl,
    [int]$PullRequestNumber,
    [string]$PullRequestUrl,
    [string]$Repository,
    [int]$ArtifactsRetentionDays = 14
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

function Read-Utf8TextFile {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "DeploymentCommentBodyPath does not exist: $Path"
    }

    return [System.IO.File]::ReadAllText($Path, [System.Text.Encoding]::UTF8)
}

function Get-NormalizedPath {
    param([Parameter(Mandatory = $true)][string]$Path)

    return [System.IO.Path]::GetFullPath($Path).TrimEnd('\')
}

function Assert-IssueIdentifier {
    param([Parameter(Mandatory = $true)][string]$Value)

    if ($Value -notmatch '^GH-\d+$') {
        throw "Issue identifier must match GH-NUMBER: $Value"
    }
}

function Assert-BranchName {
    param([Parameter(Mandatory = $true)][string]$Value)

    if ([string]::IsNullOrWhiteSpace($Value)) {
        throw 'Branch name is required.'
    }
    if ($Value -eq 'main') {
        throw 'Refusing to register cleanup request for branch "main".'
    }
}

function Assert-NonEmptyText {
    param(
        [Parameter(Mandatory = $true)][string]$Value,
        [Parameter(Mandatory = $true)][string]$FieldName
    )

    if ([string]::IsNullOrWhiteSpace($Value)) {
        throw "$FieldName is required."
    }
}

function Resolve-DeploymentCommentBody {
    param(
        [string]$InlineBody,
        [string]$BodyPath,
        [Parameter(Mandatory = $true)][string]$ParameterSetName
    )

    if ($ParameterSetName -eq 'BodyPath') {
        return Read-Utf8TextFile -Path $BodyPath
    }

    return $InlineBody
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
        [Parameter(Mandatory = $true)][string]$WorkspacePath,
        [string]$OriginUrl
    )

    if (-not [string]::IsNullOrWhiteSpace($OriginUrl)) {
        return $OriginUrl.Trim()
    }

    $resolvedOriginUrl = (& git -C $WorkspacePath config --get remote.origin.url)
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($resolvedOriginUrl)) {
        throw "Unable to resolve remote.origin.url from workspace: $WorkspacePath"
    }

    return $resolvedOriginUrl.Trim()
}

function Resolve-GitHubRepository {
    param(
        [string]$Repository,
        [string]$IssueUrl,
        [string]$PullRequestUrl,
        [string]$OriginUrl
    )

    if (-not [string]::IsNullOrWhiteSpace($Repository)) {
        return $Repository.Trim()
    }

    $candidates = @(
        $IssueUrl,
        $PullRequestUrl,
        $OriginUrl,
        [Environment]::GetEnvironmentVariable('FRESHQUANT_GITHUB_REPO', 'Process'),
        [Environment]::GetEnvironmentVariable('FRESHQUANT_GITHUB_REPO', 'User'),
        [Environment]::GetEnvironmentVariable('FRESHQUANT_GITHUB_REPO', 'Machine'),
        [Environment]::GetEnvironmentVariable('GITHUB_REPOSITORY', 'Process'),
        [Environment]::GetEnvironmentVariable('GITHUB_REPOSITORY', 'User'),
        [Environment]::GetEnvironmentVariable('GITHUB_REPOSITORY', 'Machine'),
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

    throw 'Unable to resolve GitHub repository. Pass -Repository or provide IssueUrl/PullRequestUrl/OriginUrl.'
}

Assert-IssueIdentifier -Value $IssueIdentifier
Assert-BranchName -Value $BranchName
$resolvedDeploymentCommentBody = Resolve-DeploymentCommentBody -InlineBody $DeploymentCommentBody -BodyPath $DeploymentCommentBodyPath -ParameterSetName $PSCmdlet.ParameterSetName
Assert-NonEmptyText -Value $resolvedDeploymentCommentBody -FieldName 'DeploymentCommentBody'

$workspaceRoot = Join-Path $ServiceRoot 'workspaces'
$artifactsRoot = Join-Path $ServiceRoot 'artifacts'
$requestRoot = Join-Path $artifactsRoot 'cleanup-requests'
$normalizedWorkspacePath = Assert-WorkspacePathSafe -WorkspacePath $WorkspacePath -WorkspaceRoot $workspaceRoot -IssueIdentifier $IssueIdentifier
$normalizedWorkspaceRoot = Get-NormalizedPath -Path $workspaceRoot
$normalizedArtifactsRoot = Get-NormalizedPath -Path $artifactsRoot
$resolvedOriginUrl = Resolve-OriginUrl -WorkspacePath $normalizedWorkspacePath -OriginUrl $OriginUrl
$resolvedRepository = Resolve-GitHubRepository -Repository $Repository -IssueUrl $IssueUrl -PullRequestUrl $PullRequestUrl -OriginUrl $resolvedOriginUrl

New-Item -ItemType Directory -Force -Path $requestRoot | Out-Null

$requestPath = Join-Path $requestRoot "$IssueIdentifier.json"
$payload = [ordered]@{
    issueIdentifier = $IssueIdentifier
    branchName = $BranchName
    originUrl = $resolvedOriginUrl
    repository = $resolvedRepository
    workspacePath = $normalizedWorkspacePath
    workspaceRoot = $normalizedWorkspaceRoot
    artifactsRoot = $normalizedArtifactsRoot
    artifactsRetentionDays = $ArtifactsRetentionDays
    deploymentCommentBody = $resolvedDeploymentCommentBody
    issueUrl = $IssueUrl
    pullRequestNumber = $PullRequestNumber
    pullRequestUrl = $PullRequestUrl
    requestedAt = (Get-Date).ToString('o')
}

Write-Utf8NoBomFile -Path $requestPath -Content ($payload | ConvertTo-Json -Depth 5)
Write-Host "[freshquant] cleanup request written: $requestPath"
