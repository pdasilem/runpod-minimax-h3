import asyncio
import json
import os
import random
import subprocess
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import runpod

from delivery import collect_new_files, collect_outputs, prune_volume_outputs
from graph import build_graph, required_files
from job import SEED_LIMIT, JobError, parse_job

COMFY_DIR = os.environ.get("COMFYUI_DIR", "/workspace/runpod-slim/ComfyUI")
COMFY_URL = "http://127.0.0.1:8188"
WORKFLOW = Path(os.environ.get("WORKFLOWS_DIR", "/opt/workflows")) / "t2va.json"
JOB_TIMEOUT_S = int(os.environ.get("JOB_TIMEOUT_S", "1800"))
VOLUME = Path("/runpod-volume")
MODELS_ON_VOLUME = VOLUME / "models"
COMFY_LOG = Path("/workspace/comfy.log")
BOOT_TIMEOUT_S = 600
BOOT_POLL_S = 2
HISTORY_POLL_S = 3
ERROR_TEXT_MAX = 2000
LOG_LINES_MAX = 40

_BOOT_DONE = threading.Event()
_BOOT_ERROR: list = []


def comfy_http(path: str, payload: dict | None = None, timeout: float = 30) -> bytes:
    url = COMFY_URL + path
    data = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        return urllib.request.urlopen(request, timeout=timeout).read()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")[:ERROR_TEXT_MAX]
        raise RuntimeError(f"ComfyUI {path} answered HTTP {exc.code}: {body}") from exc


def boot_comfy() -> subprocess.Popen:
    command = [
        "python3", "main.py",
        "--listen", "127.0.0.1", "--port", "8188",
        "--disable-auto-launch",
        "--enable-triton-backend",
    ] + os.environ.get("COMFYUI_EXTRA_ARGS", "").split()
    log = open(COMFY_LOG, "ab", buffering=0)
    process = subprocess.Popen(command, cwd=COMFY_DIR, stdout=log, stderr=subprocess.STDOUT)
    deadline = time.time() + BOOT_TIMEOUT_S
    while time.time() < deadline:
        if process.poll() is not None:
            raise RuntimeError("ComfyUI exited during boot")
        try:
            comfy_http("/system_stats", timeout=5)
            return process
        except (OSError, RuntimeError):
            time.sleep(BOOT_POLL_S)
    raise RuntimeError(f"ComfyUI did not become ready in {BOOT_TIMEOUT_S}s")


def boot_in_background() -> None:
    try:
        boot_comfy()
    except Exception as exc:
        _BOOT_ERROR.append(exc)
        print(f"[handler] ComfyUI boot failed: {exc}", flush=True)
    finally:
        _BOOT_DONE.set()


async def ensure_comfy() -> None:
    await asyncio.to_thread(_BOOT_DONE.wait)
    if _BOOT_ERROR:
        raise RuntimeError(f"ComfyUI failed to boot: {_BOOT_ERROR[0]} (see {COMFY_LOG})")


def missing_files(job) -> list:
    return [f"{folder}/{name}" for folder, name in required_files(job) if not (MODELS_ON_VOLUME / folder / name).is_file()]


def interrupt_prompt(prompt_id: str) -> None:
    for path, payload in (("/queue", {"delete": [prompt_id]}), ("/interrupt", {})):
        try:
            comfy_http(path, payload, timeout=5)
        except (OSError, RuntimeError) as exc:
            print(f"[handler] {path} failed during cancel: {exc}", flush=True)


async def queue_and_wait(prompt: dict) -> dict:
    answer = await asyncio.to_thread(comfy_http, "/prompt", {"prompt": prompt, "client_id": uuid.uuid4().hex}, 60)
    prompt_id = json.loads(answer)["prompt_id"]
    deadline = time.time() + JOB_TIMEOUT_S
    try:
        while time.time() < deadline:
            history = json.loads(await asyncio.to_thread(comfy_http, f"/history/{prompt_id}", None, 30))
            entry = history.get(prompt_id)
            status = (entry or {}).get("status", {})
            if status.get("status_str") == "error":
                messages = " | ".join(str(m) for m in status.get("messages", []))
                raise RuntimeError(f"ComfyUI job failed: {messages[:ERROR_TEXT_MAX]}")
            if status.get("completed"):
                return entry
            await asyncio.sleep(HISTORY_POLL_S)
    except asyncio.CancelledError:
        await asyncio.to_thread(interrupt_prompt, prompt_id)
        raise
    raise TimeoutError(f"prompt {prompt_id} exceeded {JOB_TIMEOUT_S}s")


def comfy_log_since(mark: int) -> list:
    if not COMFY_LOG.is_file():
        return []
    with open(COMFY_LOG, "rb") as log:
        log.seek(mark)
        lines = log.read().decode(errors="replace").splitlines()
    keywords = ("warn", "error", "missing", "unexpected", "fail", "traceback")
    return [line for line in lines if any(word in line.lower() for word in keywords)][-LOG_LINES_MAX:]


def health() -> dict:
    return {
        "status": "ok",
        "comfyui": "failed" if _BOOT_ERROR else ("ready" if _BOOT_DONE.is_set() else "booting"),
        "comfyui_error": str(_BOOT_ERROR[0]) if _BOOT_ERROR else None,
        "model_set": os.environ.get("MODEL_SET"),
        "volume_mounted": VOLUME.is_dir(),
    }


async def handler(job: dict) -> dict:
    inputs = job.get("input") or {}
    if isinstance(inputs, dict) and inputs.get("action") == "health":
        return health()
    try:
        parsed = parse_job(inputs, lambda: random.randrange(SEED_LIMIT))
    except JobError as exc:
        return {"error": str(exc)}
    absent = missing_files(parsed)
    if absent:
        return {"error": f"model {parsed.model} is not on the volume, missing: {', '.join(absent)}; set MODEL_SET={parsed.model} and restart the worker"}
    await ensure_comfy()
    prune_volume_outputs(VOLUME)
    prompt = build_graph(json.loads(WORKFLOW.read_text()), parsed)
    print(f"[handler] job {job.get('id')}: model={parsed.model} mode={parsed.mode} seconds={parsed.seconds} seed={parsed.seed} size={parsed.size} sparse={parsed.sparse}", flush=True)
    log_mark = COMFY_LOG.stat().st_size if COMFY_LOG.is_file() else 0
    started = time.time()
    history = await queue_and_wait(prompt)
    elapsed = time.time() - started
    print(f"[handler] comfy execution took {elapsed:.1f}s", flush=True)
    for line in comfy_log_since(log_mark):
        print(f"[comfy] {line}", flush=True)
    outputs = await asyncio.to_thread(collect_outputs, history, job, lambda path: comfy_http(path, timeout=300))
    if not outputs:
        outputs = await asyncio.to_thread(collect_new_files, Path(COMFY_DIR) / "output", started, job)
    return {
        "outputs": outputs,
        "model": parsed.model,
        "mode": parsed.mode,
        "seconds": parsed.seconds,
        "seed": parsed.seed,
        "size": parsed.size,
        "sparse": parsed.sparse,
        "execution_s": round(elapsed, 1),
    }


if __name__ == "__main__":
    threading.Thread(target=boot_in_background, daemon=True).start()
    runpod.serverless.start({"handler": handler})
