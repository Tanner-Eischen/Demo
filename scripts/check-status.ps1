<#
.SYNOPSIS
    Quick status check for pipeline jobs

.PARAMETER JobId
    The job ID to check
#>

param(
    [Parameter(Mandatory=$true, Position=0)]
    [string]$JobId
)

$ApiBase = "http://localhost:8000"

try {
    $response = Invoke-RestMethod -Uri "$ApiBase/jobs/$JobId"

    Write-Host ""
    Write-Host "Job Status: " -NoNewline

    switch ($response.status) {
        "queued" { Write-Host "Queued" -ForegroundColor Yellow }
        "started" { Write-Host "Running" -ForegroundColor Cyan }
        "finished" { Write-Host "Completed" -ForegroundColor Green }
        "failed" { Write-Host "Failed" -ForegroundColor Red }
        default { Write-Host $response.status }
    }

    if ($response.result) {
        Write-Host "Result: " -NoNewline
        Write-Host ($response.result | ConvertTo-Json -Compress) -ForegroundColor Gray
    }

    if ($response.error) {
        Write-Host "Error: " -NoNewline
        Write-Host $response.error -ForegroundColor Red
    }

} catch {
    Write-Host "Error: $_" -ForegroundColor Red
}
