[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('CaptureBaseline', 'Verify')]
    [string]$Mode,
    [string]$BaselinePath,
    [string]$OutputPath,
    [string[]]$DeploymentSurface = @(),
    [string]$DockerSnapshotPath,
    [string]$ServiceSnapshotPath,
    [string]$ProcessSnapshotPath,
    [string]$SupervisorSnapshotPath,
    [string]$SupervisorConfigPath = 'D:\fqpack\config\supervisord.fqnext.conf'
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path

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

function Read-JsonFile {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "JSON file not found: $Path"
    }

    $content = [System.IO.File]::ReadAllText($Path, [System.Text.Encoding]::UTF8)
    if ([string]::IsNullOrWhiteSpace($content)) {
        return @()
    }

    return $content | ConvertFrom-Json
}

function Convert-ToObjectArray {
    param([Parameter(ValueFromPipeline = $true)]$InputObject)

    if ($null -eq $InputObject) {
        return @()
    }

    if ($InputObject -is [System.Array]) {
        return @($InputObject)
    }

    if ($InputObject -is [System.Collections.IEnumerable] -and -not ($InputObject -is [string])) {
        return @($InputObject)
    }

    return @($InputObject)
}

function Normalize-Text {
    param([string]$Value)

    if ([string]::IsNullOrWhiteSpace($Value)) {
        return ''
    }

    return (($Value -replace '\s+', ' ').Trim()).ToLowerInvariant()
}

function Get-StringProperty {
    param(
        [Parameter(Mandatory = $true)]$Object,
        [Parameter(Mandatory = $true)][string[]]$PropertyNames
    )

    foreach ($propertyName in $PropertyNames) {
        $property = $Object.PSObject.Properties[$propertyName]
        if ($null -ne $property -and -not [string]::IsNullOrWhiteSpace([string]$property.Value)) {
            return [string]$property.Value
        }
    }

    return $null
}

function ConvertTo-IsoTimestamp {
    param([datetime]$Value)

    return $Value.ToString('o')
}

$surfaceAliasMap = @{
    api = 'api'
    apiserver = 'api'
    rear = 'api'
    web = 'web'
    webui = 'web'
    fqwebui = 'web'
    dagster = 'dagster'
    qa = 'qa'
    qawebserver = 'qa'
    tradingagents = 'tradingagents'
    'tradingagents-cn' = 'tradingagents'
    symphony = 'symphony'
    'market_data' = 'market_data'
    'market-data' = 'market_data'
    guardian = 'guardian'
    strategy = 'guardian'
    signal = 'guardian'
    'position_management' = 'position_management'
    'position-management' = 'position_management'
    tpsl = 'tpsl'
}

$knownDeploymentSurfaces = @(
    'api',
    'web',
    'dagster',
    'qa',
    'tradingagents',
    'symphony',
    'market_data',
    'guardian',
    'position_management',
    'tpsl',
    'order_management'
)

$dockerSurfaceMap = @{
    api = @('fq_apiserver')
    web = @('fq_webui')
    dagster = @('fq_dagster_webserver', 'fq_dagster_daemon')
    qa = @('fq_qawebserver')
    tradingagents = @('ta_backend', 'ta_frontend')
}

