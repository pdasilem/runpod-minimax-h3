import base64
import os
import shutil
import time
import urllib.parse
from pathlib import Path
from typing import Callable

MEGABYTE = 1024 * 1024
INLINE_MAX = int(os.environ.get("OUTPUT_INLINE_MAX_MB", "10")) * MEGABYTE
INLINE_BUDGET = int(os.environ.get("OUTPUT_INLINE_BUDGET_MB", "15")) * MEGABYTE
S3_PREFIX = os.environ.get("S3_OUTPUT_PREFIX", "outputs")
S3_URL_TTL_S = int(os.environ.get("S3_URL_TTL_S", "3600"))
OUTPUT_KEYS = ("images", "gifs", "videos")
MEDIA_SUFFIXES = (".mp4", ".webm", ".gif", ".wav", ".mp3", ".flac", ".png", ".jpg", ".jpeg", ".webp")
DAY_S = 86400


def s3_config_of(job: dict) -> dict | None:
    config = job.get("s3Config") or (job.get("input") or {}).get("s3Config")
    if isinstance(config, dict) and config.get("endpointUrl") and config.get("accessId"):
        return config
    return None


def s3_client_of(config: dict):
    import boto3
    from botocore.config import Config

    host = urllib.parse.urlparse(config["endpointUrl"]).netloc
    region = config.get("region") or host.split(".", 1)[0].removeprefix("s3api-") or "us-east-1"
    return boto3.client(
        "s3",
        endpoint_url=config["endpointUrl"],
        aws_access_key_id=config["accessId"],
        aws_secret_access_key=config["accessSecret"],
        region_name=region,
        config=Config(s3={"addressing_style": "path"}),
    )


def uploaded(filename: str, data: bytes, job: dict, config: dict) -> dict:
    key = f"{S3_PREFIX}/{job.get('id', 'job')}/{filename}"
    client = s3_client_of(config)
    client.put_object(Bucket=config["bucketName"], Key=key, Body=data)
    url = client.generate_presigned_url(
        "get_object",
        Params={"Bucket": config["bucketName"], "Key": key},
        ExpiresIn=S3_URL_TTL_S,
    )
    print(f"[handler] {filename} -> s3://{config['bucketName']}/{key} ({len(data) / 1e6:.1f}MB)", flush=True)
    return {"filename": filename, "url": url}


def emit_file(filename: str, data: bytes, job: dict, inline_used: list) -> dict:
    oversized = len(data) > INLINE_MAX or inline_used[0] + len(data) > INLINE_BUDGET
    config = s3_config_of(job)
    if oversized and config:
        try:
            return uploaded(filename, data, job, config)
        except Exception as exc:
            print(f"[handler] s3 upload failed for {filename}: {exc}; returning it inline", flush=True)
    elif oversized:
        print(f"[handler] {filename}: {len(data) / 1e6:.1f}MB over the inline limit and no s3Config", flush=True)
    inline_used[0] += len(data)
    return {"filename": filename, "b64": base64.b64encode(data).decode()}


def collect_outputs(history_entry: dict, job: dict, fetch: Callable[[str], bytes]) -> list:
    inline_used = [0]
    outputs = []
    for node_output in (history_entry.get("outputs") or {}).values():
        for key in OUTPUT_KEYS:
            for item in node_output.get(key) or []:
                query = urllib.parse.urlencode({
                    "filename": item["filename"],
                    "subfolder": item.get("subfolder", ""),
                    "type": item.get("type", "output"),
                })
                outputs.append(emit_file(item["filename"], fetch(f"/view?{query}"), job, inline_used))
    return outputs


def collect_new_files(output_dir: Path, since_ts: float, job: dict) -> list:
    inline_used = [0]
    files = sorted(p for p in output_dir.rglob("*") if p.is_file() and p.stat().st_mtime >= since_ts)
    return [
        emit_file(p.name, p.read_bytes(), job, inline_used)
        for p in files
        if p.suffix.lower() in MEDIA_SUFFIXES
    ]


def prune_volume_outputs(volume: Path) -> None:
    root = volume / S3_PREFIX
    if not root.is_dir():
        return
    cutoff = time.time() - DAY_S
    for directory in root.iterdir():
        if directory.is_dir() and directory.stat().st_mtime < cutoff:
            shutil.rmtree(directory)
