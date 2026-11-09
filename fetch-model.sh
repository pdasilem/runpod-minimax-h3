#!/usr/bin/env bash
set -euo pipefail

manifest=$1
folder=$2
name=$3
target_dir=${MODELS_DIR:?MODELS_DIR is not set}/$folder

url=$(awk -F'\t' -v folder="$folder" -v name="$name" '$2 == folder && $3 == name { print $4; exit }' "$manifest")
[ -n "$url" ] || { echo "fetch-model: $folder/$name is not in $manifest" >&2; exit 1; }

mkdir -p "$target_dir"
curl -fL --retry 5 --retry-delay 10 -o "$target_dir/$name" "$url"
