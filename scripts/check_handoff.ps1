# Validate that the repo is ready for backend/database handoff.
#
# This check is safe to run locally. PostgreSQL CLI tools are warnings by default
# because not every documentation-only environment has them installed.
#
# Example:
#   .\scripts\check_handoff.ps1
#   .\scripts\check_handoff.ps1 -RequirePostgresTools

[CmdletBinding()]
param(
    [switch]$RequirePostgresTools,
    [switch]$SkipTests
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$Failures = New-Object System.Collections.Generic.List[string]
$Warnings = New-Object System.Collections.Generic.List[string]

function Add-Problem {
    param(
        [Parameter(Mandatory = $true)][string]$Message,
        [switch]$Warning
    )

    if ($Warning) {
        $Warnings.Add($Message) | Out-Null
    }
    else {
        $Failures.Add($Message) | Out-Null
    }
}

function Test-RequiredPath {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not (Test-Path -LiteralPath (Join-Path $RepoRoot $Path))) {
        Add-Problem "Missing required handoff path: $Path"
    }
}

$requiredPaths = @(
    "README.md",
    "docs/database-schema-and-data-flow.md",
    "docs/database-scripts-readme.md",
    "docs/requirements.md",
    "scripts/export_live_schema.ps1",
    "scripts/export_reference_seed.ps1",
    "scripts/rebuild_local_db.ps1",
    "scripts/restore_schema_only.ps1",
    "scripts/restore_reference_seed.ps1",
    "scripts/validate_data.py",
    "src/legacy/README.md",
    "sql/README.md",
    "sql/migrations/README.md"
)

foreach ($path in $requiredPaths) {
    Test-RequiredPath $path
}

$rootGeneratedPatterns = @("*.sql", "*.json", "*.csv", "*.txt")
$allowedRootGeneratedNames = @("requirements.txt")
foreach ($pattern in $rootGeneratedPatterns) {
    $matches = Get-ChildItem -Path $RepoRoot -File -Filter $pattern -ErrorAction SilentlyContinue
    foreach ($match in $matches) {
        if ($allowedRootGeneratedNames -contains $match.Name) {
            continue
        }
        Add-Problem "Generated/root artifact should not be at repo root: $($match.Name)"
    }
}

$rootHistoryNames = @(
    "DATABASE_CHANGES.md",
    "DATABASE_CHANGES_BY_JIRA.md",
    "DATABASE_FERPA_AUDIT_2026-03-17.md",
    "DATABASE_HARDENING_IMPLEMENTATION.md",
    "DATABASE_HARDENING_NEXT_STEPS.md",
    "DATABASE_HARDENING_TODOS.md",
    "CLASS_SCRAPPER.md"
)

foreach ($name in $rootHistoryNames) {
    if (Test-Path -LiteralPath (Join-Path $RepoRoot $name)) {
        Add-Problem "Historical documentation should be under docs/: $name"
    }
}

$repoPycache = Get-ChildItem -Path $RepoRoot -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -notlike "*\.venv\*" }
foreach ($dir in $repoPycache) {
    Add-Problem "Python cache directory should not be committed or kept in source tree: $($dir.FullName.Replace($RepoRoot + '\', ''))"
}

foreach ($tool in @("pg_dump", "psql", "createdb", "dropdb")) {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
        Add-Problem "Missing PostgreSQL CLI tool on PATH: $tool" -Warning:(-not $RequirePostgresTools)
    }
}

if (-not $SkipTests) {
    Push-Location $RepoRoot
    try {
        python -m pytest -q
        if ($LASTEXITCODE -ne 0) {
            Add-Problem "Python tests failed: python -m pytest -q"
        }
    }
    finally {
        Pop-Location
    }
}

if ($Warnings.Count -gt 0) {
    Write-Host "Warnings:"
    foreach ($warning in $Warnings) {
        Write-Host "  - $warning"
    }
}

if ($Failures.Count -gt 0) {
    Write-Host "Failures:"
    foreach ($failure in $Failures) {
        Write-Host "  - $failure"
    }
    exit 1
}

Write-Host "Handoff check passed."
