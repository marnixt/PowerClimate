<#
.SYNOPSIS
    Deploy the committed PowerClimate integration to a Home Assistant config directory.

.DESCRIPTION
    1. Refuses to run with uncommitted changes (only committed code is deployed).
    2. Runs the test suite and ruff (skip with -SkipChecks).
    3. Checks the target for drift: the deployed files must match the commit recorded
       in the target's .deployed_commit marker (or HEAD when there is no marker).
       Files changed or added directly on the target stop the deployment (override
       with -Force).
    4. Exports HEAD with "git archive" and mirrors it to the target with robocopy /MIR,
       so files that are no longer in the repository are removed as well.
    5. Writes the deployed commit to <target>\.deployed_commit.
    6. Optionally validates the Home Assistant configuration and restarts it (-Restart).

.PARAMETER Target
    The integration directory to deploy to; must end in custom_components\powerclimate.
    Defaults to the POWERCLIMATE_DEPLOY_TARGET environment variable.

.PARAMETER DryRun
    Show what would change on the target without changing anything.

.PARAMETER SkipChecks
    Skip pytest and ruff.

.PARAMETER Force
    Deploy even when the target contains changes that are not in git.

.PARAMETER Restart
    After deploying, check the configuration and restart Home Assistant through its
    REST API. Requires HA_URL (e.g. http://homeassistant.local:8123) and HA_TOKEN
    (a long-lived access token) environment variables.

.EXAMPLE
    .\scripts\deploy.ps1 -Target 'Z:\custom_components\powerclimate' -DryRun

.EXAMPLE
    .\scripts\deploy.ps1 -Target 'Z:\custom_components\powerclimate' -Restart
#>
[CmdletBinding()]
param(
    [string]$Target = $env:POWERCLIMATE_DEPLOY_TARGET,
    [switch]$DryRun,
    [switch]$SkipChecks,
    [switch]$Force,
    [switch]$Restart
)

$ErrorActionPreference = 'Stop'

$IntegrationPath = 'custom_components/powerclimate'
$MarkerName = '.deployed_commit'
$IgnoredDirs = @('__pycache__')

function Write-Step([string]$Message) {
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Fail([string]$Message) {
    Write-Host "ERROR: $Message" -ForegroundColor Red
    exit 1
}

function Invoke-Native([string]$Description, [scriptblock]$Command) {
    & $Command
    if ($LASTEXITCODE -ne 0) {
        Fail "$Description failed (exit code $LASTEXITCODE)."
    }
}

# Content comparison that ignores CRLF/LF differences.
function Get-NormalizedBytes([byte[]]$Bytes) {
    $list = New-Object System.Collections.Generic.List[byte]($Bytes.Length)
    foreach ($b in $Bytes) {
        if ($b -ne 13) { $list.Add($b) }
    }
    return ,$list.ToArray()
}

function Test-SameContent([byte[]]$A, [byte[]]$B) {
    $na = Get-NormalizedBytes $A
    $nb = Get-NormalizedBytes $B
    if ($na.Length -ne $nb.Length) { return $false }
    for ($i = 0; $i -lt $na.Length; $i++) {
        if ($na[$i] -ne $nb[$i]) { return $false }
    }
    return $true
}

function Get-GitBlobBytes([string]$Commit, [string]$Path) {
    $tmp = [System.IO.Path]::GetTempFileName()
    try {
        # cmd redirection keeps the blob bytes intact (PowerShell 5.1 pipes re-encode).
        cmd /c "git show `"$($Commit):$Path`" > `"$tmp`""
        if ($LASTEXITCODE -ne 0) { Fail "Could not read $Path at $Commit." }
        return ,[System.IO.File]::ReadAllBytes($tmp)
    }
    finally {
        Remove-Item -Force $tmp -ErrorAction SilentlyContinue
    }
}

function Get-TargetFiles([string]$Root) {
    $rootFull = (Resolve-Path $Root).Path.TrimEnd('\')
    Get-ChildItem -Path $rootFull -Recurse -File -Force | Where-Object {
        $relative = $_.FullName.Substring($rootFull.Length + 1)
        $parts = $relative -split '\\'
        ($_.Name -ne $MarkerName) -and -not ($parts | Where-Object { $IgnoredDirs -contains $_ })
    } | ForEach-Object {
        $_.FullName.Substring($rootFull.Length + 1) -replace '\\', '/'
    }
}

# --- Repository checks --------------------------------------------------------

$repoRoot = (git rev-parse --show-toplevel 2>$null)
if ($LASTEXITCODE -ne 0 -or -not $repoRoot) { Fail 'Run this script inside the PowerClimate git repository.' }
Set-Location $repoRoot

if (-not $Target) {
    Fail 'No target given. Use -Target or set POWERCLIMATE_DEPLOY_TARGET.'
}
$Target = $Target.TrimEnd('\', '/')
$targetLeaf = Split-Path $Target -Leaf
$targetParent = Split-Path $Target -Parent
if ($targetLeaf -ne 'powerclimate' -or (Split-Path $targetParent -Leaf) -ne 'custom_components') {
    Fail "Target must be a ...\custom_components\powerclimate directory, got '$Target'."
}
if (-not (Test-Path $targetParent)) {
    Fail "Target parent '$targetParent' does not exist (is the share connected?)."
}

$dirty = git status --porcelain
if ($dirty) {
    Fail "The working tree has uncommitted changes; commit or stash them first.`n$($dirty -join "`n")"
}

$head = (git rev-parse HEAD).Trim()
$headSummary = (git log -1 --format='%h %s').Trim()
Write-Step "Deploying $headSummary"

# --- Tests and lint -----------------------------------------------------------

if ($SkipChecks) {
    Write-Step 'Skipping tests and lint (-SkipChecks)'
}
else {
    Write-Step 'Running tests'
    Invoke-Native 'pytest' { python -m pytest -q }
    Write-Step 'Running ruff'
    Invoke-Native 'ruff' { ruff check custom_components tests }
}

# --- Drift detection ----------------------------------------------------------

if (Test-Path $Target) {
    $markerPath = Join-Path $Target $MarkerName
    if (Test-Path $markerPath) {
        $baseline = (Get-Content -Raw $markerPath).Trim()
        git cat-file -e "$baseline^{commit}" 2>$null
        if ($LASTEXITCODE -ne 0) {
            Fail "Deployed commit $baseline is unknown locally; run 'git fetch' (or use -Force)."
        }
        Write-Step "Checking target against deployed commit $($baseline.Substring(0, 7))"
    }
    else {
        $baseline = $head
        Write-Step 'No deployment marker on target; checking target against HEAD'
    }

    $expected = @(git ls-tree -r --name-only $baseline -- $IntegrationPath | ForEach-Object {
        $_.Substring($IntegrationPath.Length + 1)
    })
    $actual = @(Get-TargetFiles $Target)

    $drift = New-Object System.Collections.Generic.List[string]
    foreach ($file in $expected) {
        $targetFile = Join-Path $Target ($file -replace '/', '\')
        if (-not (Test-Path $targetFile)) { continue }  # missing files are restored
        $repoBytes = Get-GitBlobBytes $baseline "$IntegrationPath/$file"
        $targetBytes = [System.IO.File]::ReadAllBytes($targetFile)
        if (-not (Test-SameContent $repoBytes $targetBytes)) {
            $drift.Add("modified on target: $file")
        }
    }
    foreach ($file in $actual) {
        if ($expected -notcontains $file) {
            $drift.Add("not in git:         $file")
        }
    }

    if ($drift.Count -gt 0) {
        Write-Host ''
        Write-Host 'The target contains changes that are not in git:' -ForegroundColor Yellow
        $drift | ForEach-Object { Write-Host "  $_" -ForegroundColor Yellow }
        Write-Host ''
        if (-not $Force) {
            Fail 'Deployment stopped. Bring these changes into git first, or rerun with -Force to overwrite them.'
        }
        Write-Host 'Continuing because -Force was given; these changes will be lost.' -ForegroundColor Yellow
    }
}

# --- Export and mirror --------------------------------------------------------

$staging = Join-Path ([System.IO.Path]::GetTempPath()) ("powerclimate-deploy-" + [guid]::NewGuid())
New-Item -ItemType Directory -Path $staging | Out-Null
try {
    $archive = Join-Path $staging 'export.tar'
    Invoke-Native 'git archive' { git archive --format=tar -o $archive HEAD -- $IntegrationPath }
    Invoke-Native 'tar' { tar -xf $archive -C $staging }
    $source = Join-Path $staging ($IntegrationPath -replace '/', '\')
    Set-Content -Path (Join-Path $source $MarkerName) -Value $head -Encoding Ascii

    $robocopyArgs = @($source, $Target, '/MIR', '/XD') + $IgnoredDirs + @('/NJH', '/NJS', '/NDL', '/NP')
    if ($DryRun) {
        Write-Step "Dry run: changes that would be made to $Target"
        $robocopyArgs += '/L'
    }
    else {
        Write-Step "Mirroring to $Target"
    }
    & robocopy @robocopyArgs
    # robocopy exit codes 0-7 mean success (bit flags for copied/extra/mismatched files).
    if ($LASTEXITCODE -ge 8) { Fail "robocopy failed (exit code $LASTEXITCODE)." }
    $global:LASTEXITCODE = 0
}
finally {
    Remove-Item -Recurse -Force $staging -ErrorAction SilentlyContinue
}

if ($DryRun) {
    Write-Step 'Dry run finished; nothing was changed.'
    exit 0
}
Write-Step "Deployed $headSummary"

# --- Restart Home Assistant ---------------------------------------------------

if ($Restart) {
    if (-not $env:HA_URL -or -not $env:HA_TOKEN) {
        Fail 'Set HA_URL and HA_TOKEN to restart Home Assistant; deployment itself succeeded.'
    }
    $baseUrl = $env:HA_URL.TrimEnd('/')
    $headers = @{ Authorization = "Bearer $($env:HA_TOKEN)" }

    Write-Step 'Checking Home Assistant configuration'
    $check = Invoke-RestMethod -Method Post -Uri "$baseUrl/api/config/core/check_config" -Headers $headers
    if ($check.result -ne 'valid') {
        Fail "Configuration check failed; not restarting.`n$($check.errors)"
    }

    Write-Step 'Restarting Home Assistant'
    try {
        Invoke-RestMethod -Method Post -Uri "$baseUrl/api/services/homeassistant/restart" -Headers $headers -TimeoutSec 15 | Out-Null
    }
    catch {
        # The connection is often dropped while Home Assistant shuts down.
        Write-Host "Restart requested (response: $($_.Exception.Message))."
    }
    Write-Step 'Restart requested'
}