$baseContainerNames = @('fq_mongodb', 'fq_redis')
$serviceSpecs = @(
    [pscustomobject]@{
        Name = 'fq-symphony-orchestrator'
        Surfaces = @('symphony')
    },
    [pscustomobject]@{
        Name = 'fqnext-supervisord'
        Surfaces = @('market_data', 'guardian', 'position_management', 'tpsl', 'order_management')
    }
)
$processSpecs = @(
    [pscustomobject]@{
        Id = 'market_data_producer'
        Surface = 'market_data'
        Pattern = 'python -m freshquant.market_data.xtdata.market_producer'
        SupervisorProgram = 'fqnext_realtime_xtdata_producer'
    },
    [pscustomobject]@{
        Id = 'market_data_consumer'
        Surface = 'market_data'
        Pattern = 'python -m freshquant.market_data.xtdata.strategy_consumer --prewarm'
        SupervisorProgram = 'fqnext_realtime_xtdata_consumer'
    },
    [pscustomobject]@{
        Id = 'guardian_monitor'
        Surface = 'guardian'
        Pattern = 'python -m freshquant.signal.astock.job.monitor_stock_zh_a_min --mode event'
        SupervisorProgram = 'fqnext_guardian_event'
    },
    [pscustomobject]@{
        Id = 'xtdata_adj_refresh_worker'
        Surface = 'market_data'
        Pattern = 'python -m freshquant.market_data.xtdata.adj_refresh_worker'
        SupervisorProgram = 'fqnext_xtdata_adj_refresh_worker'
    },
    [pscustomobject]@{
        Id = 'position_management_worker'
        Surface = 'position_management'
        Pattern = 'python -m freshquant.position_management.worker'
        SupervisorProgram = 'fqnext_position_management_worker'
    },
    [pscustomobject]@{
        Id = 'tpsl_tick_listener'
        Surface = 'tpsl'
        Pattern = 'python -m freshquant.tpsl.tick_listener'
        SupervisorProgram = 'fqnext_tpsl_worker'
    },
    [pscustomobject]@{
        Id = 'xtquant_broker'
        Surface = 'order_management'
        Pattern = 'python -m fqxtrade.xtquant.broker'
        SupervisorProgram = 'fqnext_xtquant_broker'
    },
    [pscustomobject]@{
        Id = 'credit_subjects_worker'
        Surface = 'order_management'
        Pattern = 'python -m freshquant.order_management.credit_subjects.worker'
        SupervisorProgram = 'fqnext_credit_subjects_worker'
    }
)

function Test-SpecTargetsDeploymentSurfaces {
    param(
        [Parameter(Mandatory = $true)]$Spec,
        [string[]]$DeploymentSurfaces
    )

    $surfaces = @()
    if ($null -ne $Spec.PSObject.Properties['Surfaces']) {
        $surfaces = @(Convert-ToObjectArray $Spec.Surfaces)
    }
    elseif ($null -ne $Spec.PSObject.Properties['Surface']) {
        $surfaces = @([string]$Spec.Surface)
    }

    foreach ($surface in $surfaces) {
        if ($DeploymentSurfaces -contains [string]$surface) {
            return $true
        }
    }

    return $false
}

function Resolve-DeploymentSurfaces {
    param([string[]]$Values)

    $resolved = [System.Collections.Generic.List[string]]::new()
    $seen = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)

    foreach ($rawValue in @($Values)) {
        foreach ($token in @($rawValue -split ',')) {
            $trimmed = $token.Trim()
            if ([string]::IsNullOrWhiteSpace($trimmed)) {
                continue
            }

            $normalized = $trimmed.ToLowerInvariant()
            if ($surfaceAliasMap.ContainsKey($normalized)) {
                $normalized = $surfaceAliasMap[$normalized]
            }

            if ($knownDeploymentSurfaces -notcontains $normalized) {
                $supported = $knownDeploymentSurfaces -join ', '
                throw "Unknown deployment surface: $trimmed. Supported surfaces: $supported"
            }

            if ($seen.Add($normalized)) {
                $resolved.Add($normalized)
            }
        }
    }

    return @($resolved)
}

function Get-AllKnownContainerNames {
    $names = [System.Collections.Generic.List[string]]::new()
    $seen = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)

    foreach ($name in $baseContainerNames) {
        if ($seen.Add($name)) {
            $names.Add($name)
        }
    }

    foreach ($entry in $dockerSurfaceMap.GetEnumerator()) {
        foreach ($name in $entry.Value) {
            if ($seen.Add($name)) {
                $names.Add($name)
            }
        }
    }

    return @($names)
}

