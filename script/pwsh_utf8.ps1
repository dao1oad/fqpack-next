param(
    [switch]$Quiet
)

Set-StrictMode -Version Latest

function Enable-FqUtf8Session {
    [Console]::InputEncoding = [System.Text.Encoding]::UTF8
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $global:OutputEncoding = [System.Text.Encoding]::UTF8

    # Make cat/type/Get-Content default to UTF-8 on Windows PowerShell 5.1.
    $global:PSDefaultParameterValues["Get-Content:Encoding"] = "utf8"

    # Ensure child Python processes default to UTF-8 as well.
    $env:PYTHONUTF8 = "1"
    $env:PYTHONIOENCODING = "utf-8"
}

function Test-DotSourced {
    return $MyInvocation.InvocationName -eq "."
}

Enable-FqUtf8Session

if (-not $Quiet) {
    if (-not (Test-DotSourced)) {
        Write-Host "Applied UTF-8 settings to this PowerShell process only." -ForegroundColor Yellow
        Write-Host "Tip: dot-source to affect your current session:" -ForegroundColor Yellow
        Write-Host "  . .\\script\\pwsh_utf8.ps1" -ForegroundColor Yellow
    }

    Write-Host ("Console.OutputEncoding: {0}" -f [Console]::OutputEncoding.WebName)
    Write-Host ("Get-Content default encoding: {0}" -f $global:PSDefaultParameterValues["Get-Content:Encoding"])
    Write-Host ("PYTHONUTF8: {0}" -f $env:PYTHONUTF8)
}
