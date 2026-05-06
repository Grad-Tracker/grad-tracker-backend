# Rebuild a fresh local Grad Tracker database from the live Postgres source.
#
# Required environment variables:
#   SOURCE_DATABASE_URL       Direct Postgres URL for the live source database.
#   LOCAL_ADMIN_DATABASE_URL  Local admin/maintenance Postgres URL, usually ending in /postgres.
#   LOCAL_TARGET_DATABASE_URL Local target Postgres URL for the database being rebuilt.
#
# Optional:
#   LOCAL_DATABASE_NAME       Database name to create/drop. If omitted, this script tries to
#                             derive it from LOCAL_TARGET_DATABASE_URL, then falls back to
#                             grad_tracker_rebuild.
#
# Example:
#   $env:SOURCE_DATABASE_URL='postgresql://...'
#   $env:LOCAL_ADMIN_DATABASE_URL='postgresql://postgres:postgres@localhost:5432/postgres'
#   $env:LOCAL_TARGET_DATABASE_URL='postgresql://postgres:postgres@localhost:5432/grad_tracker_rebuild'
#   .\scripts\rebuild_local_db.ps1 -ForceDrop

[CmdletBinding()]
param(
    [switch]$ForceDrop,
    [switch]$SchemaOnly,
    [string]$DatabaseName = $env:LOCAL_DATABASE_NAME,
    [string]$DumpDir = ".db_dumps/latest"
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

function Require-EnvVar {
    param(
        [Parameter(Mandatory = $true)][string]$Name
    )

    $value = [Environment]::GetEnvironmentVariable($Name)
    if ([string]::IsNullOrWhiteSpace($value)) {
        throw "Missing required environment variable: $Name"
    }

    return $value
}

function Require-Tool {
    param(
        [Parameter(Mandatory = $true)][string]$Name
    )

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

function Get-DatabaseNameFromUrl {
    param(
        [Parameter(Mandatory = $true)][string]$DatabaseUrl
    )

    try {
        $uri = [Uri]$DatabaseUrl
        $name = $uri.AbsolutePath.Trim("/")
        if (-not [string]::IsNullOrWhiteSpace($name)) {
            return $name
        }
    }
    catch {
        return $null
    }

    return $null
}

function Test-DatabaseExists {
    param(
        [Parameter(Mandatory = $true)][string]$AdminDatabaseUrl,
        [Parameter(Mandatory = $true)][string]$Name
    )

    $result = Invoke-ExternalOutput `
        -Program "psql" `
        -Arguments @(
            "--dbname=$AdminDatabaseUrl",
            "-v",
            "dbname=$Name",
            "-tAc",
            "select 1 from pg_database where datname = :'dbname';"
        ) `
        -Description "checking if local database exists"

    return (($result -join "").Trim() -eq "1")
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

function Get-TableCount {
    param(
        [Parameter(Mandatory = $true)][string]$TargetDatabaseUrl,
        [Parameter(Mandatory = $true)][string]$Table
    )

    $sql = "select count(*)::bigint from public.$Table;"
    $result = Invoke-ExternalOutput `
        -Program "psql" `
        -Arguments @("--dbname=$TargetDatabaseUrl", "-tAc", $sql) `
        -Description "counting table $Table"

    return [int64](($result -join "").Trim())
}

function Install-LocalSupabaseCompatibility {
    param(
        [Parameter(Mandatory = $true)][string]$TargetDatabaseUrl
    )

    $sql = @'
do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'anon') then
    create role anon nologin;
  end if;

  if not exists (select 1 from pg_roles where rolname = 'authenticated') then
    create role authenticated nologin;
  end if;

  if not exists (select 1 from pg_roles where rolname = 'service_role') then
    create role service_role nologin;
  end if;
end
$$;

create schema if not exists auth;

create or replace function auth.uid()
returns uuid
language sql
stable
as $$
  select null::uuid;
$$;

create or replace function auth.role()
returns text
language sql
stable
as $$
  select null::text;
$$;

create or replace function auth.email()
returns text
language sql
stable
as $$
  select null::text;
$$;

create or replace function auth.jwt()
returns jsonb
language sql
stable
as $$
  select '{}'::jsonb;
$$;
'@

    Invoke-External `
        -Program "psql" `
        -Arguments @(
            "--dbname=$TargetDatabaseUrl",
            "-v",
            "ON_ERROR_STOP=1",
            "--command=$sql"
        ) `
        -Description "Installing local Supabase compatibility roles and auth stubs"
}

$SourceDatabaseUrl = Require-EnvVar "SOURCE_DATABASE_URL"
$LocalAdminDatabaseUrl = Require-EnvVar "LOCAL_ADMIN_DATABASE_URL"
$LocalTargetDatabaseUrl = Require-EnvVar "LOCAL_TARGET_DATABASE_URL"

if ([string]::IsNullOrWhiteSpace($DatabaseName)) {
    $DatabaseName = Get-DatabaseNameFromUrl $LocalTargetDatabaseUrl
}

if ([string]::IsNullOrWhiteSpace($DatabaseName)) {
    $DatabaseName = "grad_tracker_rebuild"
}

Require-Tool "pg_dump"
Require-Tool "psql"
Require-Tool "createdb"
if ($ForceDrop) {
    Require-Tool "dropdb"
}

$RepoRoot = Split-Path -Parent $PSScriptRoot
if ([System.IO.Path]::IsPathRooted($DumpDir)) {
    $ResolvedDumpDir = $DumpDir
}
else {
    $ResolvedDumpDir = Join-Path $RepoRoot $DumpDir
}

$SchemaPath = Join-Path $ResolvedDumpDir "schema.sql"
$ReferenceSeedPath = Join-Path $ResolvedDumpDir "reference_seed.sql"

Write-Host "Grad Tracker local DB rebuild"
Write-Host "Target database: $DatabaseName"
Write-Host "Dump directory: $ResolvedDumpDir"

New-Item -ItemType Directory -Force -Path $ResolvedDumpDir | Out-Null

$databaseExists = Test-DatabaseExists -AdminDatabaseUrl $LocalAdminDatabaseUrl -Name $DatabaseName
if ($databaseExists -and -not $ForceDrop) {
    throw "Local database '$DatabaseName' already exists. Re-run with -ForceDrop to drop and recreate it."
}

if ($databaseExists -and $ForceDrop) {
    Invoke-External `
        -Program "dropdb" `
        -Arguments @("--if-exists", "--maintenance-db=$LocalAdminDatabaseUrl", $DatabaseName) `
        -Description "Dropping existing local database '$DatabaseName'"
}

Invoke-External `
    -Program "createdb" `
    -Arguments @("--maintenance-db=$LocalAdminDatabaseUrl", $DatabaseName) `
    -Description "Creating local database '$DatabaseName'"

Install-LocalSupabaseCompatibility -TargetDatabaseUrl $LocalTargetDatabaseUrl

Invoke-External `
    -Program "pg_dump" `
    -Arguments @(
        "--dbname=$SourceDatabaseUrl",
        "--schema=public",
        "--schema-only",
        "--no-owner",
        "--no-privileges",
        "--file=$SchemaPath"
    ) `
    -Description "Dumping live public schema to schema.sql"

Invoke-External `
    -Program "psql" `
    -Arguments @(
        "--dbname=$LocalTargetDatabaseUrl",
        "-v",
        "ON_ERROR_STOP=1",
        "--file=$SchemaPath"
    ) `
    -Description "Restoring schema into local database"

if (-not $SchemaOnly) {
    $existingReferenceTables = Get-ExistingSourceTables -SourceDatabaseUrl $SourceDatabaseUrl -Tables $ReferenceTables
    $missingReferenceTables = @($ReferenceTables | Where-Object { $existingReferenceTables -notcontains $_ })
    if ($missingReferenceTables.Count -gt 0) {
        throw "Source database is missing required reference tables: $($missingReferenceTables -join ', ')"
    }

    $dataDumpArgs = @(
        "--dbname=$SourceDatabaseUrl",
        "--schema=public",
        "--data-only",
        "--no-owner",
        "--no-privileges",
        "--file=$ReferenceSeedPath"
    )

    foreach ($table in $ReferenceTables) {
        $dataDumpArgs += "--table=public.$table"
    }

    Invoke-External `
        -Program "pg_dump" `
        -Arguments $dataDumpArgs `
        -Description "Dumping live reference data to reference_seed.sql"

    Invoke-External `
        -Program "psql" `
        -Arguments @(
            "--dbname=$LocalTargetDatabaseUrl",
            "-v",
            "ON_ERROR_STOP=1",
            "--file=$ReferenceSeedPath"
        ) `
        -Description "Restoring reference data into local database"

    Write-Host "Validating restored reference data"
    foreach ($table in $IncludedCountChecks) {
        $count = Get-TableCount -TargetDatabaseUrl $LocalTargetDatabaseUrl -Table $table
        Write-Host "  $table = $count"
        if ($count -le 0) {
            throw "Expected reference table '$table' to contain rows after restore."
        }
    }

    Write-Host "Validating excluded user/application data is empty"
    foreach ($table in $ExcludedZeroCountChecks) {
        $count = Get-TableCount -TargetDatabaseUrl $LocalTargetDatabaseUrl -Table $table
        Write-Host "  $table = $count"
        if ($count -ne 0) {
            throw "Expected excluded table '$table' to be empty after restore."
        }
    }
}
else {
    Write-Host "SchemaOnly was set; skipped reference data dump, restore, and seed validation."
}

Write-Host "Local database rebuild complete."
Write-Host "Generated: $SchemaPath"
if (-not $SchemaOnly) {
    Write-Host "Generated: $ReferenceSeedPath"
}
