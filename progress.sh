#!/bin/bash
# Progress monitor for voice pipeline
PROJECT="proj_2774b7a9"
WORK_DIR="data/projects/$PROJECT/work"
EXPORT_DIR="data/projects/$PROJECT/exports"

while true; do
    wavs=$(ls $WORK_DIR/*.wav 2>/dev/null | wc -l)
    exports=$(ls $EXPORT_DIR/*.mp4 2>/dev/null | wc -l)

    # Progress bar
    filled=$((wavs * 20 / 25))
    empty=$((20 - filled))
    bar=$(printf '#%.0s' $(seq 1 $filled))$(printf '.%.0s' $(seq 1 $empty))

    printf "\r[$bar] $wavs/25"

    if [ "$exports" -gt 0 ]; then
        printf "\n\nDone! Output:\n"
        ls -lh $EXPORT_DIR/
        break
    fi

    sleep 10
done
