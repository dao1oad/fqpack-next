[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [string]$TaskName = 'fq-symphony-orchestrator-restart',
    [string]$ServiceRoot = 'D:\fqpack\runtime\symphony-service',
    [string]$StatusPath,
    [int]$TimeoutSeconds = 180,
    [int]$PollIntervalSeconds = 2
)

$ErrorActionPreference = 'Stop'

function Resolve-StatusPath {
    param(
        [string]$ExplicitPath,
        [string]$ResolvedServiceRoot
    )

    if (-not [string]::IsNullOrWhiteSpace($ExplicitPath)) {
        return [System.IO.Path]::GetFullPath($ExplicitPath)
    }

    return Join-Path $ResolvedServiceRoot 'artifacts\admin-bridge\restart-status.json'
}

function Read-TaskStatus {
    param([string]$Path)

    if (-not (Test-Path $Path)) {
        return $null
    }

    return Get-Content -Raw -Path $Path | ConvertFrom-Json
}

$resolvedServiceRoot = [System.IO.Path]::GetFullPath($ServiceRoot).TrimEnd('\')
$resolvedStatusPath = Resolve-StatusPath -ExplicitPath $StatusPath -ResolvedServiceRoot $resolvedServiceRoot
$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue

if (-not $task) {
    throw "Scheduled task '$TaskName' not found. Install it first with runtime/symphony/scripts/install_freshquant_symphony_restart_task.ps1 from an elevated PowerShell session."
}

$previousWriteTimeUtc = if (Test-Path $resolvedStatusPath) { (Get-Item $resolvedStatusPath).LastWriteTimeUtc } else { [datetime]::MinValue }

if ($PSCmdlet.ShouldProcess($TaskName, 'Run FreshQuant Symphony restart task')) {
    Start-ScheduledTask -TaskName $TaskName
}

$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
$status = $null
do {
    Start-Sleep -Seconds $PollIntervalSeconds

    if (Test-Path $resolvedStatusPath) {
        $currentWriteTimeUtc = (Get-Item $resolvedStatusPath).LastWriteTimeUtc
        if ($currentWriteTimeUtc -gt $previousWriteTimeUtc) {
            $status = Read-TaskStatus -Path $resolvedStatusPath
            if ($null -ne $status -and -not [string]::IsNullOrWhiteSpace($status.completed_at)) {
                break
            }
        }
    }
} while ((Get-Date) -lt $deadline)

if ($null -eq $status -or [string]::IsNullOrWhiteSpace($status.completed_at)) {
    throw "Timed out waiting for scheduled task '$TaskName' to update $resolvedStatusPath."
}

if (-not $status.success) {
    $message = if ([string]::IsNullOrWhiteSpace($status.error)) { 'Unknown error.' } else { $status.error }
    throw "FreshQuant Symphony restart task reported failure: $message"
}

Write-Host "[freshquant] restart task completed with HTTP $($status.health_status_code)"
$status
