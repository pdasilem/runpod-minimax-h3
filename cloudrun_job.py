import asyncio
import base64
import json
import os
import sys
import threading
import urllib.parse
import urllib.request

import handler

METADATA_TOKEN = "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token"
UPLOAD = "https://storage.googleapis.com/upload/storage/v1/b/{bucket}/o?uploadType=media&name={name}"
RENDER_PREFIX = "renders/"
UPLOAD_TIMEOUT_S = 300
TOKEN_TIMEOUT_S = 10


def access_token() -> str:
    request = urllib.request.Request(METADATA_TOKEN, headers={"Metadata-Flavor": "Google"})
    with urllib.request.urlopen(request, timeout=TOKEN_TIMEOUT_S) as answer:
        return json.load(answer)["access_token"]


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


def main() -> int:
    execution = os.environ["CLOUD_RUN_EXECUTION"]
    bucket = os.environ["RENDER_BUCKET"]
    threading.Thread(target=handler.boot_in_background, daemon=True).start()
    result = asyncio.run(handler.handler({"id": execution, "input": job_input()}))
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
