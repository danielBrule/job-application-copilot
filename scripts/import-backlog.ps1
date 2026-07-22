[CmdletBinding()]
param(
    [Parameter()]
    [string]$CsvPath,

    [Parameter()]
    [string]$Repository,

    [Parameter()]
    [string]$TicketId,

    [Parameter()]
    [switch]$DryRun,

    [Parameter()]
    [switch]$IncludeCompleted
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$emDash = [char]0x2014

if ([string]::IsNullOrWhiteSpace($CsvPath)) {
    $CsvPath = Join-Path $PSScriptRoot "..\implementation-backlog.csv"
}

$requiredColumns = @(
    "Order", "Milestone", "Ticket ID", "Title", "Objective", "In Scope",
    "Out of Scope", "Dependencies", "Priority", "Size", "Status",
    "Acceptance Criteria", "Expected Tests", "Manual Verification", "Notes"
)

function Invoke-GitHubCli {
    param([Parameter(Mandatory)][string[]]$Arguments)

    $output = & gh @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "gh $($Arguments -join ' ') failed:`n$($output -join [Environment]::NewLine)"
    }
    return $output
}

function ConvertTo-Bullets {
    param(
        [AllowEmptyString()][string]$Value,
        [switch]$Checklist
    )

    if ([string]::IsNullOrWhiteSpace($Value)) {
        return "- None"
    }

    $prefix = if ($Checklist) { "- [ ] " } else { "- " }
    return (($Value -split ";" | ForEach-Object {
        $item = $_.Trim()
        if ($item) { "$prefix$item" }
    }) -join "`n")
}

function New-IssueBody {
    param([Parameter(Mandatory)]$Ticket)

    $notes = if ([string]::IsNullOrWhiteSpace($Ticket.Notes)) { "None" } else { $Ticket.Notes.Trim() }
    return @"
## Objective

$($Ticket.Objective.Trim())

## In scope

$(ConvertTo-Bullets -Value $Ticket.'In Scope')

## Out of scope

$(ConvertTo-Bullets -Value $Ticket.'Out of Scope')

## Dependencies

$(ConvertTo-Bullets -Value $Ticket.Dependencies)

## Acceptance criteria

$(ConvertTo-Bullets -Value $Ticket.'Acceptance Criteria' -Checklist)

## Expected tests

$(ConvertTo-Bullets -Value $Ticket.'Expected Tests')

## Manual verification

$(ConvertTo-Bullets -Value $Ticket.'Manual Verification')

## Planning metadata

- Ticket ID: $($Ticket.'Ticket ID')
- Priority: $($Ticket.Priority)
- Size: $($Ticket.Size)
- Initial status: $($Ticket.Status)
- Source order: $($Ticket.Order)

## Notes

$notes
"@
}

function Get-BacklogRows {
    param([Parameter(Mandatory)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "Backlog CSV not found: $Path"
    }

    $rows = @(Get-Content -LiteralPath $Path -Encoding UTF8 | ConvertFrom-Csv)
    if ($rows.Count -eq 0) {
        throw "Backlog CSV contains no tickets: $Path"
    }

    $columns = @($rows[0].PSObject.Properties.Name)
    $missingColumns = @($requiredColumns | Where-Object { $_ -notin $columns })
    if ($missingColumns.Count -gt 0) {
        throw "Backlog CSV is missing required columns: $($missingColumns -join ', ')"
    }

    $blankIds = @($rows | Where-Object { [string]::IsNullOrWhiteSpace($_.'Ticket ID') })
    if ($blankIds.Count -gt 0) {
        throw "Backlog CSV contains $($blankIds.Count) row(s) without a Ticket ID."
    }

    $duplicateIds = @($rows | Group-Object -Property 'Ticket ID' | Where-Object Count -gt 1)
    if ($duplicateIds.Count -gt 0) {
        throw "Backlog CSV contains duplicate Ticket IDs: $($duplicateIds.Name -join ', ')"
    }

    return $rows
}

function Assert-GitHubPrerequisites {
    if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
        throw "GitHub CLI (gh) is not installed. Install it and run 'gh auth login'."
    }
    [void](Invoke-GitHubCli -Arguments @("auth", "status"))
}

function Resolve-Repository {
    param([string]$RequestedRepository)

    if ($RequestedRepository) {
        if ($RequestedRepository -notmatch '^[^/]+/[^/]+$') {
            throw "Repository must use the OWNER/REPO format."
        }
        return $RequestedRepository
    }

    $resolved = (Invoke-GitHubCli -Arguments @(
        "repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner"
    ) | Select-Object -First 1).Trim()
    if (-not $resolved) {
        throw "Unable to resolve the GitHub repository. Pass -Repository OWNER/REPO."
    }
    return $resolved
}

