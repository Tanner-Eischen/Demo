<#
.SYNOPSIS
    Monitors vo-demo-generator pipeline progress with visual progress bar

.DESCRIPTION
    Polls the project directory and displays real-time progress including:
    - Progress bar with percentage
    - Current stage (vision/rewrite/tts/mixing)
    - Segment completion counts
    - Estimated time remaining

.PARAMETER ProjectId
    The project ID to monitor (required)

.PARAMETER IntervalSeconds
    Polling interval in seconds (default: 2)

.EXAMPLE
    .\monitor-pipeline.ps1 -ProjectId "proj_7233fe2f"

.EXAMPLE
    .\monitor-pipeline.ps1 proj_7233fe2f
#>

param(
    [Parameter(Mandatory=$true, Position=0)]
    [string]$ProjectId,

    [Parameter(Mandatory=$false)]
    [string]$DataDir = "C:\Users\tanne\Gauntlet\voice\data",

    [int]$IntervalSeconds = 2
)

$ProjectDir = Join-Path $DataDir "projects\$ProjectId"
$WorkDir = Join-Path $ProjectDir "work"
$HolisticWorkDir = Join-Path $WorkDir "holistic"
$ExportsDir = Join-Path $ProjectDir "exports"

function Write-ProgressBar {
    param([int]$Percent, [int]$Width = 30)

    $filled = [Math]::Floor($Percent * $Width / 100)
    $empty = $Width - $filled

    $bar = "[" + ("#" * $filled) + ("-" * $empty) + "]"

    # Color based on progress
    if ($Percent -lt 33) {
        Write-Host $bar -ForegroundColor Yellow -NoNewline
    } elseif ($Percent -lt 66) {
        Write-Host $bar -ForegroundColor Cyan -NoNewline
    } else {
        Write-Host $bar -ForegroundColor Green -NoNewline
    }

    Write-Host " $Percent%"
}

function Get-PipelineMode {
    param([string]$ProjDir)

    $projectFile = Join-Path $ProjDir "project.json"
    if (Test-Path $projectFile) {
        $proj = Get-Content $projectFile | ConvertFrom-Json
        $mode = $proj.settings.narration_mode
        if ($proj.settings.holistic.enabled) { $mode = "holistic" }
        return $mode
    }
    return "segment"
}

function Get-SegmentProgress {
    param([string]$ProjDir)

    $workDir = Join-Path $ProjDir "work"
    $holisticWorkDir = Join-Path $workDir "holistic"
    $ttsOnlyWorkDir = Join-Path $workDir "tts_only"

    # Check for segment mode files
    $visionCount = (Get-ChildItem -Path $workDir -Filter "*_vision_raw.txt" -ErrorAction SilentlyContinue).Count
    $rewriteCount = (Get-ChildItem -Path $workDir -Filter "*_rewrite_raw.txt" -ErrorAction SilentlyContinue).Count
    $ttsCount = (Get-ChildItem -Path $workDir -Filter "seg*.wav" -ErrorAction SilentlyContinue).Count

    # Check for holistic mode files
    $holisticTtsCount = (Get-ChildItem -Path $holisticWorkDir -Filter "section_*.wav" -ErrorAction SilentlyContinue).Count

    # Check for tts_only mode files
    $ttsOnlyCount = (Get-ChildItem -Path $ttsOnlyWorkDir -Filter "seg*.wav" -ErrorAction SilentlyContinue).Count

    return @{
        Vision = $visionCount
        Rewrite = $rewriteCount
        TTS = $ttsCount
        HolisticTTS = $holisticTtsCount
        TTSOnly = $ttsOnlyCount
    }
}

function Get-TimelineNarrationCount {
    param([string]$ProjDir)

    $projectFile = Join-Path $ProjDir "project.json"
    if (-not (Test-Path $projectFile)) { return 0 }

    try {
        $proj = Get-Content $projectFile | ConvertFrom-Json
        if ($proj.timeline -and $proj.timeline.narration_events) {
            return @($proj.timeline.narration_events).Count
        }
    } catch {
        return 0
    }
    return 0
}

function Get-HolisticProgress {
    param([string]$ProjDir)

    $projectFile = Join-Path $ProjDir "project.json"
    if (-not (Test-Path $projectFile)) { return "unknown" }

    $proj = Get-Content $projectFile | ConvertFrom-Json
    return $proj.holistic.status
}