function Resolve-ContainerName {
    param(
        $Entry,
        [string[]]$KnownNames = @()
    )

    $value = Get-StringProperty -Object $Entry -PropertyNames @('Name', 'name', 'Names', 'names')
    if ([string]::IsNullOrWhiteSpace($value)) {
        return $null
    }

    $normalized = $value.Trim()
    if ($normalized.StartsWith('/')) {
        $normalized = $normalized.TrimStart('/')
    }

    if (@($KnownNames).Count -gt 0) {
        if ($KnownNames -contains $normalized) {
            return $normalized
        }

        $orderedKnownNames = @($KnownNames | Sort-Object Length -Descending)
        foreach ($knownName in $orderedKnownNames) {
            $escapedName = [regex]::Escape($knownName)
            if ($normalized -match "(?:^|[-_])$escapedName(?:[-_]\d+)?$") {
                return $knownName
            }
        }
    }

    return $normalized
}

function Get-DockerSnapshot {
    param([string[]]$ContainerNames)

    if (-not [string]::IsNullOrWhiteSpace($DockerSnapshotPath)) {
        return Convert-ToObjectArray (Read-JsonFile -Path $DockerSnapshotPath)
    }

    $availableContainerNames = @(& docker ps -a --format '{{.Names}}' 2>$null)
    $snapshot = @()
    foreach ($name in $ContainerNames) {
        $inspectTarget = $name
        if ($availableContainerNames -notcontains $name) {
            $escapedName = [regex]::Escape($name)
            foreach ($candidate in $availableContainerNames) {
                if ($candidate -match "(?:^|[-_])$escapedName(?:[-_]\d+)?$") {
                    $inspectTarget = $candidate
                    break
                }
            }
        }

        $inspectJson = & docker inspect $inspectTarget 2>$null
        if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace(($inspectJson | Out-String))) {
            $snapshot += [pscustomobject]@{
                Name = $name
                Missing = $true
            }
            continue
        }

        foreach ($entry in @(Convert-ToObjectArray ($inspectJson | ConvertFrom-Json))) {
            $entry.Name = $name
            $snapshot += $entry
        }
    }

    return $snapshot
}

function Get-ServiceSnapshot {
    if (-not [string]::IsNullOrWhiteSpace($ServiceSnapshotPath)) {
        return Convert-ToObjectArray (Read-JsonFile -Path $ServiceSnapshotPath)
    }

    $services = @()
    foreach ($serviceSpec in $serviceSpecs) {
        $service = Get-Service -Name $serviceSpec.Name -ErrorAction SilentlyContinue
        if ($null -ne $service) {
            $services += [pscustomobject]@{
                Name = $service.Name
                Status = [string]$service.Status
            }
        }
    }

    return $services
}

function Get-SupervisorProgramSnapshot {
    if (-not [string]::IsNullOrWhiteSpace($SupervisorSnapshotPath)) {
        return [pscustomobject]@{
            available = $true
            source = 'snapshot'
            programs = @(Convert-ToObjectArray (Read-JsonFile -Path $SupervisorSnapshotPath))
        }
    }

    if (-not [string]::IsNullOrWhiteSpace($ServiceSnapshotPath) -or -not [string]::IsNullOrWhiteSpace($ProcessSnapshotPath)) {
        return [pscustomobject]@{
            available = $false
            source = 'disabled_for_test_snapshots'
            programs = @()
        }
    }

    $statusScript = Join-Path $repoRoot 'script\fqnext_host_runtime.py'
    if (-not (Test-Path $statusScript)) {
        return [pscustomobject]@{
            available = $false
            source = 'missing_host_runtime_script'
            programs = @()
        }
    }

    $command = @(
        'py',
        '-3.12',
        $statusScript,
        '--config-path',
        $SupervisorConfigPath,
        'status'
    )
    $result = & $command[0] $command[1..($command.Count - 1)] 2>$null
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace(($result | Out-String))) {
        return [pscustomobject]@{
            available = $false
            source = 'live_query_failed'
            programs = @()
        }
    }

    $payload = $result | ConvertFrom-Json
    return [pscustomobject]@{
        available = $true
        source = 'live_query'
        programs = @(Convert-ToObjectArray $payload.programs)
    }
}

function Get-ProcessSnapshot {
    if (-not [string]::IsNullOrWhiteSpace($ProcessSnapshotPath)) {
        return Convert-ToObjectArray (Read-JsonFile -Path $ProcessSnapshotPath)
    }

    return @(Get-CimInstance Win32_Process | Select-Object ProcessId, Name, CommandLine)
}

