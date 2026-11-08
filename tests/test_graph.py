import copy
import json
from pathlib import Path

import pytest

from graph import (
    COMFY_TURBO_LORA,
    COMFY_UNET,
    FRAME_HEIGHT,
    FRAME_WIDTH,
    PRISM_UNET,
    build_graph,
)
from job import Job

TEMPLATE = json.loads((Path(__file__).resolve().parent.parent / "workflows" / "t2va.json").read_text())


def job_of(model: str, mode: str, seconds: int = 12) -> Job:
    return Job(prompt="a woman orders coffee", model=model, mode=mode, seconds=seconds, seed=1234)


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


@pytest.mark.parametrize("model, mode", [("prism", "fast"), ("prism", "standard"), ("comfy", "fast"), ("comfy", "standard")])
def test_every_link_points_to_a_node_of_the_graph(model, mode):
    graph = build_graph(TEMPLATE, job_of(model, mode))

    assert all(link[0] in graph for link in links_of(graph))


def test_writes_the_prompt_the_duration_the_seed_and_the_scene_frame():
    graph = build_graph(TEMPLATE, job_of("prism", "fast", seconds=9))

    assert graph["latent"]["inputs"]["prompt"] == "a woman orders coffee"
    assert graph["seconds"]["inputs"]["value"] == 9
    assert graph["noise"]["inputs"]["noise_seed"] == 1234
    assert (graph["latent"]["inputs"]["width"], graph["latent"]["inputs"]["height"]) == (FRAME_WIDTH, FRAME_HEIGHT)


def test_leaves_the_template_untouched():
    before = copy.deepcopy(TEMPLATE)

    build_graph(TEMPLATE, job_of("comfy", "fast"))
    build_graph(TEMPLATE, job_of("prism", "standard"))

    assert TEMPLATE == before