function Get-CurrentStage {
    param($Progress, [string]$Mode, [string]$HolisticStatus)

    if ($Mode -eq "tts_only") {
        if ($Progress.TTSOnly -gt 0) {
            return "TTS"
        }
        return "Starting"
    }

    if ($Mode -eq "holistic") {
        switch ($HolisticStatus) {
            "running" { return "Processing" }
            "completed" { return "Done" }
            "error" { return "Error" }
            default { return "Starting" }
        }
    }

    if ($Progress.TTS -ge $Progress.Vision -and $Progress.TTS -gt 0) {
        return "TTS"
    } elseif ($Progress.Rewrite -ge $Progress.Vision -and $Progress.Rewrite -gt 0) {
        return "Rewrite"
    } elseif ($Progress.Vision -gt 0) {
        return "Vision"
    } else {
        return "Starting"
    }
}

function Get-LogTail {
    param([string]$ProjDir)

    $logFile = Join-Path $ProjDir "logs\job.log"
    if (Test-Path $logFile) {
        $lines = Get-Content $logFile -Tail 1
        return $lines
    }
    return ""
}

function Get-VideoDuration {
    param([string]$ProjDir)

    $projectFile = Join-Path $ProjDir "project.json"
    if (Test-Path $projectFile) {
        $proj = Get-Content $projectFile | ConvertFrom-Json
        return $proj.source.video.duration_ms / 1000
    }
    return 0
}

# Validate project exists
if (-not (Test-Path $ProjectDir)) {
    Write-Host "Error: Project directory not found: $ProjectDir" -ForegroundColor Red
    exit 1
}

$mode = Get-PipelineMode -ProjDir $ProjectDir
$videoDuration = Get-VideoDuration -ProjDir $ProjectDir

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "   Pipeline Progress Monitor" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Project: $ProjectId" -ForegroundColor Gray
Write-Host "Mode: $mode" -ForegroundColor $(if ($mode -eq "holistic") { "Green" } else { "Yellow" })
Write-Host "Duration: $([Math]::Round($videoDuration, 1))s" -ForegroundColor Gray
Write-Host ""

$startTime = Get-Date
$totalSegments = 25  # Default, will update if we detect otherwise
$ttsOnlyTotal = Get-TimelineNarrationCount -ProjDir $ProjectDir

