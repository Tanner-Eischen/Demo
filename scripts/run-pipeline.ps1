<#
.SYNOPSIS
    Starts the vo-demo-generator pipeline and automatically monitors progress

.DESCRIPTION
    Initiates a pipeline run and immediately starts monitoring progress.
    Combines starting and monitoring into a single command.

.PARAMETER ProjectId
    The project ID to run (required)

.EXAMPLE
    .\run-pipeline.ps1 -ProjectId "proj_7233fe2f"

.EXAMPLE
    .\run-pipeline.ps1 proj_7233fe2f
#>

param(
    [Parameter(Mandatory=$true, Position=0)]
    [string]$ProjectId
)

$ApiBase = "http://localhost:8000"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host ""
Write-Host "Starting pipeline for project: $ProjectId" -ForegroundColor Cyan

try {
    # Start the pipeline
    $response = Invoke-RestMethod -Uri "$ApiBase/projects/$ProjectId/run" -Method POST
    $jobId = $response.job_id

    Write-Host "Pipeline started!" -ForegroundColor Green
    Write-Host "Job ID: $jobId" -ForegroundColor Gray
    Write-Host ""

    # Start monitoring (just needs ProjectId now)
    & "$ScriptDir\monitor-pipeline.ps1" -ProjectId $ProjectId

} catch {
    Write-Host "Failed to start pipeline: $_" -ForegroundColor Red
    exit 1
}