function Normalize-DockerBaseline {
    param(
        [object[]]$Snapshot,
        [string[]]$ContainerNames
    )

    $lookup = @{}
    foreach ($entry in @($Snapshot)) {
        $name = Resolve-ContainerName -Entry $entry -KnownNames $ContainerNames
        if ([string]::IsNullOrWhiteSpace($name)) {
            continue
        }

        $lookup[$name] = $entry
    }

    $normalized = foreach ($name in $ContainerNames) {
        $entry = $lookup[$name]
        $exists = $false
        $stateStatus = 'missing'
        $healthStatus = $null
        $statusText = $null

        $isMissing = $false
        if ($null -ne $entry -and $null -ne $entry.PSObject.Properties['Missing']) {
            $isMissing = [bool]$entry.PSObject.Properties['Missing'].Value
        }

        if ($null -ne $entry -and -not $isMissing) {
            $exists = $true
            if ($null -ne $entry.PSObject.Properties['State']) {
                $stateStatus = [string]$entry.State.Status
                if ($null -ne $entry.State.Health) {
                    $healthStatus = [string]$entry.State.Health.Status
                }
            }

            if ([string]::IsNullOrWhiteSpace($stateStatus)) {
                $stateStatus = Get-StringProperty -Object $entry -PropertyNames @('state_status', 'StateStatus', 'Status')
            }
            if ([string]::IsNullOrWhiteSpace($healthStatus)) {
                $healthStatus = Get-StringProperty -Object $entry -PropertyNames @('health_status', 'HealthStatus')
            }
            $statusText = Get-StringProperty -Object $entry -PropertyNames @('Status', 'status', 'StateText', 'state_text')
        }

        [pscustomobject]@{
            name = $name
            exists = $exists
            state_status = $stateStatus
            health_status = $healthStatus
            status_text = $statusText
        }
    }

    return @($normalized)
}

function Normalize-ServiceBaseline {
    param([object[]]$Snapshot)

    $lookup = @{}
    foreach ($entry in @($Snapshot)) {
        $name = Get-StringProperty -Object $entry -PropertyNames @('Name', 'name')
        if ([string]::IsNullOrWhiteSpace($name)) {
            continue
        }

        $lookup[$name] = $entry
    }

    $normalized = foreach ($serviceSpec in $serviceSpecs) {
        $entry = $lookup[$serviceSpec.Name]
        $exists = $null -ne $entry
        $status = if ($exists) {
            Get-StringProperty -Object $entry -PropertyNames @('Status', 'status')
        }
        else {
            'Missing'
        }

        [pscustomobject]@{
            name = $serviceSpec.Name
            surfaces = if ($null -ne $serviceSpec.PSObject.Properties['Surfaces']) { @($serviceSpec.Surfaces) } else { @([string]$serviceSpec.Surface) }
            exists = $exists
            status = $status
        }
    }

    return @($normalized)
}

