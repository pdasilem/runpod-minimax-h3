FROM huchukato/comfyui-base:cu130@sha256:89a47a4a46c0e79ff8d2cdd762ebfc56924e98cd03a1802e2cfeb567b28857c9 AS base

RUN cd /usr/local/lib/python3.12/dist-packages \
    && rm -rf tensorrt tensorrt_bindings tensorrt_libs \
        tensorrt_cu13-10.15.1.29.dist-info tensorrt_cu13_bindings-10.15.1.29.dist-info tensorrt_cu13_libs-10.15.1.29.dist-info \
        llama_cpp llama_cpp_python-0.4.3+cu130.dist-info \
    && rm -rf /opt/comfyui-baked/custom_nodes/ComfyUI-Manager

FROM scratch
COPY --from=base / /

ENV PATH=/usr/local/cuda/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    LD_LIBRARY_PATH=/usr/local/cuda/lib64 \
    NVIDIA_REQUIRE_CUDA= \
    NVIDIA_DISABLE_REQUIRE=true \
    NVIDIA_VISIBLE_DEVICES=all \
    NVIDIA_DRIVER_CAPABILITIES=all \
    DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    IMAGEIO_FFMPEG_EXE=/usr/bin/ffmpeg

ENV GIT_TERMINAL_PROMPT=0
RUN git clone --depth 1 --branch main https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite.git \
        /opt/comfyui-baked/custom_nodes/ComfyUI-VideoHelperSuite

RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir -r /opt/comfyui-baked/custom_nodes/ComfyUI-VideoHelperSuite/requirements.txt \
    && pip install --no-cache-dir --no-deps "transformers>=5.2.0" \
    && pip install --no-cache-dir 'runpod>=1.12' google-cloud-storage \
    && pip cache purge

COPY handler.py job.py graph.py delivery.py cloudrun_job.py /opt/serverless/
COPY workflows/t2va.json /opt/workflows/t2va.json

ENV MODELS_DIR=/models \
    COMFYUI_DIR="/workspace/runpod-slim/ComfyUI" \
    WORKFLOWS_DIR="/opt/workflows" \
    JOB_TIMEOUT_S="1800" \
    MODEL_SET="comfy"

RUN mkdir -p "$COMFYUI_DIR" && cp -a /opt/comfyui-baked/. "$COMFYUI_DIR/" \
    && printf 'cloudrun:\n  base_path: /models\n  diffusion_models: diffusion_models\n  loras: loras\n  vae: vae\n  text_encoders: text_encoders\n' \
        > "$COMFYUI_DIR/extra_model_paths.yaml"

WORKDIR /opt/serverless
ENTRYPOINT ["python3", "/opt/serverless/cloudrun_job.py"]
