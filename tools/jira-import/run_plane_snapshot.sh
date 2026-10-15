#!/usr/bin/env bash
# Phase 0b runner: copy plane_snapshot_server.py to the host, run it read-only
# inside the api container, and bring the snapshot back to .state/.
#
#   ./run_plane_snapshot.sh            # LOKKO in workspace lokko
#   PROJECT=TEST ./run_plane_snapshot.sh
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
KEY="${SSH_KEY:-$HOME/.ssh/am-us-west-2.pem}"
HOST="${SSH_HOST:-ec2-user@ec2-54-149-251-138.us-west-2.compute.amazonaws.com}"
CONTAINER="${API_CONTAINER:-plane-app-api-1}"
PROJECT="${PROJECT:-LOKKO}"
WORKSPACE="${WORKSPACE:-lokko}"
REMOTE_DIR="jira-sync"
OUT="/tmp/plane_snapshot_${PROJECT}.json.gz"
SSH=(ssh -o ConnectTimeout=15 -o BatchMode=yes -i "$KEY" "$HOST")

mkdir -p "$HERE/.state"
"${SSH[@]}" "mkdir -p ~/$REMOTE_DIR"
scp -q -o BatchMode=yes -i "$KEY" "$HERE/plane_snapshot_server.py" "$HOST:$REMOTE_DIR/"
"${SSH[@]}" "docker exec -i -e SNAP_PROJECT=$PROJECT -e SNAP_WORKSPACE=$WORKSPACE $CONTAINER \
    python manage.py shell < ~/$REMOTE_DIR/plane_snapshot_server.py \
  && docker cp $CONTAINER:$OUT ~/$REMOTE_DIR/ && docker exec $CONTAINER rm -f $OUT"
scp -q -o BatchMode=yes -i "$KEY" "$HOST:$REMOTE_DIR/$(basename "$OUT")" "$HERE/.state/"
echo "saved $HERE/.state/$(basename "$OUT")"
