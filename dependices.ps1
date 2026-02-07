# THIS IS FOR POWERSHELL USERS ONLY
# Installs Python dependencies for the project.
# Run from the repo root:  .\src\dependices.ps1
# Requires Python and pip to be installed.

# Fail on first error
$ErrorActionPreference = 'Stop'

Write-Host "Installing Python packages from requirements.txt..."
python -m pip install -r requirements.txt
Write-Host "Done."
