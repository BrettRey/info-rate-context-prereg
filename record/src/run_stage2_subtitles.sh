#!/usr/bin/env bash
# Run the Stage 2 subtitle fetch for several languages, stopping at a wall-clock deadline.
# Usage: src/run_stage2_subtitles.sh HH:MM LANG [LANG ...]
# At the deadline the current fetch is killed; it resumes from its checkpoint next time.
# Logs: results/stage2/logs/opensubtitles_<LANG>.log (appended).
set -u
cd "$(dirname "$0")/.."
deadline=$(date -j -f "%H:%M" "$1" +%s); shift
[ "$deadline" -le "$(date +%s)" ] && deadline=$((deadline + 86400))   # HH:MM already past: tomorrow
stop=data/interim/stage2_ckpt/STOP
mkdir -p data/interim/stage2_ckpt results/stage2/logs
rm -f "$stop"
( while [ "$(date +%s)" -lt "$deadline" ]; do sleep 20; done
  touch "$stop"; pkill -f "src/stage2_opensubtitles.py" ) &
watcher=$!
for L in "$@"; do
  [ -e "$stop" ] && { echo "deadline reached before $L"; break; }
  .venv/bin/python -I src/stage2_opensubtitles.py "$L" >> "results/stage2/logs/opensubtitles_$L.log" 2>&1
  tail -1 "results/stage2/logs/opensubtitles_$L.log"
done
kill "$watcher" 2>/dev/null
if [ -e "$stop" ]; then echo "stopped at deadline $(date +%H:%M)"; fi
exit 0
