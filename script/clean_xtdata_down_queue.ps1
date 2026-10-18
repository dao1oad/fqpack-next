param(
    [int]$RetentionHours = 24,
    [string]$QmtRoot = ''
)

$ErrorActionPreference = 'Stop'
$logFile = 'D:\fqdata\log\fqnext_clean_xtdata_down_queue.log'

function Write-RunLog {
    param([string]$Message)
    $line = (Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + ' ' + $Message
    try {
        $dir = Split-Path -Parent $logFile
        if (-not (Test-Path $dir)) {
            New-Item -ItemType Directory -Path $dir -Force | Out-Null
        }
        Add-Content -LiteralPath $logFile -Value $line -Encoding UTF8
    } catch {
    }
    Write-Output $line
}

try {
    if (-not $QmtRoot) {
        $qmtDirs = @(Get-ChildItem 'D:\' -Directory -Force -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -match 'QMT' })
        if ($qmtDirs.Count -eq 0) {
            throw 'QMT root not found under D:\'
        }
        $QmtRoot = $qmtDirs[0].FullName
    }

    $userData = Join-Path $QmtRoot 'userdata_mini'
    if (-not (Test-Path -LiteralPath $userData)) {
        throw "userdata_mini not found: $userData"
    }

    $cutoff = (Get-Date).AddHours(-1 * [math]::Abs($RetentionHours))
    $files = @(Get-ChildItem -LiteralPath $userData -File -Filter 'down_queue*' -Force -ErrorAction SilentlyContinue)
    $groups = @{}
    foreach ($file in $files) {
        $base = $file.Name -replace '__mutex$', ''
        if (-not $groups.ContainsKey($base)) {
            $groups[$base] = New-Object System.Collections.ArrayList
        }
        [void]$groups[$base].Add($file)
    }

    $keepBases = @(
        $groups.Keys | ForEach-Object {
            $newest = ($groups[$_] | Sort-Object LastWriteTime -Descending | Select-Object -First 1).LastWriteTime
            [pscustomobject]@{ Base = $_; Newest = $newest }
        } | Sort-Object Newest -Descending | Select-Object -First 2 |
            ForEach-Object { $_.Base }
    )

    $deleted = 0
    $failed = 0
    $freedBytes = 0
    foreach ($base in @($groups.Keys)) {
        if ($keepBases -contains $base) {
            continue
        }
        foreach ($file in @($groups[$base])) {
            if ($file.LastWriteTime -ge $cutoff) {
                continue
            }
            try {
                $size = $file.Length
                [IO.File]::Delete($file.FullName)
                $freedBytes += $size
                $deleted += 1
            } catch {
                $failed += 1
            }
        }
    }

    $freeGb = [math]::Round((Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='D:'").FreeSpace / 1GB, 2)
    $message = 'qmt={0} deleted={1} failed={2} freed_mb={3} d_free_gb={4} retention_h={5} kept={6}' -f `
        $QmtRoot, $deleted, $failed, [math]::Round($freedBytes / 1MB, 1), $freeGb, $RetentionHours, ($keepBases -join ',')
    Write-RunLog $message
    exit 0
} catch {
    Write-RunLog ('ERROR ' + $_.Exception.Message)
    exit 1
}
