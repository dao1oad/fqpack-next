[CmdletBinding()]
param(
    [string]$ServiceName = 'fq-symphony-orchestrator',
    [string]$ServiceRoot = 'D:\fqpack\runtime\symphony-service',
    [int]$Port = 40123,
    [string]$StatusPath,
    [int]$HealthTimeoutSeconds = 90,
    [int]$HealthPollIntervalSeconds = 3
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

function Write-TaskStatus {
    param(
        [Parameter(Mandatory = $true)]
        [System.Collections.IDictionary]$Status,
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    $directory = Split-Path -Parent $Path
    if (-not [string]::IsNullOrWhiteSpace($directory)) {
        New-Item -ItemType Directory -Force -Path $directory | Out-Null
    }

    $Status | ConvertTo-Json -Depth 5 | Set-Content -Path $Path -Encoding UTF8
}

function Wait-ServiceRunning {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [int]$TimeoutSeconds = 60
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        $service = Get-Service -Name $Name -ErrorAction Stop
        if ($service.Status -eq 'Running') {
            return $service
        }

        Start-Sleep -Seconds 2
    } while ((Get-Date) -lt $deadline)

    throw "Service '$Name' did not reach Running within $TimeoutSeconds seconds."
}

function Wait-HealthEndpointReady {
    param(
        [int]$Port,
        [int]$TimeoutSeconds = 90,
        [int]$PollIntervalSeconds = 3
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $lastError = $null

    do {
        try {
            return Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:$Port/api/v1/state"
        }
        catch {
            $lastError = $_.Exception.Message
            Start-Sleep -Seconds $PollIntervalSeconds
        }
    } while ((Get-Date) -lt $deadline)

    if ([string]::IsNullOrWhiteSpace($lastError)) {
        throw "Health endpoint on port $Port did not become ready within $TimeoutSeconds seconds."
    }

    throw $lastError
}

$resolvedServiceRoot = [System.IO.Path]::GetFullPath($ServiceRoot).TrimEnd('\')
$resolvedStatusPath = Resolve-StatusPath -ExplicitPath $StatusPath -ResolvedServiceRoot $resolvedServiceRoot
$status = [ordered]@{
    started_at = (Get-Date).ToString('o')
    completed_at = $null
    success = $false
    service_name = $ServiceName
    service_root = $resolvedServiceRoot
    port = $Port
    host = $env:COMPUTERNAME
    service_status = $null
    health_status_code = $null
    error = $null
}

Write-TaskStatus -Status $status -Path $resolvedStatusPath

try {
    Restart-Service -Name $ServiceName -ErrorAction Stop
    $service = Wait-ServiceRunning -Name $ServiceName
    $response = Wait-HealthEndpointReady `
        -Port $Port `
        -TimeoutSeconds $HealthTimeoutSeconds `
        -PollIntervalSeconds $HealthPollIntervalSeconds

    $status.success = $true
    $status.service_status = $service.Status.ToString()
    $status.health_status_code = [int]$response.StatusCode
}
catch {
    $status.error = $_.Exception.Message

    try {
        $service = Get-Service -Name $ServiceName -ErrorAction Stop
        $status.service_status = $service.Status.ToString()
    }
    catch {
        $status.service_status = 'Unknown'
    }
}
finally {
    $status.completed_at = (Get-Date).ToString('o')
    Write-TaskStatus -Status $status -Path $resolvedStatusPath
}

if (-not $status.success) {
    throw "FreshQuant Symphony restart task failed: $($status.error)"
}
