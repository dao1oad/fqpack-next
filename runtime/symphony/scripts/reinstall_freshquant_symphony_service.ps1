[CmdletBinding()]
param(
    [string]$ServiceName = 'fq-symphony-orchestrator',
    [string]$ServiceRoot = 'D:\fqpack\runtime\symphony-service',
    [string]$OpenAISymphonyRoot = 'D:\fqpack\tools\openai-symphony\elixir',
    [string]$InstallScriptPath,
    [int]$Port = 40123,
    [string]$ServicePassword
)

$ErrorActionPreference = 'Stop'

function Test-IsElevatedSession {
    $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [System.Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([System.Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-LimitBlankPasswordUse {
    $lsa = Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\Lsa'
    return [int]$lsa.LimitBlankPasswordUse
}

function Get-EnvValue {
    param([string]$Name)

    foreach ($scope in 'Process', 'User', 'Machine') {
        $value = [Environment]::GetEnvironmentVariable($Name, $scope)
        if (-not [string]::IsNullOrWhiteSpace($value)) {
            return $value
        }
    }

    return $null
}

function Resolve-OpenAISymphonyRoot {
    param([string]$RequestedPath)

    $candidates = @()

    foreach ($name in 'FRESHQUANT_OPENAI_SYMPHONY_ROOT', 'OPENAI_SYMPHONY_ROOT') {
        $value = Get-EnvValue -Name $name
        if (-not [string]::IsNullOrWhiteSpace($value)) {
            $candidates += $value
        }
    }

    if (-not [string]::IsNullOrWhiteSpace($RequestedPath)) {
        $candidates += $RequestedPath
    }

    $candidates += @(
        'D:\fqpack\tools\dao1oad-symphony\elixir',
        'D:\fqpack\tools\openai-symphony\elixir'
    )

    foreach ($candidate in $candidates | Select-Object -Unique) {
        if (-not [string]::IsNullOrWhiteSpace($candidate) -and (Test-Path $candidate)) {
            return [System.IO.Path]::GetFullPath($candidate).TrimEnd('\')
        }
    }

    $message = ($candidates | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -Unique) -join ', '
    throw "OpenAI Symphony elixir root not found. Checked: $message"
}

function Read-PlaintextPassword {
    $secure = Read-Host -Prompt 'Enter current Windows account password (press Enter for blank password)' -AsSecureString
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)

    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    }
    finally {
        if ($bstr -ne [IntPtr]::Zero) {
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
        }
    }
}

if (-not (Test-IsElevatedSession)) {
    throw 'Run this script in an elevated PowerShell session (Run as Administrator).'
}

if ([string]::IsNullOrWhiteSpace($InstallScriptPath)) {
    $InstallScriptPath = Join-Path $PSScriptRoot 'install_freshquant_symphony_service.ps1'
}

if (-not (Test-Path $InstallScriptPath)) {
    throw "Install script not found: $InstallScriptPath"
}

$OpenAISymphonyRoot = Resolve-OpenAISymphonyRoot -RequestedPath $OpenAISymphonyRoot

$blankPasswordAllowed = (Get-LimitBlankPasswordUse) -eq 0

if ([string]::IsNullOrWhiteSpace($ServicePassword)) {
    $ServicePassword = Read-PlaintextPassword
}

if ([string]::IsNullOrWhiteSpace($ServicePassword)) {
    if (-not $blankPasswordAllowed) {
        throw 'ServicePassword cannot be empty unless LimitBlankPasswordUse is set to 0.'
    }

    $ServicePassword = ''
}

$userLinearKey = [Environment]::GetEnvironmentVariable('LINEAR_API_KEY', 'User')
$machineLinearKey = [Environment]::GetEnvironmentVariable('LINEAR_API_KEY', 'Machine')
if ([string]::IsNullOrWhiteSpace($userLinearKey) -and [string]::IsNullOrWhiteSpace($machineLinearKey)) {
    throw 'LINEAR_API_KEY is not configured in the User or Machine environment.'
}

$existingService = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($existingService) {
    if ($existingService.Status -ne 'Stopped') {
        try {
            Stop-Service -Name $ServiceName -Force -ErrorAction Stop
        }
        catch {
            Write-Warning "Failed to stop the existing service. Continuing with delete: $($_.Exception.Message)"
        }
    }

    & sc.exe delete $ServiceName | Out-Null
    Start-Sleep -Seconds 2
}

& $InstallScriptPath `
    -ServiceName $ServiceName `
    -ServiceRoot $ServiceRoot `
    -OpenAISymphonyRoot $OpenAISymphonyRoot `
    -Port $Port `
    -ServicePassword $ServicePassword

Start-Service -Name $ServiceName
Start-Sleep -Seconds 8

Get-Service -Name $ServiceName | Select-Object Name, Status, StartType
& sc.exe qc $ServiceName

try {
    $response = Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:$Port/api/v1/state"
    Write-Host "[freshquant] health check ok: $($response.StatusCode)"
}
catch {
    Write-Warning "health check failed: $($_.Exception.Message)"

    $stdoutLog = Join-Path (Join-Path $ServiceRoot 'logs') 'stdout.log'
    $stderrLog = Join-Path (Join-Path $ServiceRoot 'logs') 'stderr.log'

    if (Test-Path $stdoutLog) {
        Write-Host '[freshquant] stdout.log tail'
        Get-Content $stdoutLog -Tail 100
    }

    if (Test-Path $stderrLog) {
        Write-Host '[freshquant] stderr.log tail'
        Get-Content $stderrLog -Tail 100
    }

    throw
}
