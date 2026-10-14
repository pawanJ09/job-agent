#!/usr/bin/env bash
# Shows how long the job-agent container has been running by the wall clock,
# versus how long it has actually been running. The difference is time the
# Docker Desktop VM was paused, for example while the Mac was asleep.
#
# Usage:
#   scripts/active_time.sh [container-name]     (default: job-agent-app)
#
# Works from any folder. Needs the container to be running, since the "actually
# running" figure is read from inside it. Times are in UTC.

set -euo pipefail

CONTAINER="${1:-job-agent-app}"

if ! STARTED=$(docker inspect -f '{{.State.StartedAt}}' "$CONTAINER" 2>/dev/null); then
  echo "Container '$CONTAINER' not found. Run 'docker ps' to see the name." >&2
  exit 1
fi

if [ "$(docker inspect -f '{{.State.Running}}' "$CONTAINER")" != "true" ]; then
  echo "Container '$CONTAINER' exists but is not running." >&2
  exit 1
fi

read -r -d '' PY <<'PYEOF' || true
import os, sys
from datetime import datetime, timezone

# Process runtime according to the VM's own clock, which stops while the VM is paused.
uptime = float(open('/proc/uptime').read().split()[0])
start_ticks = int(open('/proc/1/stat').read().rsplit(')', 1)[1].split()[19])
active = (uptime - start_ticks / os.sysconf('SC_CLK_TCK')) / 3600

# Wall-clock time since Docker says the container started.
started = datetime.fromisoformat(sys.argv[1])
wall = (datetime.now(timezone.utc) - started).total_seconds() / 3600

print(f'started (UTC):       {started:%Y-%m-%d %H:%M:%S}')
print(f'wall clock elapsed:  {wall:.1f} h')
print(f'actually running:    {active:.1f} h')
print(f'paused (Mac asleep): {max(wall - active, 0):.1f} h')
PYEOF

docker exec "$CONTAINER" python -c "$PY" "$STARTED"
