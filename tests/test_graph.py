import copy
import json
from pathlib import Path

import pytest

from graph import (
    COMFY_TURBO_LORA,
    COMFY_UNET,
    FRAME_SIZES,
    PRISM_UNET,
    build_graph,
)
from job import Job

TEMPLATE = json.loads((Path(__file__).resolve().parent.parent / "workflows" / "t2va.json").read_text())
VARIANTS = [("prism", "fast"), ("prism", "standard"), ("comfy", "fast"), ("comfy", "standard")]


def job_of(model: str, mode: str, seconds: int = 12, size: str = "scene", sparse: bool = True) -> Job:
    return Job(prompt="a woman orders coffee", model=model, mode=mode, seconds=seconds, seed=1234, size=size, sparse=sparse)


def links_of(graph: dict) -> list:
    return [value for node in graph.values() for value in node["inputs"].values() if isinstance(value, list)]


@pytest.mark.parametrize(
    "model, mode, unet, steps, sampler, scheduler",
    [
        ("prism", "fast", PRISM_UNET, 8, "euler", "beta"),
        ("prism", "standard", PRISM_UNET, 20, "euler", "beta"),
        ("comfy", "fast", COMFY_UNET, 8, "res_multistep", "simple"),
        ("comfy", "standard", COMFY_UNET, 20, "res_multistep", "simple"),
    ],
)
def test_sets_the_model_and_sampling_of_each_variant(model, mode, unet, steps, sampler, scheduler):
    graph = build_graph(TEMPLATE, job_of(model, mode))

    assert graph["unet"]["inputs"]["unet_name"] == unet
    assert graph["scheduler"]["inputs"]["steps"] == steps
    assert graph["scheduler"]["inputs"]["scheduler"] == scheduler
    assert graph["sampler"]["inputs"]["sampler_name"] == sampler


def test_comfy_fast_runs_the_turbo_lora_on_the_base_model():
    graph = build_graph(TEMPLATE, job_of("comfy", "fast"))

    assert graph["lora"]["inputs"]["lora_name"] == COMFY_TURBO_LORA
    assert graph["lora"]["inputs"]["model"] == ["unet", 0]
    assert graph["attention"]["inputs"]["model"] == ["lora", 0]


@pytest.mark.parametrize("model, mode", [("prism", "fast"), ("prism", "standard"), ("comfy", "standard")])
def test_other_variants_drop_the_lora_and_feed_the_model_straight_on(model, mode):
    graph = build_graph(TEMPLATE, job_of(model, mode))

    assert "lora" not in graph
    assert graph["attention"]["inputs"]["model"] == ["unet", 0]


@pytest.mark.parametrize("sparse", [True, False])
@pytest.mark.parametrize("model, mode", VARIANTS)
def test_every_link_points_to_a_node_of_the_graph(model, mode, sparse):
    graph = build_graph(TEMPLATE, job_of(model, mode, sparse=sparse))

    assert all(link[0] in graph for link in links_of(graph))


def test_writes_the_prompt_the_duration_and_the_seed():
    graph = build_graph(TEMPLATE, job_of("prism", "fast", seconds=9))

    assert graph["latent"]["inputs"]["prompt"] == "a woman orders coffee"
    assert graph["seconds"]["inputs"]["value"] == 9
    assert graph["noise"]["inputs"]["noise_seed"] == 1234


@pytest.mark.parametrize("size", ["scene", "native"])
def test_draws_the_frame_of_the_asked_size(size):
    graph = build_graph(TEMPLATE, job_of("prism", "fast", size=size))

    assert (graph["latent"]["inputs"]["width"], graph["latent"]["inputs"]["height"]) == FRAME_SIZES[size]


@pytest.mark.parametrize("model, mode", VARIANTS)
def test_dense_attention_drops_the_sparse_node_and_feeds_sampling_from_the_attention_backend(model, mode):
    graph = build_graph(TEMPLATE, job_of(model, mode, sparse=False))

    assert "sparse" not in graph
    assert graph["scheduler"]["inputs"]["model"] == ["attention", 0]
    assert graph["guider"]["inputs"]["model"] == ["attention", 0]


def test_sparse_attention_stays_between_the_backend_and_sampling():
    graph = build_graph(TEMPLATE, job_of("prism", "fast"))

    assert graph["sparse"]["inputs"]["model"] == ["attention", 0]
    assert graph["scheduler"]["inputs"]["model"] == ["sparse", 0]
    assert graph["guider"]["inputs"]["model"] == ["sparse", 0]


def test_leaves_the_template_untouched():
    before = copy.deepcopy(TEMPLATE)

    build_graph(TEMPLATE, job_of("comfy", "fast"))
    build_graph(TEMPLATE, job_of("prism", "standard"))

    assert TEMPLATE == before
