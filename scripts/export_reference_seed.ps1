# Export safe Grad Tracker reference data only.
#
# Required environment variables:
#   SOURCE_DATABASE_URL  Direct Postgres URL for the live Supabase/Postgres database.
#
# Example:
#   $env:SOURCE_DATABASE_URL='postgresql://...'
#   .\scripts\export_reference_seed.ps1

[CmdletBinding()]
param(
    [string]$OutputPath = ".db_dumps/latest/reference_seed.sql"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ReferenceTables = @(
    "terms",
    "courses",
    "course_crosslistings",
    "course_offerings",
    "course_code_aliases",
    "course_req_sets",
    "course_req_nodes",
    "course_req_atoms",
    "programs",
    "program_requirement_blocks",
    "program_requirement_courses",
    "program_requirement_block_flags",
    "program_req_sets",
    "program_req_nodes",
    "program_req_atoms",
    "gen_ed_buckets",
    "gen_ed_bucket_courses",
    "major_certificate_mappings"
)

function Require-EnvVar {
    param([Parameter(Mandatory = $true)][string]$Name)

    $value = [Environment]::GetEnvironmentVariable($Name)
    if ([string]::IsNullOrWhiteSpace($value)) {
        throw "Missing required environment variable: $Name"
    }

    return $value
}

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

function Get-ExistingSourceTables {
    param(
        [Parameter(Mandatory = $true)][string]$SourceDatabaseUrl,
        [Parameter(Mandatory = $true)][string[]]$Tables
    )

    $quotedTables = ($Tables | ForEach-Object { "'" + $_.Replace("'", "''") + "'" }) -join ","
    $sql = "select tablename from pg_tables where schemaname = 'public' and tablename in ($quotedTables);"

    $result = Invoke-ExternalOutput `
        -Program "psql" `
        -Arguments @("--dbname=$SourceDatabaseUrl", "-tAc", $sql) `
        -Description "checking source reference tables"

    return @($result | ForEach-Object { $_.Trim() } | Where-Object { $_ })
}

$SourceDatabaseUrl = Require-EnvVar "SOURCE_DATABASE_URL"
Require-Tool "pg_dump"
Require-Tool "psql"

$RepoRoot = Split-Path -Parent $PSScriptRoot
if ([System.IO.Path]::IsPathRooted($OutputPath)) {
    $ResolvedOutputPath = $OutputPath
}
else {
    $ResolvedOutputPath = Join-Path $RepoRoot $OutputPath
}

$OutputDir = Split-Path -Parent $ResolvedOutputPath
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

$existingReferenceTables = Get-ExistingSourceTables -SourceDatabaseUrl $SourceDatabaseUrl -Tables $ReferenceTables
$missingReferenceTables = @($ReferenceTables | Where-Object { $existingReferenceTables -notcontains $_ })
if ($missingReferenceTables.Count -gt 0) {
    throw "Source database is missing required reference tables: $($missingReferenceTables -join ', ')"
}

$dumpArgs = @(
    "--dbname=$SourceDatabaseUrl",
    "--schema=public",
    "--data-only",
    "--no-owner",
    "--no-privileges",
    "--file=$ResolvedOutputPath"
)

foreach ($table in $ReferenceTables) {
    $dumpArgs += "--table=public.$table"
}

Invoke-External `
    -Program "pg_dump" `
    -Arguments $dumpArgs `
    -Description "Exporting safe reference data to $ResolvedOutputPath"

Write-Host "Reference seed export complete: $ResolvedOutputPath"
