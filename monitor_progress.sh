#!/bin/bash
# Progress monitor - no flicker version
PROJECT_ID=${1:-proj_7233fe2f}
API_URL="http://localhost:8000/projects/$PROJECT_ID"

trap 'echo ""; exit 0' INT TERM

echo "=== Pipeline Monitor: $PROJECT_ID ==="
echo "Press Ctrl+C to exit"
echo ""

while true; do
    DATA=$(curl -s "$API_URL" 2>/dev/null)

    if [ -z "$DATA" ]; then
        echo -e "\r\033[KCannot connect to API...   "
        sleep 2
        continue
    fi

    read TOTAL VISION NARRATION TTS PLANNING EXPORTS <<< $(echo "$DATA" | python -c "
import sys,json
d=json.load(sys.stdin)
segs = d.get('segments',[])
total = len(segs)
vision = sum(1 for s in segs if s.get('vision',{}).get('status')=='ok')
narr = sum(1 for s in segs if s.get('narration',{}).get('selected_text'))
tts = sum(1 for s in segs if s.get('tts',{}).get('status')=='ok')
planning = d.get('planning',{}).get('narration_global',{}).get('status','pending')
exports = 'READY' if d.get('exports',{}).get('artifacts') else 'pending'
print(total, vision, narr, tts, planning, exports)
" 2>/dev/null)

    TOTAL=${TOTAL:-25}
    VISION=${VISION:-0}
    NARRATION=${NARRATION:-0}
    TTS=${TTS:-0}
    OVERALL=$(( (VISION + NARRATION + TTS) * 100 / (TOTAL * 3) ))

    # Print status - \033[K clears to end of line, \r goes to start
    echo -ne "\r\033[KPlanning:   $PLANNING                              \n"
    echo -ne "\r\033[KVision:     $VISION/$TOTAL  ($((VISION*100/TOTAL))%)              \n"
    echo -ne "\r\033[KNarration:  $NARRATION/$TOTAL  ($((NARRATION*100/TOTAL))%)              \n"
    echo -ne "\r\033[KTTS:        $TTS/$TOTAL  ($((TTS*100/TOTAL))%)              \n"
    echo -ne "\r\033[KOverall:    ${OVERALL}%  |  Exports: $EXPORTS        \n"
    echo -ne "\r\033[K----------------------------------------\n"
    # Move cursor up 5 lines for next update
    echo -ne "\033[5A"

    if [ "$VISION" -eq "$TOTAL" ] && [ "$NARRATION" -eq "$TOTAL" ] && [ "$TTS" -eq "$TOTAL" ] && [ "$EXPORTS" = "READY" ]; then
        echo -ne "\033[5B"  # Move back down
        echo ""
        echo "✅ COMPLETE!"
        echo "$DATA" | python -c "import sys,json; e=json.load(sys.stdin).get('exports',{}).get('artifacts',{}); [print(f'  {k}: {v}') for k,v in e.items()]"
        break
    fi

    sleep 2
done
