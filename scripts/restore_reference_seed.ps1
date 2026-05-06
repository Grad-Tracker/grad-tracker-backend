# Restore a generated Grad Tracker reference seed into an existing local database.
#
# Required environment variables:
#   LOCAL_TARGET_DATABASE_URL  Local Postgres URL for the database being seeded.
#
# Example:
#   $env:LOCAL_TARGET_DATABASE_URL='postgresql://postgres:postgres@localhost:5432/grad_tracker_rebuild'
#   .\scripts\restore_reference_seed.ps1

[CmdletBinding()]
param(
    [string]$SeedPath = ".db_dumps/latest/reference_seed.sql",
    [string]$TargetDatabaseUrl = $env:LOCAL_TARGET_DATABASE_URL,
    [switch]$SkipValidation
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$IncludedCountChecks = @(
    "courses",
    "programs",
    "program_requirement_blocks",
    "program_requirement_courses"
)

$ExcludedZeroCountChecks = @(
    "students",
    "staff",
    "ai_messages"
)

function Require-Tool {
    param([Parameter(Mandatory = $true)][string]$Name)

    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if (-not $command) {
        throw "Missing required PostgreSQL tool on PATH: $Name"
    }
}

function Invoke-External {
    param(
        [Parameter(Mandatory = $true)][string]$Program,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$Description
    )

    Write-Host $Description
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Program failed while running: $Description"
    }
}

function Invoke-ExternalOutput {
    param(
        [Parameter(Mandatory = $true)][string]$Program,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$Description
    )

    $output = & $Program @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Program failed while running: $Description"
    }

    return $output
}

function Get-TableCount {
    param(
        [Parameter(Mandatory = $true)][string]$TargetDatabaseUrl,
        [Parameter(Mandatory = $true)][string]$Table
    )

    $result = Invoke-ExternalOutput `
        -Program "psql" `
        -Arguments @("--dbname=$TargetDatabaseUrl", "-tAc", "select count(*)::bigint from public.$Table;") `
        -Description "counting table $Table"

    return [int64](($result -join "").Trim())
}

if ([string]::IsNullOrWhiteSpace($TargetDatabaseUrl)) {
    throw "Missing required environment variable or parameter: LOCAL_TARGET_DATABASE_URL"
}

Require-Tool "psql"

$RepoRoot = Split-Path -Parent $PSScriptRoot
if ([System.IO.Path]::IsPathRooted($SeedPath)) {
    $ResolvedSeedPath = $SeedPath
}
else {
    $ResolvedSeedPath = Join-Path $RepoRoot $SeedPath
}

if (-not (Test-Path -LiteralPath $ResolvedSeedPath)) {
    throw "Reference seed file not found: $ResolvedSeedPath. Generate it with scripts/export_reference_seed.ps1 or scripts/rebuild_local_db.ps1 first."
}

Invoke-External `
    -Program "psql" `
    -Arguments @("--dbname=$TargetDatabaseUrl", "-v", "ON_ERROR_STOP=1", "--file=$ResolvedSeedPath") `
    -Description "Restoring reference data from $ResolvedSeedPath"

if (-not $SkipValidation) {
    Write-Host "Validating restored reference data"
    foreach ($table in $IncludedCountChecks) {
        $count = Get-TableCount -TargetDatabaseUrl $TargetDatabaseUrl -Table $table
        Write-Host "  $table = $count"
        if ($count -le 0) {
            throw "Expected reference table '$table' to contain rows after restore."
        }
    }

    Write-Host "Validating excluded user/application data is empty"
    foreach ($table in $ExcludedZeroCountChecks) {
        $count = Get-TableCount -TargetDatabaseUrl $TargetDatabaseUrl -Table $table
        Write-Host "  $table = $count"
        if ($count -ne 0) {
            throw "Expected excluded table '$table' to be empty after restore."
        }
    }
}

Write-Host "Reference seed restore complete."
