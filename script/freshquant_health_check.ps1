[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Url,
    [int]$ExpectedStatus = 200,
    [string]$ExpectJsonField,
    [string]$ExpectedValue,
    [string]$ExpectText,
    [int]$TimeoutSec = 20,
    [string]$OutputPath
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

function Test-IsLocalUrl {
    param([Parameter(Mandatory = $true)][uri]$Uri)

    return $Uri.Host -in @('127.0.0.1', 'localhost', '::1')
}

function Resolve-JsonFieldValue {
    param(
        [Parameter(Mandatory = $true)]$InputObject,
        [Parameter(Mandatory = $true)][string]$FieldPath
    )

    $current = $InputObject
    foreach ($segment in @($FieldPath -split '\.')) {
        if ($null -eq $current) {
            return $null
        }

        if ($current -is [System.Collections.IList] -and $segment -match '^\d+$') {
            $index = [int]$segment
            if ($index -ge $current.Count) {
                return $null
            }
            $current = $current[$index]
            continue
        }

        $property = $current.PSObject.Properties[$segment]
        if ($null -eq $property) {
            return $null
        }
        $current = $property.Value
    }

    return $current
}

$uri = [uri]$Url
$proxyBypassed = Test-IsLocalUrl -Uri $uri
$proxyEnvPresent = [ordered]@{
    HTTP_PROXY = -not [string]::IsNullOrWhiteSpace($env:HTTP_PROXY)
    HTTPS_PROXY = -not [string]::IsNullOrWhiteSpace($env:HTTPS_PROXY)
    ALL_PROXY = -not [string]::IsNullOrWhiteSpace($env:ALL_PROXY)
}
$reasons = [System.Collections.Generic.List[string]]::new()
$body = ''
$statusCode = 0
$curlExitCode = 0
$jsonValue = $null

$bodyPath = [System.IO.Path]::GetTempFileName()
try {
    $curlPath = Get-Command curl.exe -ErrorAction SilentlyContinue
    if ($null -eq $curlPath) {
        throw 'curl.exe is required for FreshQuant health checks.'
    }

    $curlArgs = @(
        '--silent',
        '--show-error',
        '--location',
        '--output',
        $bodyPath,
        '--write-out',
        '%{http_code}',
        '--max-time',
        [string]$TimeoutSec
    )
    if ($proxyBypassed) {
        $curlArgs += @('--noproxy', '*')
    }
    $curlArgs += $Url

    $statusText = & $curlPath.Source @curlArgs
    $curlExitCode = $LASTEXITCODE
    if (Test-Path -LiteralPath $bodyPath) {
        $body = [System.IO.File]::ReadAllText($bodyPath, [System.Text.Encoding]::UTF8)
    }

    if (-not [int]::TryParse(($statusText | Out-String).Trim(), [ref]$statusCode)) {
        $reasons.Add("unable to parse status code from curl output: $statusText")
    }
    if ($curlExitCode -ne 0) {
        $reasons.Add("curl exited with code $curlExitCode")
    }
}
finally {
    if (Test-Path -LiteralPath $bodyPath) {
        Remove-Item -LiteralPath $bodyPath -Force -ErrorAction SilentlyContinue
    }
}

if ($statusCode -ne $ExpectedStatus) {
    $reasons.Add("status code mismatch: expected $ExpectedStatus actual $statusCode")
}

if (-not [string]::IsNullOrWhiteSpace($ExpectText) -and -not $body.Contains($ExpectText)) {
    $reasons.Add("response text missing required fragment: $ExpectText")
}

if (-not [string]::IsNullOrWhiteSpace($ExpectJsonField)) {
    try {
        $payload = $body | ConvertFrom-Json
        $jsonValue = Resolve-JsonFieldValue -InputObject $payload -FieldPath $ExpectJsonField
    }
    catch {
        $reasons.Add("response body is not valid JSON: $($_.Exception.Message)")
    }

    if ($null -eq $jsonValue) {
        $reasons.Add("JSON field not found: $ExpectJsonField")
    }
    elseif (
        -not [string]::IsNullOrWhiteSpace($ExpectedValue) -and
        [string]$jsonValue -ne $ExpectedValue
    ) {
        $reasons.Add(
            "JSON field value mismatch: $ExpectJsonField expected $ExpectedValue actual $jsonValue"
        )
    }
}

$result = [ordered]@{
    url = $Url
    status_code = $statusCode
    expected_status = $ExpectedStatus
    passed = ($reasons.Count -eq 0)
    proxy_bypassed = $proxyBypassed
    proxy_env_present = $proxyEnvPresent
    json_field = $ExpectJsonField
    json_value = if ($null -eq $jsonValue) { $null } else { [string]$jsonValue }
    expected_value = $ExpectedValue
    expect_text = $ExpectText
    reasons = @($reasons)
    body = $body
}

$json = $result | ConvertTo-Json -Depth 10
if (-not [string]::IsNullOrWhiteSpace($OutputPath)) {
    Write-Utf8NoBomFile -Path $OutputPath -Content $json
}
Write-Output $json

if (-not $result.passed) {
    exit 1
}

exit 0
