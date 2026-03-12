[CmdletBinding()]
param(
    [string]$Repository = 'dao1oad/fqpack-next',
    [string]$ServiceRoot = 'D:\fqpack\runtime\symphony-service',
    [int]$Port = 40123,
    [int]$PollSeconds = 120,
    [int]$PollIntervalSeconds = 10,
    [switch]$AutoClose = $true
)

$ErrorActionPreference = 'Stop'

function Assert-CommandExists {
    param([Parameter(Mandatory = $true)][string]$Name)

    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if (-not $command) {
        throw "Required command not found: $Name"
    }
}

function Get-IssueNumberFromUrl {
    param([Parameter(Mandatory = $true)][string]$Url)

    if ($Url -notmatch '/issues/(?<number>\d+)$') {
        throw "Unable to parse issue number from url: $Url"
    }

    return [int]$Matches.number
}

function Test-IssueClaimed {
    param(
        [Parameter(Mandatory = $true)][int]$IssueNumber,
        [Parameter(Mandatory = $true)][string]$ServiceRoot,
        [Parameter(Mandatory = $true)][int]$Port
    )

    $issueIdentifier = "GH-$IssueNumber"
    $state = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/v1/state" -Method Get
    $running = @($state.running)
    $retrying = @($state.retrying)
    $workspacePath = Join-Path (Join-Path $ServiceRoot 'workspaces') $issueIdentifier

    return (
        ($running | Where-Object { $_.issue_id -eq $issueIdentifier -or $_.issue_identifier -eq $issueIdentifier }).Count -gt 0 -or
        ($retrying | Where-Object { $_.issue_id -eq $issueIdentifier -or $_.issue_identifier -eq $issueIdentifier }).Count -gt 0 -or
        (Test-Path $workspacePath)
    )
}

Assert-CommandExists -Name 'gh'

$title = '[Smoke] formal service check'
$body = @'
Smoke test for the GitHub-first FreshQuant Symphony formal service.

Expected behavior:
- formal service polls this issue from GitHub
- formal service may create a GH-* workspace
- this issue will be closed after verification
'@

# New issues must start on the default low-risk path: `symphony` + `todo`.
# Do not pre-apply `design-review` here; the first Todo pass decides whether
# the task later needs to enter the Design Review path.

$issueUrl = (& gh issue create --repo $Repository --title $title --body $body --label symphony --label todo).Trim()
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($issueUrl)) {
    throw 'Failed to create smoke issue.'
}

$issueNumber = Get-IssueNumberFromUrl -Url $issueUrl
$deadline = (Get-Date).AddSeconds($PollSeconds)
$claimed = $false

while ((Get-Date) -lt $deadline) {
    if (Test-IssueClaimed -IssueNumber $issueNumber -ServiceRoot $ServiceRoot -Port $Port) {
        $claimed = $true
        break
    }

    Start-Sleep -Seconds $PollIntervalSeconds
}

$issueState = Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:$Port/api/v1/state"
$workspaceRoot = Join-Path $ServiceRoot 'workspaces'

Write-Host "[freshquant] smoke issue: $issueUrl"
Write-Host "[freshquant] claimed: $claimed"
Write-Host '[freshquant] formal service state:'
$issueState.Content
Write-Host '[freshquant] workspaces:'
Get-ChildItem $workspaceRoot -Force | Select-Object Name, LastWriteTime

if ($AutoClose) {
    & gh issue close $issueNumber --repo $Repository --comment 'Smoke test completed.'
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "Failed to close smoke issue #$issueNumber"
    }
}

if (-not $claimed) {
    throw "Formal service did not claim GH-$issueNumber within $PollSeconds seconds."
}
