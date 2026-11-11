import asyncio
import base64
import json
import multiprocessing
import os
import site
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from graph import required_files
from job import JobError, parse_job

MODELS_PREFIX = "minimax-h3"
DOWNLOAD_CHUNK = 64 * 1024 * 1024
DOWNLOAD_WORKERS = 16
METADATA_TOKEN = "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token"
OBJECT = "https://storage.googleapis.com/storage/v1/b/{bucket}/o/{name}"
UPLOAD = "https://storage.googleapis.com/upload/storage/v1/b/{bucket}/o?uploadType=media&name={name}"
RENDER_PREFIX = "renders/"
UPLOAD_TIMEOUT_S = 300
DOWNLOAD_TIMEOUT_S = 300
TOKEN_TIMEOUT_S = 10
RUNTIME_DIR = Path("/runtime")
RUNTIME_ARCHIVE = RUNTIME_DIR / "runtime.tar"
SITE_PACKAGES = "/usr/local/lib/python3.12/dist-packages"


def access_token() -> str:
    request = urllib.request.Request(METADATA_TOKEN, headers={"Metadata-Flavor": "Google"})
    with urllib.request.urlopen(request, timeout=TOKEN_TIMEOUT_S) as answer:
        return json.load(answer)["access_token"]


def object_url(bucket: str, name: str) -> str:
    return OBJECT.format(bucket=bucket, name=urllib.parse.quote(name, safe=""))


def object_size(url: str, token: str) -> int:
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(request, timeout=TOKEN_TIMEOUT_S) as answer:
        return int(json.load(answer)["size"])


def fetch_range(url: str, token: str, descriptor: int, start: int, end: int) -> None:
    request = urllib.request.Request(
        f"{url}?alt=media",
        headers={"Authorization": f"Bearer {token}", "Range": f"bytes={start}-{end}"},
    )
    with urllib.request.urlopen(request, timeout=DOWNLOAD_TIMEOUT_S) as answer:
        data = answer.read()
    if len(data) != end - start + 1:
        raise OSError(f"bytes {start}-{end} came back as {len(data)} bytes")
    os.pwrite(descriptor, data, start)


def fetch_runtime(bucket: str, name: str) -> None:
    started = time.time()
    token = access_token()
    url = object_url(bucket, name)
    size = object_size(url, token)
    starts = range(0, size, DOWNLOAD_CHUNK)
    descriptor = os.open(RUNTIME_ARCHIVE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC)
    try:
        with ThreadPoolExecutor(DOWNLOAD_WORKERS) as pool:
            ranges = [(start, min(start + DOWNLOAD_CHUNK, size) - 1) for start in starts]
            list(pool.map(lambda piece: fetch_range(url, token, descriptor, *piece), ranges))
    finally:
        os.close(descriptor)
    print(f"[cloudrun] gs://{bucket}/{name}: {size} bytes in {time.time() - started:.1f}s", flush=True)
    started = time.time()
    subprocess.run(["tar", "-xf", str(RUNTIME_ARCHIVE), "-C", str(RUNTIME_DIR)], check=True)
    RUNTIME_ARCHIVE.unlink()
    site.addsitedir(SITE_PACKAGES)
    print(f"[cloudrun] runtime unpacked in {time.time() - started:.1f}s", flush=True)


def boot_comfy(started: float) -> None:
    import handler

    handler.boot_in_background()
    print(f"[cloudrun] ComfyUI boot ended in {time.time() - started:.1f}s", flush=True)


def upload(bucket: str, name: str, data: bytes) -> None:
    request = urllib.request.Request(
        UPLOAD.format(bucket=bucket, name=urllib.parse.quote(name, safe="")),
        data=data,
        method="POST",
        headers={"Authorization": f"Bearer {access_token()}", "Content-Type": "video/mp4"},
    )
    with urllib.request.urlopen(request, timeout=UPLOAD_TIMEOUT_S) as answer:
        answer.read()


def job_input() -> dict:
    return {
        "prompt": os.environ["PROMPT"],
        "model": os.environ["MODEL"],
        "mode": os.environ["MODE"],
        "seconds": int(os.environ["CLIP_SECONDS"]),
    }


def fetch_models(bucket_name: str, files: list) -> None:
    from google.cloud import storage
    from google.cloud.storage import transfer_manager

    import handler

    bucket = storage.Client().bucket(bucket_name)
    for folder, name in files:
        target = handler.MODELS_ON_VOLUME / folder / name
        target.parent.mkdir(parents=True, exist_ok=True)
        started = time.time()
        blob = bucket.blob(f"{MODELS_PREFIX}/{folder}/{name}")
        transfer_manager.download_chunks_concurrently(
            blob, str(target), chunk_size=DOWNLOAD_CHUNK, max_workers=DOWNLOAD_WORKERS
        )
        print(f"[cloudrun] {folder}/{name}: {blob.size} bytes in {time.time() - started:.1f}s", flush=True)


def main() -> int:
    execution = os.environ["CLOUD_RUN_EXECUTION"]
    bucket = os.environ["RENDER_BUCKET"]
    inputs = job_input()
    try:
        files = required_files(parse_job(inputs, lambda: 0))
    except JobError as refused:
        print(f"[cloudrun] the render was refused: {refused}", file=sys.stderr, flush=True)
        return 1
    models_bucket = os.environ["MODELS_BUCKET"]
    runtime = os.environ["RUNTIME_ARCHIVE"]
    try:
        fetch_runtime(models_bucket, runtime)
    except (OSError, subprocess.CalledProcessError, KeyError, ValueError) as failed:
        print(f"[cloudrun] gs://{models_bucket}/{runtime} was not fetched: {failed}", file=sys.stderr, flush=True)
        return 1
    import handler

    started = time.time()
    fetcher = multiprocessing.Process(target=fetch_models, args=(models_bucket, files))
    fetcher.start()
    threading.Thread(target=boot_comfy, args=(started,), daemon=True).start()
    fetcher.join()
    if fetcher.exitcode != 0:
        print(f"[cloudrun] the models were not fetched, exit code {fetcher.exitcode}", file=sys.stderr, flush=True)
        return 1
    print(f"[cloudrun] models fetched in {time.time() - started:.1f}s", flush=True)
    result = asyncio.run(handler.handler({"id": execution, "input": inputs}))
    if "error" in result:
        print(f"[cloudrun] the render was refused: {result['error']}", file=sys.stderr, flush=True)
        return 1
    outputs = result.get("outputs") or []
    if not outputs:
        print("[cloudrun] the render produced no clip", file=sys.stderr, flush=True)
        return 1
    name = f"{RENDER_PREFIX}{execution}.mp4"
    upload(bucket, name, base64.b64decode(outputs[0]["b64"]))
    summary = {key: value for key, value in result.items() if key != "outputs"}
    print(f"[cloudrun] gs://{bucket}/{name} {json.dumps(summary)}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
