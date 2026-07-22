[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$emDash = [char]0x2014

$scriptPath = Join-Path $PSScriptRoot "import-backlog.ps1"
$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("job-copilot-import-test-" + [guid]::NewGuid())
New-Item -ItemType Directory -Path $tempRoot | Out-Null

try {
    $validCsv = Join-Path $tempRoot "valid.csv"
    @'
Order,Milestone,Ticket ID,Title,Objective,In Scope,Out of Scope,Dependencies,Priority,Size,Status,Owner,Started,Completed,Acceptance Criteria,Expected Tests,Manual Verification,Notes
1,M1 Foundation,T1.1,First ticket,Create a thing.,One; Two,None,None,P0,S,TODO,,,,It works; Errors are clear.,Unit tests.,Run it.,A note
2,M1 Foundation,T1.1A,Completed ticket,Create another thing.,One,None,T1.1,P1,XS,DONE,,,,It works.,Unit tests.,Run it.,
'@ | Set-Content -LiteralPath $validCsv -Encoding UTF8

    $result = @(& $scriptPath -CsvPath $validCsv -DryRun)
    if ($LASTEXITCODE -ne 0) { throw "Dry run returned exit code $LASTEXITCODE." }
    if ($result.Count -ne 2) { throw "Expected one ticket line and one summary line; got $($result.Count)." }
    if ($result[0] -notmatch "T1\.1 $emDash First ticket") { throw "Dry run did not produce the expected title." }
    if ($result[-1] -notmatch '1 issue\(s\) planned') { throw "DONE tickets should be excluded by default." }

    $allResult = @(& $scriptPath -CsvPath $validCsv -DryRun -IncludeCompleted)
    if ($allResult[-1] -notmatch '2 issue\(s\) planned') { throw "IncludeCompleted did not include DONE tickets." }

    $suffixResult = @(& $scriptPath -CsvPath $validCsv -DryRun -IncludeCompleted -TicketId T1.1A)
    if ($suffixResult[0] -notmatch 'T1\.1A') { throw "A suffixed TicketId was not selected." }

    $filteredResult = @(& $scriptPath -CsvPath $validCsv -DryRun -TicketId T1.1)
    if ($filteredResult[-1] -notmatch '1 issue\(s\) planned') { throw "TicketId did not select one ticket." }

    $missingTicketRejected = $false
    try {
        & $scriptPath -CsvPath $validCsv -DryRun -TicketId T9.9 | Out-Null
    }
    catch {
        $missingTicketRejected = $_.Exception.Message -match "Ticket ID not found"
    }
    if (-not $missingTicketRejected) { throw "An unknown TicketId was not rejected." }

    $duplicateCsv = Join-Path $tempRoot "duplicate.csv"
    (Get-Content -LiteralPath $validCsv -Encoding UTF8) +
        '3,M1 Foundation,T1.1,Duplicate,Duplicate.,One,None,None,P0,S,TODO,,,,Works.,Tests.,Run.,' |
        Set-Content -LiteralPath $duplicateCsv -Encoding UTF8

    $duplicateRejected = $false
    try {
        & $scriptPath -CsvPath $duplicateCsv -DryRun | Out-Null
    }
    catch {
        $duplicateRejected = $_.Exception.Message -match "duplicate Ticket IDs"
    }
    if (-not $duplicateRejected) { throw "Duplicate ticket IDs were not rejected." }

    $missingColumnCsv = Join-Path $tempRoot "missing-column.csv"
    @'
Order,Milestone,Ticket ID,Title
1,M1 Foundation,T1.1,Incomplete schema
'@ | Set-Content -LiteralPath $missingColumnCsv -Encoding UTF8

    $missingColumnRejected = $false
    try {
        & $scriptPath -CsvPath $missingColumnCsv -DryRun | Out-Null
    }
    catch {
        $missingColumnRejected = $_.Exception.Message -match "missing required columns"
    }
    if (-not $missingColumnRejected) { throw "A CSV with missing columns was not rejected." }

    Write-Output "All import-backlog tests passed."
}
finally {
    Remove-Item -LiteralPath $tempRoot -Recurse -Force
}
