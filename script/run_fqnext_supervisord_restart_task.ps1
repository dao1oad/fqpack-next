[CmdletBinding()]
param(
    [string]$ServiceName = 'fqnext-supervisord',
    [int]$Port = 10011,
    [int]$TimeoutSeconds = 60,
    [string]$StatusPath = 'D:\fqpack\supervisord\artifacts\admin-bridge\restart-status.json'
)

$ErrorActionPreference = 'Stop'

function Write-Utf8NoBomFile {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Content
    )

    $directory = Split-Path -Parent $Path
    if (-not [string]::IsNullOrWhiteSpace($directory)) {
        New-Item -ItemType Directory -Force -Path $directory | Out-Null
    }

    $encoding = [System.Text.UTF8Encoding]::new($false)
    [System.IO.File]::WriteAllText($Path, $Content, $encoding)
}

function Test-TcpPort {
    param(
        [string]$HostName,
        [int]$PortNumber,
        [int]$ConnectTimeoutMs = 1000
    )

    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $async = $client.BeginConnect($HostName, $PortNumber, $null, $null)
        if (-not $async.AsyncWaitHandle.WaitOne($ConnectTimeoutMs)) {
            return $false
        }
        $client.EndConnect($async) | Out-Null
        return $true
    }
    catch {
        return $false
    }
    finally {
        $client.Dispose()
    }
}

$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
$service = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($null -eq $service) {
    throw "Service not found: $ServiceName"
}

if ($service.Status -eq 'Running') {
    Restart-Service -Name $ServiceName -Force
}
else {
    Start-Service -Name $ServiceName
}

$serviceStatus = 'Unknown'
$rpcReachable = $false
while ((Get-Date) -lt $deadline) {
    $currentService = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
    $serviceStatus = if ($null -eq $currentService) { 'Missing' } else { [string]$currentService.Status }
    if ($serviceStatus -eq 'Running') {
        $rpcReachable = Test-TcpPort -HostName '127.0.0.1' -PortNumber $Port
        if ($rpcReachable) {
            break
        }
    }
    Start-Sleep -Seconds 1
}

$payload = [ordered]@{
    service_name = $ServiceName
    service_status = $serviceStatus
    port = $Port
    rpc_reachable = $rpcReachable
    success = ($serviceStatus -eq 'Running' -and $rpcReachable)
    generated_at = (Get-Date).ToString('o')
}

$json = $payload | ConvertTo-Json -Depth 6
Write-Utf8NoBomFile -Path $StatusPath -Content $json
Write-Output $json

if (-not $payload.success) {
    exit 1
}

exit 0
