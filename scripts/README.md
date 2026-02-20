# Pipeline Scripts

Scripts for running and monitoring the vo-demo-generator pipeline.

## Quick Start

```powershell
# Run pipeline with automatic monitoring
.\run-pipeline.ps1 -ProjectId "proj_7233fe2f"

# Or use the batch wrapper
.\pipeline.cmd proj_7233fe2f
```

## Scripts

### `run-pipeline.ps1`
Starts the pipeline and automatically begins monitoring.

```powershell
.\run-pipeline.ps1 -ProjectId "proj_7233fe2f"
```

### `monitor-pipeline.ps1`
Monitors an already-running pipeline job.

```powershell
.\monitor-pipeline.ps1 -JobId "abc123-456-def" -ProjectId "proj_7233fe2f"
```

Options:
- `-JobId` (required) - The job ID to monitor
- `-ProjectId` (optional) - Shows detailed segment progress
- `-IntervalSeconds` (default: 5) - Polling interval

### `check-status.ps1`
Quick one-time status check.

```powershell
.\check-status.ps1 -JobId "abc123-456-def"
```

### `pipeline.cmd`
Batch wrapper for easy command-line usage.

```cmd
.\pipeline.cmd proj_7233fe2f
```

## Progress Display

The monitor shows:
```
[02:34] [##########----------] 50% | Stage: Rewrite | V:25 R:12 T:0/25
```

- `[02:34]` - Elapsed time
- `[###---]` - Visual progress bar
- `50%` - Overall completion percentage
- `Stage` - Current processing stage (Vision/Rewrite/TTS)
- `V:25 R:12 T:0` - Segments completed per stage
