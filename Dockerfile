FROM huchukato/comfyui-base:cu130@sha256:89a47a4a46c0e79ff8d2cdd762ebfc56924e98cd03a1802e2cfeb567b28857c9

ENV MODELS_DIR=/models
COPY models-manifest.txt fetch-model.sh /opt/cloudrun/
RUN bash /opt/cloudrun/fetch-model.sh /opt/cloudrun/models-manifest.txt text_encoders qwen3vl_32b_heretic_minimax_h3_nvfp4.safetensors
RUN bash /opt/cloudrun/fetch-model.sh /opt/cloudrun/models-manifest.txt vae minimax_h3_video_vae_fp16.safetensors
RUN bash /opt/cloudrun/fetch-model.sh /opt/cloudrun/models-manifest.txt vae minimax_h3_audio_vae_fp32.safetensors
RUN bash /opt/cloudrun/fetch-model.sh /opt/cloudrun/models-manifest.txt diffusion_models minimax_h3_fl2va_pruned_int8_convrot.safetensors
RUN bash /opt/cloudrun/fetch-model.sh /opt/cloudrun/models-manifest.txt loras minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors

# ──────────────────────────────────────────────────────────────────────────────
# Custom nodes — same stack as the pod image
# ──────────────────────────────────────────────────────────────────────────────
ENV GIT_TERMINAL_PROMPT=0
RUN dl() { \
    local user="$1" repo="$2" branch="${3:-main}" dir="$4"; \
    echo "Cloning $user/$repo ($branch) -> $dir"; \
    git clone --depth 1 --branch "$branch" "https://github.com/$user/$repo.git" "/opt/comfyui-baked/custom_nodes/$dir"; \
  } && \
    cd /opt/comfyui-baked/custom_nodes && \
    dl Kosinkadink ComfyUI-VideoHelperSuite main ComfyUI-VideoHelperSuite


# ──────────────────────────────────────────────────────────────────────────────
# Requirements + runpod serverless SDK
# ──────────────────────────────────────────────────────────────────────────────
# libgl1/libglib2.0-0: opencv-python (VideoHelperSuite) fails to import without
# them → the whole pack never registers → missing_node_type on VHS_* nodes.
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

RUN bash -c 'cd /opt/comfyui-baked/custom_nodes && for node_dir in */; do \
        if [ -f "$node_dir/requirements.txt" ]; then \
            echo "Installing requirements for $node_dir..." && \
            pip install --no-cache-dir -r "$node_dir/requirements.txt" || echo "Failed to install requirements for $node_dir"; \
        fi; \
    done' && \
    pip install --no-cache-dir --no-deps "transformers>=5.2.0" && \
    pip install --no-cache-dir 'runpod>=1.12' requests boto3 "huggingface_hub[cli]" hf_transfer && \
    pip cache purge

ENV HF_TOKEN=""

COPY handler.py job.py graph.py delivery.py cloudrun_job.py /opt/serverless/
COPY workflows/t2va.json /opt/workflows/t2va.json

ENV COMFYUI_DIR="/workspace/runpod-slim/ComfyUI" \
    WORKFLOWS_DIR="/opt/workflows" \
    JOB_TIMEOUT_S="1800" \
    MODEL_SET="comfy" \
    VENV_SUFFIX="cu130"

RUN mkdir -p "$COMFYUI_DIR" && cp -a /opt/comfyui-baked/. "$COMFYUI_DIR/" \
    && printf 'cloudrun:\n  base_path: /models\n  diffusion_models: diffusion_models\n  loras: loras\n  vae: vae\n  text_encoders: text_encoders\n' \
        > "$COMFYUI_DIR/extra_model_paths.yaml"

ENV PATH="/workspace/runpod-slim/ComfyUI/.venv-cu130/bin:${PATH}"
WORKDIR /opt/serverless
ENTRYPOINT ["python3", "/opt/serverless/cloudrun_job.py"]
