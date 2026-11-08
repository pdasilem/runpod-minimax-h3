import copy
from dataclasses import dataclass

from job import Job

FRAME_WIDTH = 1024
FRAME_HEIGHT = 576

PRISM_UNET = "PRISM_DMAD_PDMD_int8.safetensors"
COMFY_UNET = "minimax_h3_fl2va_pruned_int8_convrot.safetensors"
COMFY_TURBO_LORA = "minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors"
TEXT_ENCODER = "qwen3vl_32b_heretic_minimax_h3_nvfp4.safetensors"
VIDEO_VAE = "minimax_h3_video_vae_fp16.safetensors"
AUDIO_VAE = "minimax_h3_audio_vae_fp32.safetensors"

FAST_STEPS = 8
STANDARD_STEPS = 20


@dataclass(frozen=True)
class Preset:
    unet: str
    lora: str | None
    steps: int
    sampler: str
    scheduler: str


PRESETS = {
    ("prism", "fast"): Preset(PRISM_UNET, None, FAST_STEPS, "euler", "beta"),
    ("prism", "standard"): Preset(PRISM_UNET, None, STANDARD_STEPS, "euler", "beta"),
    ("comfy", "fast"): Preset(COMFY_UNET, COMFY_TURBO_LORA, FAST_STEPS, "res_multistep", "simple"),
    ("comfy", "standard"): Preset(COMFY_UNET, None, STANDARD_STEPS, "res_multistep", "simple"),
}

COMMON_FILES = (
    ("text_encoders", TEXT_ENCODER),
    ("vae", VIDEO_VAE),
    ("vae", AUDIO_VAE),
)

MODEL_FILES = {
    "prism": (("diffusion_models", PRISM_UNET),),
    "comfy": (("diffusion_models", COMFY_UNET), ("loras", COMFY_TURBO_LORA)),
}


def required_files(job: Job) -> list:
    return [*COMMON_FILES, *MODEL_FILES[job.model]]


def without_lora(graph: dict) -> dict:
    source = graph["lora"]["inputs"]["model"]
    rest = {key: node for key, node in graph.items() if key != "lora"}
    rest["attention"]["inputs"]["model"] = source
    return rest


def build_graph(template: dict, job: Job) -> dict:
    preset = PRESETS[(job.model, job.mode)]
    graph = copy.deepcopy(template)
    graph["unet"]["inputs"]["unet_name"] = preset.unet
    graph["scheduler"]["inputs"]["steps"] = preset.steps
    graph["scheduler"]["inputs"]["scheduler"] = preset.scheduler
    graph["sampler"]["inputs"]["sampler_name"] = preset.sampler
    graph["latent"]["inputs"]["prompt"] = job.prompt
    graph["latent"]["inputs"]["width"] = FRAME_WIDTH
    graph["latent"]["inputs"]["height"] = FRAME_HEIGHT
    graph["seconds"]["inputs"]["value"] = job.seconds
    graph["noise"]["inputs"]["noise_seed"] = job.seed
    if preset.lora is None:
        return without_lora(graph)
    graph["lora"]["inputs"]["lora_name"] = preset.lora
    return graph
