[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string]$Target = "help"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$script:ProjectRoot = $PSScriptRoot
$script:VirtualEnvironment = Join-Path $script:ProjectRoot ".venv"
$script:IsDotSourced = $MyInvocation.InvocationName -eq "."

function Write-Usage {
    Write-Output @"
Job Application Copilot developer commands

Usage:
  .\dev.ps1 env        Create or update .venv with Poetry
  . .\dev.ps1 activate Activate .venv in the current PowerShell session
  .\dev.ps1 directories Create and validate private local directories
  .\dev.ps1 database   Migrate and validate the local SQLite database
  .\dev.ps1 database-sql Preview pending database migrations as SQL
  .\dev.ps1 test       Run the Pytest suite
  .\dev.ps1 lint       Run Ruff lint and formatting checks
  .\dev.ps1 ui         Start the Streamlit application
  .\dev.ps1 help       Show this help
"@
}

function Resolve-Poetry {
    $command = Get-Command "poetry" -CommandType Application -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($null -ne $command) {
        return $command.Source
    }

    $candidates = @()
    if ($env:APPDATA) {
        $candidates += Join-Path $env:APPDATA "Python\Scripts\poetry.exe"
        $candidates += Join-Path $env:APPDATA "pypoetry\venv\Scripts\poetry.exe"
    }

    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return $candidate
        }
    }

    throw "Poetry was not found. Install Poetry 2.x and ensure 'poetry' is on PATH."
}

function Resolve-VenvTool {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    $path = Join-Path $script:VirtualEnvironment "Scripts\$Name"
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "The project environment is missing or incomplete. Run '.\dev.ps1 env' first."
    }
    return $path
}

function Invoke-ProjectTool {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Executable,

        [Parameter()]
        [string[]]$Arguments = @()
    )

    Push-Location $script:ProjectRoot
    try {
        & $Executable @Arguments
        $exitCode = $LASTEXITCODE
    }
    finally {
        Pop-Location
    }

    if ($exitCode -ne 0) {
        throw "'$Executable' failed with exit code $exitCode."
    }
}

function Initialize-Environment {
    $poetry = Resolve-Poetry
    Invoke-ProjectTool -Executable $poetry -Arguments @("install")
}

function Enable-Environment {
    if (-not $script:IsDotSourced) {
        throw "Activation must be dot-sourced. Run: . .\dev.ps1 activate"
    }

    $activateScript = Resolve-VenvTool -Name "Activate.ps1"
    . $activateScript
    Write-Output "Activated $env:VIRTUAL_ENV"
}

function Invoke-Tests {
    $python = Resolve-VenvTool -Name "python.exe"
    Invoke-ProjectTool -Executable $python -Arguments @("-m", "pytest")
}

function Initialize-Directories {
    $python = Resolve-VenvTool -Name "python.exe"
    Invoke-ProjectTool -Executable $python -Arguments @(
        "-m",
        "job_application_copilot.services.local_directories"
    )
}

function Initialize-Database {
    $python = Resolve-VenvTool -Name "python.exe"
    Invoke-ProjectTool -Executable $python -Arguments @(
        "-m",
        "job_application_copilot.services.database_bootstrap"
    )
}

function Show-DatabaseMigrationSql {
    $python = Resolve-VenvTool -Name "python.exe"
    Invoke-ProjectTool -Executable $python -Arguments @(
        "-m",
        "alembic",
        "upgrade",
        "head",
        "--sql"
    )
}

function Invoke-Lint {
    $ruff = Resolve-VenvTool -Name "ruff.exe"
    Invoke-ProjectTool -Executable $ruff -Arguments @("check", ".")
    Invoke-ProjectTool -Executable $ruff -Arguments @("format", "--check", ".")
}

function Start-UserInterface {
    $streamlit = Resolve-VenvTool -Name "streamlit.exe"
    $application = Join-Path $script:ProjectRoot "src\job_application_copilot\ui\app.py"
    Invoke-ProjectTool -Executable $streamlit -Arguments @("run", $application)
}

switch ($Target.ToLowerInvariant()) {
    "env" {
        Initialize-Environment
    }
    "activate" {
        Enable-Environment
    }
    "directories" {
        Initialize-Directories
    }
    "database" {
        Initialize-Database
    }
    "database-sql" {
        Show-DatabaseMigrationSql
    }
    "test" {
        Invoke-Tests
    }
    "lint" {
        Invoke-Lint
    }
    "ui" {
        Start-UserInterface
    }
    { $_ -in @("help", "-h", "--help") } {
        Write-Usage
    }
    default {
        Write-Usage
        throw "Unknown target '$Target'."
    }
}
