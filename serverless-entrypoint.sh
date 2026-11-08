#!/bin/bash
# Serverless worker entrypoint: materialize baked ComfyUI, point it at the
# network volume for models, then hand off to the runpod handler.
set -e

COMFYUI_DIR="/workspace/runpod-slim/ComfyUI"
BAKED="/opt/comfyui-baked"
VENV_DIR="$COMFYUI_DIR/.venv-${VENV_SUFFIX:-cu130}"

if [ ! -f "$COMFYUI_DIR/main.py" ]; then
    echo "Materializing baked ComfyUI into workspace..."
    mkdir -p "$COMFYUI_DIR"
    cp -a "$BAKED/." "$COMFYUI_DIR/"
fi

# Models live on the RunPod network volume — populated once by
# populate-gguf-volume.sh, shared across every serverless worker.
cat > "$COMFYUI_DIR/extra_model_paths.yaml" << 'YAML'
runpod_volume:
  base_path: /runpod-volume/models
  checkpoints: checkpoints
  diffusion_models: diffusion_models
  unet: unet
  loras: loras
  vae: vae
  text_encoders: text_encoders
  clip_projections: clip_projections
  LLM: LLM
  clip: clip
  clip_vision: clip_vision
  vae_approx: vae_approx
  ultralytics_bbox: ultralytics/bbox
  ultralytics_segm: ultralytics/segm
  sams: sams
  upscale_models: upscale_models
YAML

# Auto-populate the network volume on first boot (models-manifest.txt).
# Concurrent cold workers serialize on a flock inside populate-volume.sh;
# disable with VOLUME_AUTOPOPULATE=false.
if [ "${VOLUME_AUTOPOPULATE:-true}" = "true" ]; then
    /opt/serverless/populate-volume.sh "${MODEL_SET:-}" || echo "entrypoint: volume populate failed for MODEL_SET=${MODEL_SET:-unset}; jobs report the missing models" >&2
fi

export PATH="$VENV_DIR/bin:$PATH"
exec python3 /opt/serverless/handler.py
