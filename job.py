from dataclasses import dataclass
from typing import Callable

MODELS = ("prism", "comfy")
MODES = ("fast", "standard")
SECONDS_LEAST = 8
SECONDS_MOST = 15
SECONDS_DEFAULT = 12
SEED_LIMIT = 2**32


class JobError(ValueError):
    pass


@dataclass(frozen=True)
class Job:
    prompt: str
    model: str
    mode: str
    seconds: int
    seed: int


def is_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def prompt_of(inputs: dict) -> str:
    prompt = inputs.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise JobError("prompt must be a non-empty string")
    return prompt.strip()


def choice_of(inputs: dict, key: str, allowed: tuple) -> str:
    value = inputs.get(key)
    if value not in allowed:
        raise JobError(f"{key} must be one of {', '.join(allowed)}")
    return value


def seconds_of(inputs: dict) -> int:
    seconds = inputs.get("seconds", SECONDS_DEFAULT)
    if not is_integer(seconds) or not SECONDS_LEAST <= seconds <= SECONDS_MOST:
        raise JobError(f"seconds must be an integer from {SECONDS_LEAST} to {SECONDS_MOST}")
    return seconds


def seed_of(inputs: dict, draw_seed: Callable[[], int]) -> int:
    if "seed" not in inputs:
        return draw_seed()
    seed = inputs["seed"]
    if not is_integer(seed) or not 0 <= seed < SEED_LIMIT:
        raise JobError(f"seed must be an integer from 0 to {SEED_LIMIT - 1}")
    return seed


def parse_job(inputs: object, draw_seed: Callable[[], int]) -> Job:
    if not isinstance(inputs, dict):
        raise JobError("input must be an object")
    return Job(
        prompt=prompt_of(inputs),
        model=choice_of(inputs, "model", MODELS),
        mode=choice_of(inputs, "mode", MODES),
        seconds=seconds_of(inputs),
        seed=seed_of(inputs, draw_seed),
    )