$tickets = @(Get-BacklogRows -Path $CsvPath)
if (-not $IncludeCompleted) {
    $tickets = @($tickets | Where-Object { $_.Status -ne "DONE" })
}
if ($TicketId) {
    $tickets = @($tickets | Where-Object { $_.'Ticket ID' -eq $TicketId })
    if ($tickets.Count -eq 0) {
        throw "Ticket ID not found or excluded by status: $TicketId"
    }
}

if ($DryRun) {
    foreach ($ticket in $tickets) {
        $ticketId = $ticket.PSObject.Properties["Ticket ID"].Value
        $labels = @("priority:$($ticket.Priority)", "size:$($ticket.Size)", "status:$($ticket.Status)")
        Write-Output "[DRY RUN] $ticketId $emDash $($ticket.Title) | milestone=$($ticket.Milestone) | labels=$($labels -join ',')"
    }
    Write-Output "Dry run complete: $($tickets.Count) issue(s) planned; no GitHub changes made."
    exit 0
}

Assert-GitHubPrerequisites
$Repository = Resolve-Repository -RequestedRepository $Repository

$existingIssues = @{}
$issueJson = Invoke-GitHubCli -Arguments @(
    "issue", "list", "--repo", $Repository, "--state", "all", "--limit", "1000", "--json", "title,number"
)
$parsedIssues = ($issueJson -join "`n") | ConvertFrom-Json
@($parsedIssues) | Where-Object { $null -ne $_ } | ForEach-Object {
    if ($_.title -match "^(T\d+\.\d+[A-Z]?)\s+$emDash") {
        $existingIssues[$Matches[1]] = $_.number
    }
}

$existingMilestones = @{}
$milestoneJson = Invoke-GitHubCli -Arguments @(
    "api", "--paginate", "repos/$Repository/milestones?state=all&per_page=100"
)
$parsedMilestones = ($milestoneJson -join "`n") | ConvertFrom-Json
@($parsedMilestones) | Where-Object { $null -ne $_ } | ForEach-Object {
    $existingMilestones[$_.title] = $_.number
}

$existingLabels = @{}
$labelJson = Invoke-GitHubCli -Arguments @(
    "label", "list", "--repo", $Repository, "--limit", "1000", "--json", "name"
)
$parsedLabels = ($labelJson -join "`n") | ConvertFrom-Json
@($parsedLabels) | Where-Object { $null -ne $_ } | ForEach-Object {
    $existingLabels[$_.name] = $true
}

$created = 0
$skipped = 0
foreach ($ticket in $tickets) {
    $ticketId = $ticket.PSObject.Properties["Ticket ID"].Value.Trim()
    if ($existingIssues.ContainsKey($ticketId)) {
        Write-Output "Skipping $ticketId; issue #$($existingIssues[$ticketId]) already exists."
        $skipped++
        continue
    }

    $milestone = $ticket.Milestone.Trim()
    if (-not $existingMilestones.ContainsKey($milestone)) {
        $createdMilestone = Invoke-GitHubCli -Arguments @(
            "api", "--method", "POST", "repos/$Repository/milestones", "-f", "title=$milestone"
        )
        $milestoneData = ($createdMilestone -join "`n") | ConvertFrom-Json
        $existingMilestones[$milestone] = $milestoneData.number
        Write-Output "Created milestone: $milestone"
    }

    $labels = @("priority:$($ticket.Priority)", "size:$($ticket.Size)", "status:$($ticket.Status)")
    foreach ($label in $labels) {
        if (-not $existingLabels.ContainsKey($label)) {
            [void](Invoke-GitHubCli -Arguments @(
                "label", "create", $label, "--repo", $Repository, "--color", "D4C5F9"
            ))
            $existingLabels[$label] = $true
            Write-Output "Created label: $label"
        }
    }

    $title = "$ticketId $emDash $($ticket.Title.Trim())"
    $body = New-IssueBody -Ticket $ticket
    $issueUrl = Invoke-GitHubCli -Arguments @(
        "issue", "create", "--repo", $Repository, "--title", $title,
        "--body", $body, "--milestone", $milestone, "--label", ($labels -join ",")
    )
    Write-Output "Created $ticketId`: $($issueUrl | Select-Object -Last 1)"
    $created++
}

Write-Output "Import complete for $Repository`: created=$created, skipped=$skipped, considered=$($tickets.Count)."
