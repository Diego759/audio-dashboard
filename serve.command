#!/bin/bash
# macOS: double-click to serve the dashboard locally and open it.
# (First time: right-click -> Open to clear Gatekeeper.)
cd "$(dirname "$0")" || exit 1
PORT=8768
python3 -m http.server "$PORT" >/dev/null 2>&1 &
SRV=$!
trap 'kill $SRV 2>/dev/null' EXIT
sleep 1
open "http://localhost:$PORT/index.html"
echo "Serving Gateway dashboard on http://localhost:$PORT"
echo "Close this window (or press Ctrl+C) to stop."
wait $SRV