function Normalize-ProcessBaseline {
    param(
        [object[]]$Snapshot,
        [object]$SupervisorState
    )

    $normalizedSnapshot = foreach ($entry in @($Snapshot)) {
        [pscustomobject]@{
            process_id = Get-StringProperty -Object $entry -PropertyNames @('ProcessId', 'Id', 'process_id')
            name = Get-StringProperty -Object $entry -PropertyNames @('Name', 'ProcessName', 'name')
            command_line = Get-StringProperty -Object $entry -PropertyNames @('CommandLine', 'command_line')
        }
    }

    $supervisorLookup = @{}
    $supervisorAvailable = $false
    if ($null -ne $SupervisorState -and $null -ne $SupervisorState.PSObject.Properties['available']) {
        $supervisorAvailable = [bool]$SupervisorState.available
    }
    foreach ($entry in @(Convert-ToObjectArray $SupervisorState.programs)) {
        $programName = Get-StringProperty -Object $entry -PropertyNames @('name', 'Name')
        if ([string]::IsNullOrWhiteSpace($programName)) {
            continue
        }

        $supervisorLookup[$programName] = $entry
    }

    $baseline = foreach ($processSpec in $processSpecs) {
        $supervisorProgram = if ($null -ne $processSpec.PSObject.Properties['SupervisorProgram']) {
            [string]$processSpec.SupervisorProgram
        }
        else {
            $null
        }

        if ($supervisorAvailable -and -not [string]::IsNullOrWhiteSpace($supervisorProgram)) {
            $supervisorEntry = $supervisorLookup[$supervisorProgram]
            $supervisorStateName = if ($null -ne $supervisorEntry) {
                Get-StringProperty -Object $supervisorEntry -PropertyNames @('statename', 'state', 'State')
            }
            else {
                'Missing'
            }
            $supervisorRunning = ((Normalize-Text -Value $supervisorStateName) -eq 'running')
            $matches = @()
            if ($supervisorRunning) {
                $matches = @(
                    [pscustomobject]@{
                        process_id = Get-StringProperty -Object $supervisorEntry -PropertyNames @('pid', 'process_id', 'ProcessId')
                        name = $supervisorProgram
                        command_line = $processSpec.Pattern
                        source = 'supervisor'
                    }
                )
            }

            [pscustomobject]@{
                id = $processSpec.Id
                surface = $processSpec.Surface
                pattern = $processSpec.Pattern
                source = 'supervisor'
                running = $supervisorRunning
                match_count = $matches.Count
                matches = @($matches)
            }
            continue
        }

        $pattern = Normalize-Text -Value $processSpec.Pattern
        $matches = @(
            $normalizedSnapshot |
                Where-Object {
                    -not [string]::IsNullOrWhiteSpace($_.command_line) -and
                    (Normalize-Text -Value $_.command_line).Contains($pattern)
                }
        )

        [pscustomobject]@{
            id = $processSpec.Id
            surface = $processSpec.Surface
            pattern = $processSpec.Pattern
            source = 'process_snapshot'
            running = ($matches.Count -gt 0)
            match_count = $matches.Count
            matches = @($matches)
        }
    }

    return @($baseline)
}

function Read-Baseline {
    param([Parameter(Mandatory = $true)][string]$Path)

    $payload = Read-JsonFile -Path $Path
    if ($null -ne $payload.PSObject.Properties['baseline']) {
        return $payload.baseline
    }

    return $payload
}

function Get-DockerChecks {
    param(
        [object[]]$CurrentEntries,
        [string[]]$RequiredContainerNames
    )

    $lookup = @{}
    foreach ($entry in @($CurrentEntries)) {
        $lookup[$entry.name] = $entry
    }

    $checks = @()
    $failures = [System.Collections.Generic.List[string]]::new()

    foreach ($name in $RequiredContainerNames) {
        $entry = $lookup[$name]
        $exists = ($null -ne $entry -and [bool]$entry.exists)
        $stateStatus = if ($null -ne $entry) { [string]$entry.state_status } else { 'missing' }
        $healthStatus = if ($null -ne $entry) { [string]$entry.health_status } else { $null }
        $reasons = [System.Collections.Generic.List[string]]::new()

        if (-not $exists) {
            $reasons.Add('required container missing')
        }
        elseif ($stateStatus -eq 'restarting') {
            $reasons.Add('container is Restarting')
        }
        elseif ($stateStatus -eq 'exited') {
            $reasons.Add('container is Exited')
        }
        elseif ($stateStatus -ne 'running') {
            $reasons.Add("container state is $stateStatus")
        }

        if ($healthStatus -eq 'unhealthy') {
            $reasons.Add('container health is unhealthy')
        }

        $passed = ($reasons.Count -eq 0)
        if (-not $passed) {
            $failures.Add(("docker check failed: {0}; {1}" -f $name, ($reasons -join ', ')))
        }

        $checks += [pscustomobject]@{
            name = $name
            required = $true
            exists = $exists
            state_status = $stateStatus
            health_status = $healthStatus
            passed = $passed
            reasons = @($reasons)
        }
    }

    return @{
        Checks = @($checks)
        Failures = @($failures)
    }
}

