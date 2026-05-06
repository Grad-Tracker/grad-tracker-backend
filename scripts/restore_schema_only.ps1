# Restore the committed Grad Tracker schema into an existing local database.
#
# Required environment variables:
#   LOCAL_TARGET_DATABASE_URL  Local Postgres URL for the database being restored.
#
# Example:
#   $env:LOCAL_TARGET_DATABASE_URL='postgresql://postgres:postgres@localhost:5432/grad_tracker_rebuild'
#   .\scripts\restore_schema_only.ps1

[CmdletBinding()]
param(
    [string]$SchemaPath = "sql/schema.sql",
    [string]$TargetDatabaseUrl = $env:LOCAL_TARGET_DATABASE_URL
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

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

function Install-LocalSupabaseCompatibility {
    param([Parameter(Mandatory = $true)][string]$TargetDatabaseUrl)

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
        -Arguments @("--dbname=$TargetDatabaseUrl", "-v", "ON_ERROR_STOP=1", "--command=$sql") `
        -Description "Installing local Supabase compatibility roles and auth stubs"
}

if ([string]::IsNullOrWhiteSpace($TargetDatabaseUrl)) {
    throw "Missing required environment variable or parameter: LOCAL_TARGET_DATABASE_URL"
}

Require-Tool "psql"

$RepoRoot = Split-Path -Parent $PSScriptRoot
if ([System.IO.Path]::IsPathRooted($SchemaPath)) {
    $ResolvedSchemaPath = $SchemaPath
}
else {
    $ResolvedSchemaPath = Join-Path $RepoRoot $SchemaPath
}

if (-not (Test-Path -LiteralPath $ResolvedSchemaPath)) {
    throw "Schema file not found: $ResolvedSchemaPath. Generate it with scripts/export_live_schema.ps1 first."
}

Install-LocalSupabaseCompatibility -TargetDatabaseUrl $TargetDatabaseUrl

Invoke-External `
    -Program "psql" `
    -Arguments @("--dbname=$TargetDatabaseUrl", "-v", "ON_ERROR_STOP=1", "--file=$ResolvedSchemaPath") `
    -Description "Restoring schema from $ResolvedSchemaPath"

Write-Host "Schema restore complete."
