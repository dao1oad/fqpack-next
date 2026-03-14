[CmdletBinding()]
param(
    [string]$TaskName = 'fqnext-supervisord-restart',
    [string]$ServiceName = 'fqnext-supervisord',
    [int]$TimeoutSeconds = 90,
    [string]$StatusPath = 'D:\fqpack\supervisord\artifacts\admin-bridge\restart-status.json'
)

$ErrorActionPreference = 'Stop'

if (-not (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue)) {
    throw "Scheduled task not found: $TaskName"
}

if (Test-Path $StatusPath) {
    Remove-Item -Path $StatusPath -Force
}

Start-ScheduledTask -TaskName $TaskName

$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
while ((Get-Date) -lt $deadline) {
    if (Test-Path $StatusPath) {
        $content = Get-Content -Raw $StatusPath
        Write-Output $content
        $payload = $content | ConvertFrom-Json
        if (-not $payload.success) {
            throw "fqnext supervisor restart task reported failure for $ServiceName"
        }
        exit 0
    }
    Start-Sleep -Seconds 1
}

throw "Timed out waiting for restart task result: $TaskName"
