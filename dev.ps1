[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string]$Target = "help",

    [Parameter()]
    [switch]$Force,

    [Parameter()]
    [int]$DocumentBVersion,

    [Parameter()]
    [string]$Lane
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$script:ProjectRoot = $PSScriptRoot
$script:VirtualEnvironment = Join-Path $script:ProjectRoot ".venv"
$script:IsDotSourced = $MyInvocation.InvocationName -eq "."
$script:UiWorkerStartupAttempts = 3
$script:UiWorkerStartupDelaySeconds = 1

function Write-Usage {
    Write-Output @"
Job Application Copilot developer commands

Usage:
  .\dev.ps1 env        Create or update .venv with Poetry
  . .\dev.ps1 activate Activate .venv in the current PowerShell session
  .\dev.ps1 directories Create and validate private local directories
  .\dev.ps1 database   Migrate and validate the local SQLite database
  .\dev.ps1 database-sql Preview pending database migrations as SQL
  .\dev.ps1 reset-reference-assets -Force Reset all development Settings assets
  .\dev.ps1 document-b-routing [-DocumentBVersion N] [-Lane LANE] Inspect routing
  .\dev.ps1 test       Run the Pytest suite
  .\dev.ps1 coverage   Run Pytest with branch coverage reporting
  .\dev.ps1 test-openai Run opt-in tests against real OpenAI files and vector stores
  .\dev.ps1 lint       Run Ruff lint and formatting checks
  .\dev.ps1 type       Run mypy static type checks
  .\dev.ps1 worker     Start the local sequential worker
  .\dev.ps1 ui         Start Streamlit and its local worker
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

function Test-ActiveWorkerLease {
    param(
        [Parameter(Mandatory = $true)]
        [string]$DataDirectory
    )

    $leasePath = Join-Path $DataDirectory "logs\worker.lock"
    try {
        $metadata = Get-Content -LiteralPath $leasePath -Raw -ErrorAction Stop | ConvertFrom-Json
        $process = Get-Process -Id ([int]$metadata.process_id) -ErrorAction Stop
        return $null -ne $process
    }
    catch {
        return $false
    }
}

function Start-UiWorker {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Python,

        [Parameter(Mandatory = $true)]
        [string]$StopFile,

        [Parameter(Mandatory = $true)]
        [string]$DataDirectory
    )

    for ($attempt = 1; $attempt -le $script:UiWorkerStartupAttempts; $attempt++) {
        $worker = Start-Process -FilePath $Python -ArgumentList @(
            "-m",
            "job_application_copilot.services.background_worker",
            "--stop-file",
            $StopFile
        ) -WorkingDirectory $script:ProjectRoot -WindowStyle Hidden -PassThru
        Start-Sleep -Seconds $script:UiWorkerStartupDelaySeconds
        if (-not $worker.HasExited) {
            return $worker
        }

        if ($attempt -lt $script:UiWorkerStartupAttempts) {
            Write-Warning (
                "Background worker exited during startup; retrying " +
                "($attempt of $script:UiWorkerStartupAttempts)."
            )
        }
    }

    if (Test-ActiveWorkerLease -DataDirectory $DataDirectory) {
        Write-Warning "A background worker is already active; the UI will use that worker."
        return $null
    }

    throw (
        "The background worker could not start after $script:UiWorkerStartupAttempts attempts. " +
        "Check data/logs/worker.log before starting the UI again."
    )
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

function New-PytestBaseTemp {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Prefix
    )

    $tempRoot = Join-Path $script:ProjectRoot ".pytest-tmp"
    try {
        New-Item -ItemType Directory -Path $tempRoot -Force -ErrorAction Stop | Out-Null
    }
    catch {
        throw "Cannot prepare pytest temp directory '$tempRoot': $($_.Exception.Message)"
    }

    return Join-Path $tempRoot "$Prefix-$([Guid]::NewGuid().ToString("N"))"
}

function Invoke-Tests {
    $python = Resolve-VenvTool -Name "python.exe"
    $baseTemp = New-PytestBaseTemp -Prefix "tests"
    Invoke-ProjectTool -Executable $python -Arguments @(
        "-m",
        "pytest",
        "--basetemp",
        $baseTemp
    )
}

function Invoke-Coverage {
    $python = Resolve-VenvTool -Name "python.exe"
    $baseTemp = New-PytestBaseTemp -Prefix "coverage"
    Invoke-ProjectTool -Executable $python -Arguments @(
        "-m",
        "pytest",
        "--basetemp",
        $baseTemp,
        "--cov=job_application_copilot",
        "--cov-branch",
        "--cov-report=term-missing"
    )
}