function Get-ServiceChecks {
    param(
        [object[]]$CurrentEntries,
        [object]$Baseline,
        [string[]]$DeploymentSurfaces
    )

    $currentLookup = @{}
    foreach ($entry in @($CurrentEntries)) {
        $currentLookup[$entry.name] = $entry
    }

    $baselineLookup = @{}
    foreach ($entry in @(Convert-ToObjectArray $Baseline.services)) {
        $baselineLookup[$entry.name] = $entry
    }

    $checks = @()
    $warnings = [System.Collections.Generic.List[string]]::new()
    $failures = [System.Collections.Generic.List[string]]::new()

    foreach ($serviceSpec in $serviceSpecs) {
        $current = $currentLookup[$serviceSpec.Name]
        $baselineEntry = $baselineLookup[$serviceSpec.Name]
        $required = Test-SpecTargetsDeploymentSurfaces -Spec $serviceSpec -DeploymentSurfaces $DeploymentSurfaces
        $status = if ($null -ne $current) { [string]$current.status } else { 'Missing' }
        $baselineStatus = if ($null -ne $baselineEntry) { [string]$baselineEntry.status } else { 'Missing' }
        $reasons = [System.Collections.Generic.List[string]]::new()

        if ($required) {
            if ($status -ne 'Running') {
                $reasons.Add("service status is $status")
            }
        }
        elseif ($baselineStatus -eq 'Running' -and $status -ne 'Running') {
            $warnings.Add(("host service drifted: {0} baseline=Running current={1}" -f $serviceSpec.Name, $status))
        }

        $passed = ($reasons.Count -eq 0)
        if (-not $passed) {
            $failures.Add(("host service check failed: {0}; {1}" -f $serviceSpec.Name, ($reasons -join ', ')))
        }

        $checks += [pscustomobject]@{
            name = $serviceSpec.Name
            surfaces = if ($null -ne $serviceSpec.PSObject.Properties['Surfaces']) { @($serviceSpec.Surfaces) } else { @([string]$serviceSpec.Surface) }
            required = $required
            baseline_status = $baselineStatus
            status = $status
            passed = $passed
            reasons = @($reasons)
        }
    }

    return @{
        Checks = @($checks)
        Warnings = @($warnings)
        Failures = @($failures)
    }
}

function Get-ProcessChecks {
    param(
        [object[]]$CurrentEntries,
        [object]$Baseline,
        [string[]]$DeploymentSurfaces
    )

    $currentLookup = @{}
    foreach ($entry in @($CurrentEntries)) {
        $currentLookup[$entry.id] = $entry
    }

    $baselineLookup = @{}
    foreach ($entry in @(Convert-ToObjectArray $Baseline.processes)) {
        $baselineLookup[$entry.id] = $entry
    }

    $checks = @()
    $warnings = [System.Collections.Generic.List[string]]::new()
    $failures = [System.Collections.Generic.List[string]]::new()

    foreach ($processSpec in $processSpecs) {
        $current = $currentLookup[$processSpec.Id]
        $baselineEntry = $baselineLookup[$processSpec.Id]
        $baselineRunning = $false
        if ($null -ne $baselineEntry -and $null -ne $baselineEntry.PSObject.Properties['running']) {
            $baselineRunning = [bool]$baselineEntry.running
        }

        $currentRunning = ($null -ne $current -and [bool]$current.running)
        $required = $baselineRunning -or ($DeploymentSurfaces -contains $processSpec.Surface)
        $requiredReason = if ($baselineRunning -and ($DeploymentSurfaces -contains $processSpec.Surface)) {
            'baseline running and targeted by this deploy'
        }
        elseif ($baselineRunning) {
            'baseline running before deploy'
        }
        elseif ($DeploymentSurfaces -contains $processSpec.Surface) {
            'targeted surface must be restored'
        }
        else {
            'observe only'
        }

        $reasons = [System.Collections.Generic.List[string]]::new()
        if ($required -and -not $currentRunning) {
            $reasons.Add('critical process is not running')
        }

        if (-not $required -and -not $currentRunning) {
            $warnings.Add(("optional process is not running: {0}" -f $processSpec.Id))
        }

        $passed = ($reasons.Count -eq 0)
        if (-not $passed) {
            $failures.Add(("host process check failed: {0}; {1}" -f $processSpec.Id, ($reasons -join ', ')))
        }

        $checks += [pscustomobject]@{
            id = $processSpec.Id
            surface = $processSpec.Surface
            pattern = $processSpec.Pattern
            required = $required
            required_reason = $requiredReason
            baseline_running = $baselineRunning
            current_running = $currentRunning
            match_count = if ($null -ne $current) { [int]$current.match_count } else { 0 }
            passed = $passed
            reasons = @($reasons)
        }
    }

    return @{
        Checks = @($checks)
        Warnings = @($warnings)
        Failures = @($failures)
    }
}

