import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "populate-volume.sh"

FAKE_WGET = """#!/bin/bash
out=""
url=""
while [ $# -gt 0 ]; do
    case "$1" in
        -O) out="$2"; shift 2;;
        -*) shift;;
        *) url="$1"; shift;;
    esac
done
printf '%s' "$url" > "$out"
"""

MANIFEST = "\n".join([
    "# header",
    "common\ttext_encoders\tencoder.safetensors\thttps://example.test/encoder",
    "common\tvae\tvideo_vae.safetensors\thttps://example.test/video_vae",
    "prism\tdiffusion_models\tprism.safetensors\thttps://example.test/prism",
    "comfy\tdiffusion_models\tbase.safetensors\thttps://example.test/base",
    "comfy\tloras\tturbo.safetensors\thttps://example.test/turbo",
    "",
])


@pytest.fixture
def volume(tmp_path: Path) -> Path:
    root = tmp_path / "volume"
    root.mkdir()
    return root


def run(tmp_path: Path, volume: Path, *args: str) -> subprocess.CompletedProcess:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    wget = bin_dir / "wget"
    wget.write_text(FAKE_WGET)
    wget.chmod(0o755)
    manifest = tmp_path / "manifest.txt"
    manifest.write_text(MANIFEST)
    env = {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "VOL_ROOT": str(volume),
        "MANIFEST": str(manifest),
    }
    return subprocess.run(["bash", str(SCRIPT), *args], env=env, capture_output=True, text=True)


def files_on(volume: Path) -> set:
    models = volume / "models"
    return {str(p.relative_to(models)) for p in models.rglob("*") if p.is_file()}


def test_prism_downloads_the_common_files_and_prism(tmp_path, volume):
    result = run(tmp_path, volume, "prism")

    assert result.returncode == 0, result.stderr
    assert files_on(volume) == {
        "text_encoders/encoder.safetensors",
        "vae/video_vae.safetensors",
        "diffusion_models/prism.safetensors",
    }


def test_comfy_downloads_the_common_files_the_base_model_and_its_lora(tmp_path, volume):
    result = run(tmp_path, volume, "comfy")

    assert result.returncode == 0, result.stderr
    assert files_on(volume) == {
        "text_encoders/encoder.safetensors",
        "vae/video_vae.safetensors",
        "diffusion_models/base.safetensors",
        "loras/turbo.safetensors",
    }


def test_switching_to_comfy_removes_prism_and_keeps_the_common_files(tmp_path, volume):
    run(tmp_path, volume, "prism")
    encoder = volume / "models" / "text_encoders" / "encoder.safetensors"
    encoder.write_text("kept")

    result = run(tmp_path, volume, "comfy")

    assert result.returncode == 0, result.stderr
    assert "diffusion_models/prism.safetensors" not in files_on(volume)
    assert encoder.read_text() == "kept"


def test_switching_back_to_prism_removes_the_base_model_and_its_lora(tmp_path, volume):
    run(tmp_path, volume, "comfy")

    result = run(tmp_path, volume, "prism")

    assert result.returncode == 0, result.stderr
    assert files_on(volume) == {
        "text_encoders/encoder.safetensors",
        "vae/video_vae.safetensors",
        "diffusion_models/prism.safetensors",
    }


@pytest.mark.parametrize("args", [(), ("eros",), ("common",)])
def test_refuses_a_missing_or_unknown_set(tmp_path, volume, args):
    result = run(tmp_path, volume, *args)

    assert result.returncode != 0
    assert not (volume / "models").exists()
