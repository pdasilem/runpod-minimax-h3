#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SETTINGS="$ROOT/deploy/runpod.env"
OUT_DIR="$ROOT/out"
REST="https://rest.runpod.io/v1"
JOBS_API="https://api.runpod.ai/v2"
POLL_S=5

usage() {
    echo "usage: tools/bench.sh update <l40s|pro6000>" >&2
    echo "       tools/bench.sh job <prism-fast|prism-standard|comfy-fast|comfy-standard>..." >&2
    exit 2
}

load_settings() {
    if [ -f "$SETTINGS" ]; then
        set -a
        . "$SETTINGS"
        set +a
    fi
    : "${RUNPOD_API_KEY:?set RUNPOD_API_KEY in $SETTINGS}"
    : "${RUNPOD_ENDPOINT_ID:?set RUNPOD_ENDPOINT_ID in $SETTINGS}"
}

call() {
    curl -sS --fail-with-body --retry 5 -H "Authorization: Bearer $RUNPOD_API_KEY" -H "Content-Type: application/json" "$@"
}

update() {
    local gpu="$1"
    local body="$ROOT/deploy/update-$gpu.json"
    [ -f "$body" ] || usage
    call -X POST "$REST/endpoints/$RUNPOD_ENDPOINT_ID/update" -d @"$body" > /dev/null
    call "$REST/endpoints/$RUNPOD_ENDPOINT_ID" \
        | jq '{gpuTypeIds, flashboot, executionTimeoutMs, idleTimeout, workersMin, workersMax, minCudaVersion}'
}

save_video() {
    local status_file="$1" target="$2"
    local url
    url="$(jq -r '.output.outputs[0].url // empty' "$status_file")"
    if [ -n "$url" ]; then
        curl -sS --fail-with-body -o "$target" "$url"
    else
        jq -r '.output.outputs[0].b64' "$status_file" | base64 -d > "$target"
    fi
}

report() {
    local name="$1" status_file="$2" target="$3"
    jq -r --arg name "$name" --arg file "$target" '
        "\($name): handler execution_s=\(.output.execution_s)"
        + " runpod executionTime_s=\((.executionTime // 0) / 1000)"
        + " delayTime_s=\((.delayTime // 0) / 1000)"
        + " seed=\(.output.seed) -> \($file)"' "$status_file"
}

run_job() {
    local name="$1"
    local request="$ROOT/jobs/$name.json"
    [ -f "$request" ] || usage
    mkdir -p "$OUT_DIR"
    local stamp status_file job_id state previous="" started
    stamp="$(date +%Y%m%d-%H%M%S)"
    status_file="$OUT_DIR/$name-$stamp.json"
    call -X POST "$JOBS_API/$RUNPOD_ENDPOINT_ID/run" -d @"$request" > "$status_file"
    job_id="$(jq -r '.id // empty' "$status_file")"
    if [ -z "$job_id" ]; then
        echo "$name: the endpoint did not return a job id:" >&2
        cat "$status_file" >&2
        return 1
    fi
    started="$(date +%s)"
    echo "$name: job $job_id"
    while true; do
        call "$JOBS_API/$RUNPOD_ENDPOINT_ID/status/$job_id" > "$status_file"
        state="$(jq -r '.status' "$status_file")"
        if [ "$state" != "$previous" ]; then
            echo "$name: $state after $(( $(date +%s) - started ))s"
            previous="$state"
        fi
        case "$state" in
            COMPLETED) break ;;
            FAILED|CANCELLED|TIMED_OUT)
                jq '{status, error, output}' "$status_file" >&2
                return 1
                ;;
        esac
        sleep "$POLL_S"
    done
    if jq -e '.output.error' "$status_file" > /dev/null; then
        jq -r '"\(.output.error)"' "$status_file" >&2
        return 1
    fi
    local target="$OUT_DIR/$name-$stamp.mp4"
    save_video "$status_file" "$target"
    report "$name" "$status_file" "$target"
}

[ $# -ge 2 ] || usage
load_settings
command="$1"
shift
case "$command" in
    update) update "$1" ;;
    job) for name in "$@"; do run_job "$name"; done ;;
    *) usage ;;
esac