$deploymentSurfaces = @(Resolve-DeploymentSurfaces -Values $DeploymentSurface)
$allContainerNames = @(Get-AllKnownContainerNames)
$dockerSnapshot = @(Get-DockerSnapshot -ContainerNames $allContainerNames)
$serviceSnapshot = @(Get-ServiceSnapshot)
$supervisorState = Get-SupervisorProgramSnapshot
$processSnapshot = @(Get-ProcessSnapshot)
$dockerBaseline = @(Normalize-DockerBaseline -Snapshot $dockerSnapshot -ContainerNames $allContainerNames)
$serviceBaseline = @(Normalize-ServiceBaseline -Snapshot $serviceSnapshot)
$processBaseline = @(Normalize-ProcessBaseline -Snapshot $processSnapshot -SupervisorState $supervisorState)

$result = [ordered]@{
    mode = $Mode
    deployment_surfaces = @($deploymentSurfaces)
    captured_at = ConvertTo-IsoTimestamp -Value (Get-Date)
    baseline = [ordered]@{
        docker = @($dockerBaseline)
        services = @($serviceBaseline)
        processes = @($processBaseline)
    }
    docker_checks = @()
    service_checks = @()
    process_checks = @()
    warnings = @()
    failures = @()
    passed = $true
}

if ($Mode -eq 'CaptureBaseline') {
    $json = $result | ConvertTo-Json -Depth 12
    if (-not [string]::IsNullOrWhiteSpace($OutputPath)) {
        Write-Utf8NoBomFile -Path $OutputPath -Content $json
    }
    Write-Output $json
    exit 0
}

if ([string]::IsNullOrWhiteSpace($BaselinePath)) {
    throw 'BaselinePath is required for Verify mode.'
}

$baseline = Read-Baseline -Path $BaselinePath
$result.baseline = $baseline

$requiredContainerNames = [System.Collections.Generic.List[string]]::new()
$requiredContainerSeen = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
foreach ($name in $baseContainerNames) {
    if ($requiredContainerSeen.Add($name)) {
        $requiredContainerNames.Add($name)
    }
}
foreach ($surface in $deploymentSurfaces) {
    if (-not $dockerSurfaceMap.ContainsKey($surface)) {
        continue
    }
    foreach ($name in $dockerSurfaceMap[$surface]) {
        if ($requiredContainerSeen.Add($name)) {
            $requiredContainerNames.Add($name)
        }
    }
}

$dockerChecks = Get-DockerChecks -CurrentEntries $dockerBaseline -RequiredContainerNames @($requiredContainerNames)
$serviceChecks = Get-ServiceChecks -CurrentEntries $serviceBaseline -Baseline $baseline -DeploymentSurfaces $deploymentSurfaces
$processChecks = Get-ProcessChecks -CurrentEntries $processBaseline -Baseline $baseline -DeploymentSurfaces $deploymentSurfaces

$result.docker_checks = $dockerChecks.Checks
$result.service_checks = $serviceChecks.Checks
$result.process_checks = $processChecks.Checks
$result.warnings = @($serviceChecks.Warnings + $processChecks.Warnings)
$result.failures = @($dockerChecks.Failures + $serviceChecks.Failures + $processChecks.Failures)
$result.passed = ($result.failures.Count -eq 0)

$verifyJson = $result | ConvertTo-Json -Depth 12
if (-not [string]::IsNullOrWhiteSpace($OutputPath)) {
    Write-Utf8NoBomFile -Path $OutputPath -Content $verifyJson
}
Write-Output $verifyJson

if (-not $result.passed) {
    exit 1
}

exit 0
