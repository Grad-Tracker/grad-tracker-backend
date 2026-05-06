# Export the live Grad Tracker database schema only.
#
# This writes a schema-only SQL dump to sql/schema.sql. It does not export data.
#
# Required environment variables:
#   SOURCE_DATABASE_URL  Direct Postgres URL for the live Supabase/Postgres database.
#
# Example:
#   $env:SOURCE_DATABASE_URL='postgresql://...'
#   .\scripts\export_live_schema.ps1

[CmdletBinding()]
param(
    [string]$OutputPath = "sql/schema.sql"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

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

$SourceDatabaseUrl = Require-EnvVar "SOURCE_DATABASE_URL"
Require-Tool "pg_dump"

$RepoRoot = Split-Path -Parent $PSScriptRoot
if ([System.IO.Path]::IsPathRooted($OutputPath)) {
    $ResolvedOutputPath = $OutputPath
}
else {
    $ResolvedOutputPath = Join-Path $RepoRoot $OutputPath
}

$OutputDir = Split-Path -Parent $ResolvedOutputPath
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

Invoke-External `
    -Program "pg_dump" `
    -Arguments @(
        "--dbname=$SourceDatabaseUrl",
        "--schema=public",
        "--schema-only",
        "--no-owner",
        "--no-privileges",
        "--file=$ResolvedOutputPath"
    ) `
    -Description "Exporting live public schema to $ResolvedOutputPath"

Write-Host "Schema export complete: $ResolvedOutputPath"