function Invoke-OpenAIIntegrationTests {
    $python = Resolve-VenvTool -Name "python.exe"
    $flagName = "JAC_RUN_OPENAI_INTEGRATION"
    $existingFlag = Get-Item -LiteralPath "Env:$flagName" -ErrorAction SilentlyContinue
    $baseTemp = New-PytestBaseTemp -Prefix "openai"

    Write-Output (
        "This target contacts OpenAI, uploads temporary DOCX files, creates and searches a " +
        "temporary vector store, and deletes the remote resources during test cleanup."
    )
    try {
        Set-Item -LiteralPath "Env:$flagName" -Value "1"
        Invoke-ProjectTool -Executable $python -Arguments @(
            "-m",
            "pytest",
            "-m",
            "openai_integration",
            "--basetemp",
            $baseTemp
        )
    }
    finally {
        if ($null -eq $existingFlag) {
            Remove-Item -LiteralPath "Env:$flagName" -ErrorAction SilentlyContinue
        }
        else {
            Set-Item -LiteralPath "Env:$flagName" -Value $existingFlag.Value
        }
    }
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

function Reset-ReferenceAssets {
    if (-not $Force) {
        throw (
            "Reference-asset reset requires -Force. Run: " +
            ".\dev.ps1 reset-reference-assets -Force"
        )
    }

    $python = Resolve-VenvTool -Name "python.exe"
    Invoke-ProjectTool -Executable $python -Arguments @(
        "-m",
        "job_application_copilot.services.reference_asset_reset",
        "--force"
    )
}

function Invoke-Lint {
    $ruff = Resolve-VenvTool -Name "ruff.exe"
    Invoke-ProjectTool -Executable $ruff -Arguments @("check", ".")
    Invoke-ProjectTool -Executable $ruff -Arguments @("format", "--check", ".")
}

function Show-DocumentBRouting {
    $python = Resolve-VenvTool -Name "python.exe"
    $arguments = @("-m", "job_application_copilot.services.document_b_routing_cli")
    if ($DocumentBVersion -gt 0) {
        $arguments += @("--document-b-version", $DocumentBVersion.ToString())
    }
    if (-not [string]::IsNullOrWhiteSpace($Lane)) {
        $arguments += @("--lane", $Lane)
    }
    Invoke-ProjectTool -Executable $python -Arguments $arguments
}

function Invoke-TypeChecks {
    $python = Resolve-VenvTool -Name "python.exe"
    Invoke-ProjectTool -Executable $python -Arguments @("-m", "mypy")
}

function Start-UserInterface {
    $python = Resolve-VenvTool -Name "python.exe"
    $streamlit = Resolve-VenvTool -Name "streamlit.exe"
    $application = Join-Path $script:ProjectRoot "src\job_application_copilot\ui\app.py"
    $dataDirectory = if ($env:JAC_DATA_DIR) {
        [System.IO.Path]::GetFullPath($env:JAC_DATA_DIR)
    }
    else {
        Join-Path $script:ProjectRoot "data"
    }
    $stopFile = Join-Path $dataDirectory ("worker-stop-" + [Guid]::NewGuid().ToString("N") + ".signal")

    New-Item -ItemType Directory -Path $dataDirectory -Force | Out-Null
    $worker = Start-UiWorker -Python $python -StopFile $stopFile -DataDirectory $dataDirectory
    try {
        Invoke-ProjectTool -Executable $streamlit -Arguments @("run", $application)
    }
    finally {
        if ($null -ne $worker) {
            New-Item -ItemType File -Path $stopFile -Force | Out-Null
            if (-not $worker.WaitForExit(65000)) {
                Write-Warning "The background worker is still finishing its current task."
            }
            elseif (Test-Path -LiteralPath $stopFile -PathType Leaf) {
                Remove-Item -LiteralPath $stopFile -Force
            }
        }
    }
}

function Start-BackgroundWorker {
    $python = Resolve-VenvTool -Name "python.exe"
    Invoke-ProjectTool -Executable $python -Arguments @(
        "-m",
        "job_application_copilot.services.background_worker"
    )
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
    "reset-reference-assets" {
        Reset-ReferenceAssets
    }
    "document-b-routing" {
        Show-DocumentBRouting
    }
    "test" {
        Invoke-Tests
    }
    "coverage" {
        Invoke-Coverage
    }
    "test-openai" {
        Invoke-OpenAIIntegrationTests
    }
    "lint" {
        Invoke-Lint
    }
    "type" {
        Invoke-TypeChecks
    }
    "worker" {
        Start-BackgroundWorker
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
