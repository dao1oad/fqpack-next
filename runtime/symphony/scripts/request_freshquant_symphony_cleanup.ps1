[CmdletBinding()]
param(
    [string]$ServiceRoot = 'D:\fqpack\runtime\symphony-service',
    [Parameter(Mandatory = $true)]
    [string]$IssueIdentifier,
    [Parameter(Mandatory = $true)]
    [string]$BranchName,
    [Parameter(Mandatory = $true)]
    [string]$WorkspacePath,
    [Parameter(Mandatory = $true)]
    [string]$DeploymentCommentBody,
    [string]$OriginUrl,
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

function Get-NormalizedPath {
    param([Parameter(Mandatory = $true)][string]$Path)

    return [System.IO.Path]::GetFullPath($Path).TrimEnd('\')
}

function Assert-IssueIdentifier {
    param([Parameter(Mandatory = $true)][string]$Value)

    if ($Value -notmatch '^[A-Z]+-\d+$') {
        throw "Issue identifier must match TEAM-NUMBER: $Value"
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

Assert-IssueIdentifier -Value $IssueIdentifier
Assert-BranchName -Value $BranchName
Assert-NonEmptyText -Value $DeploymentCommentBody -FieldName 'DeploymentCommentBody'

$workspaceRoot = Join-Path $ServiceRoot 'workspaces'
$artifactsRoot = Join-Path $ServiceRoot 'artifacts'
$requestRoot = Join-Path $artifactsRoot 'cleanup-requests'
$normalizedWorkspacePath = Assert-WorkspacePathSafe -WorkspacePath $WorkspacePath -WorkspaceRoot $workspaceRoot -IssueIdentifier $IssueIdentifier
$normalizedWorkspaceRoot = Get-NormalizedPath -Path $workspaceRoot
$normalizedArtifactsRoot = Get-NormalizedPath -Path $artifactsRoot
$resolvedOriginUrl = Resolve-OriginUrl -WorkspacePath $normalizedWorkspacePath -OriginUrl $OriginUrl

New-Item -ItemType Directory -Force -Path $requestRoot | Out-Null

$requestPath = Join-Path $requestRoot "$IssueIdentifier.json"
$payload = [ordered]@{
    issueIdentifier = $IssueIdentifier
    branchName = $BranchName
    originUrl = $resolvedOriginUrl
    workspacePath = $normalizedWorkspacePath
    workspaceRoot = $normalizedWorkspaceRoot
    artifactsRoot = $normalizedArtifactsRoot
    artifactsRetentionDays = $ArtifactsRetentionDays
    deploymentCommentBody = $DeploymentCommentBody
    requestedAt = (Get-Date).ToString('o')
}

Write-Utf8NoBomFile -Path $requestPath -Content ($payload | ConvertTo-Json -Depth 5)
Write-Host "[freshquant] cleanup request written: $requestPath"
