import json
from pathlib import Path

import pytest

from job import parse_job

ROOT = Path(__file__).resolve().parent.parent
JOB_FILES = sorted((ROOT / "jobs").glob("*.json"))
ENDPOINT_FILES = sorted((ROOT / "deploy").glob("endpoint-*.json"))


def no_seed() -> int:
    raise AssertionError("a test job carries its own seed")


def test_there_is_one_job_per_model_and_mode():
    assert [p.stem for p in JOB_FILES] == ["comfy-fast", "comfy-standard", "prism-fast", "prism-standard"]


@pytest.mark.parametrize("path", JOB_FILES, ids=lambda p: p.stem)
def test_each_job_is_valid_and_named_after_its_variant(path):
    job = parse_job(json.loads(path.read_text())["input"], no_seed)

    assert f"{job.model}-{job.mode}" == path.stem


def test_all_jobs_share_the_prompt_the_duration_and_the_seed():
    jobs = [json.loads(p.read_text())["input"] for p in JOB_FILES]

    assert len({(j["prompt"], j["seconds"], j["seed"]) for j in jobs}) == 1


@pytest.mark.parametrize("path", ENDPOINT_FILES, ids=lambda p: p.stem)
def test_each_endpoint_boots_with_flashboot_one_worker_and_the_long_timeout(path):
    body = json.loads(path.read_text())

    assert body["flashboot"] is True
    assert body["executionTimeoutMs"] == 1800000
    assert body["workersMax"] == 1
    assert body["idleTimeout"] == 60


def test_the_l40s_endpoint_cannot_land_on_an_l40():
    body = json.loads((ROOT / "deploy" / "endpoint-l40s.json").read_text())

    assert body["gpuTypeIds"] == ["NVIDIA L40S"]
