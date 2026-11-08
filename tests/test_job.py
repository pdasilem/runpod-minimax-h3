import pytest

from job import Job, JobError, parse_job


def fixed_seed() -> int:
    return 42


def test_defaults_seconds_to_twelve_and_draws_a_seed():
    job = parse_job({"prompt": "a cat says hello", "model": "prism", "mode": "fast"}, fixed_seed)

    assert job == Job(prompt="a cat says hello", model="prism", mode="fast", seconds=12, seed=42)


@pytest.mark.parametrize("seconds", [8, 12, 15])
def test_accepts_seconds_from_eight_to_fifteen(seconds):
    job = parse_job({"prompt": "p", "model": "comfy", "mode": "standard", "seconds": seconds}, fixed_seed)

    assert job.seconds == seconds


@pytest.mark.parametrize("seconds", [7, 16, 0, -1, 12.5, "12", True, None])
def test_rejects_seconds_outside_the_range_or_not_an_integer(seconds):
    with pytest.raises(JobError, match="seconds"):
        parse_job({"prompt": "p", "model": "prism", "mode": "fast", "seconds": seconds}, fixed_seed)


@pytest.mark.parametrize("model", ["", "PRISM", "10eros", None, 1])
def test_rejects_an_unknown_model(model):
    with pytest.raises(JobError, match="model"):
        parse_job({"prompt": "p", "model": model, "mode": "fast"}, fixed_seed)


@pytest.mark.parametrize("mode", ["", "turbo", "Fast", None])
def test_rejects_an_unknown_mode(mode):
    with pytest.raises(JobError, match="mode"):
        parse_job({"prompt": "p", "model": "prism", "mode": mode}, fixed_seed)


@pytest.mark.parametrize("prompt", ["", "   ", None, 5])
def test_rejects_an_empty_or_missing_prompt(prompt):
    with pytest.raises(JobError, match="prompt"):
        parse_job({"prompt": prompt, "model": "prism", "mode": "fast"}, fixed_seed)


def test_keeps_a_given_seed():
    job = parse_job({"prompt": "p", "model": "prism", "mode": "fast", "seed": 7}, fixed_seed)

    assert job.seed == 7


@pytest.mark.parametrize("seed", [-1, 2**32, 1.5, "7", True])
def test_rejects_a_seed_outside_thirty_two_bits_or_not_an_integer(seed):
    with pytest.raises(JobError, match="seed"):
        parse_job({"prompt": "p", "model": "prism", "mode": "fast", "seed": seed}, fixed_seed)


def test_rejects_input_that_is_not_an_object():
    with pytest.raises(JobError, match="input"):
        parse_job(["prompt"], fixed_seed)