while ($true) {
    $progress = Get-SegmentProgress -ProjDir $ProjectDir
    $holisticStatus = Get-HolisticProgress -ProjDir $ProjectDir
    $stage = Get-CurrentStage -Progress $progress -Mode $mode -HolisticStatus $holisticStatus

    # Calculate overall progress based on mode
    if ($mode -eq "tts_only") {
        if ($ttsOnlyTotal -le 0) {
            $ttsOnlyTotal = 1
        }

        $ttsOnlyPct = ($progress.TTSOnly / $ttsOnlyTotal) * 90
        $overallPct = [Math]::Round([Math]::Min(99, $ttsOnlyPct))

        $visionCount = 0
        $rewriteCount = 0
        $ttsCount = $progress.TTSOnly
        $totalSegments = $ttsOnlyTotal
    }
    elseif ($mode -eq "holistic") {
        # For holistic mode, check holistic progress
        $holisticTts = $progress.HolisticTTS

        # Estimate total sections based on video duration (~2.25 WPS, ~8 words per section)
        $estimatedSections = [Math]::Max(10, [Math]::Round($videoDuration * 2.25 / 8))
        if ($holisticTts -gt $estimatedSections) { $estimatedSections = $holisticTts }

        $ttsPct = if ($estimatedSections -gt 0) { ($holisticTts / $estimatedSections) * 80 } else { 0 }

        if ($holisticStatus -eq "completed") {
            $overallPct = 100
        } elseif ($holisticStatus -eq "error") {
            $overallPct = [Math]::Round($ttsPct)
        } else {
            $overallPct = [Math]::Round($ttsPct)
        }

        $visionCount = 0
        $rewriteCount = 0
        $ttsCount = $holisticTts
        $totalSegments = $estimatedSections
    } else {
        # Segment mode
        if ($progress.Vision -gt $totalSegments) { $totalSegments = $progress.Vision }

        $visionPct = if ($totalSegments -gt 0) { ($progress.Vision / $totalSegments) * 30 } else { 0 }
        $rewritePct = if ($totalSegments -gt 0) { ($progress.Rewrite / $totalSegments) * 30 } else { 0 }
        $ttsPct = if ($totalSegments -gt 0) { ($progress.TTS / $totalSegments) * 30 } else { 0 }

        $overallPct = [Math]::Round($visionPct + $rewritePct + $ttsPct)
        $visionCount = $progress.Vision
        $rewriteCount = $progress.Rewrite
        $ttsCount = $progress.TTS
    }

    # Calculate elapsed time
    $elapsed = (Get-Date) - $startTime
    $elapsedStr = "{0:mm\:ss}" -f $elapsed

    # Clear and write progress
    Write-Host "`r" -NoNewline
    Write-Host "[$elapsedStr] " -ForegroundColor DarkGray -NoNewline

    Write-ProgressBar -Percent $overallPct

    Write-Host " | Stage: " -NoNewline
    switch ($stage) {
        "Vision" { Write-Host $stage -ForegroundColor Magenta -NoNewline }
        "Rewrite" { Write-Host $stage -ForegroundColor Yellow -NoNewline }
        "TTS" { Write-Host $stage -ForegroundColor Cyan -NoNewline }
        "Processing" { Write-Host $stage -ForegroundColor Green -NoNewline }
        "Starting" { Write-Host $stage -ForegroundColor Gray -NoNewline }
        "Done" { Write-Host $stage -ForegroundColor Green -NoNewline }
        "Error" { Write-Host $stage -ForegroundColor Red -NoNewline }
        default { Write-Host $stage -ForegroundColor White -NoNewline }
    }

    if ($mode -eq "tts_only") {
        Write-Host " | T:$ttsCount/$totalSegments" -NoNewline
    }
    elseif ($mode -eq "holistic") {
        Write-Host " | Sections: $ttsCount" -NoNewline
    } else {
        Write-Host " | V:$visionCount R:$rewriteCount T:$ttsCount/$totalSegments" -NoNewline
    }

    # Check for completion
    $isComplete = $false
    $isFailed = $false

    if ($mode -eq "tts_only") {
        $finalMp4 = Join-Path $ExportsDir "final.mp4"
        $finalWithCaps = Join-Path $ExportsDir "final_with_captions.mp4"
        if ((Test-Path $finalMp4) -or (Test-Path $finalWithCaps)) {
            $isComplete = $true
            $overallPct = 100
        }
    }
    elseif ($mode -eq "holistic") {
        if ($holisticStatus -eq "completed") { $isComplete = $true }
        if ($holisticStatus -eq "error") { $isFailed = $true }
    } else {
        # Check for final output file
        $finalMp4 = Join-Path $ExportsDir "final.mp4"
        $finalWithCaps = Join-Path $ExportsDir "final_with_captions.mp4"
        if ((Test-Path $finalMp4) -or (Test-Path $finalWithCaps)) {
            $isComplete = $true
        }
    }

    if ($isComplete) {
        Write-Host ""
        Write-Host ""
        Write-Host "========================================" -ForegroundColor Green
        Write-Host "   PIPELINE COMPLETED SUCCESSFULLY" -ForegroundColor Green
        Write-Host "========================================" -ForegroundColor Green
        Write-Host "Total time: $elapsedStr" -ForegroundColor Gray

        # Find output file
        $outputFile = if ($mode -eq "holistic") {
            Join-Path $ExportsDir "final_holistic_with_captions.mp4"
        } else {
            Join-Path $ExportsDir "final_with_captions.mp4"
        }
        if (-not (Test-Path $outputFile)) {
            $outputFile = if ($mode -eq "holistic") {
                Join-Path $ExportsDir "final_holistic.mp4"
            } else {
                Join-Path $ExportsDir "final.mp4"
            }
        }
        if (Test-Path $outputFile) {
            Write-Host "Output: $outputFile" -ForegroundColor Cyan
        }
        break
    }

    if ($isFailed) {
        Write-Host ""
        Write-Host ""
        Write-Host "========================================" -ForegroundColor Red
        Write-Host "   PIPELINE FAILED" -ForegroundColor Red
        Write-Host "========================================" -ForegroundColor Red

        # Try to get error from project file
        $projectFile = Join-Path $ProjectDir "project.json"
        if (Test-Path $projectFile) {
            $proj = Get-Content $projectFile | ConvertFrom-Json
            if ($proj.holistic.error) {
                Write-Host "Error: $($proj.holistic.error)" -ForegroundColor Red
            }
        }
        break
    }

    Start-Sleep -Seconds $IntervalSeconds
}
