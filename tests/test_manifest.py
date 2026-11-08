from pathlib import Path

from graph import required_files
from job import Job

MANIFEST = Path(__file__).resolve().parent.parent / "models-manifest.txt"
SETS = ("common", "prism", "comfy")


def rows() -> list:
    lines = [line for line in MANIFEST.read_text().splitlines() if line.strip() and not line.lstrip().startswith("#")]
    return [line.split("\t") for line in lines]


def test_every_row_has_a_set_a_folder_a_file_and_an_address():
    assert all(len(row) == 4 for row in rows())
    assert all(row[0] in SETS for row in rows())
    assert all(row[3].startswith("https://") for row in rows())


def test_each_set_holds_every_file_its_variants_need():
    for model in ("prism", "comfy"):
        held = {(row[1], row[2]) for row in rows() if row[0] in ("common", model)}
        for mode in ("fast", "standard"):
            needed = set(required_files(Job(prompt="p", model=model, mode=mode, seconds=12, seed=0)))
            assert needed <= held


def test_a_file_belongs_to_one_set_only():
    files = [(row[1], row[2]) for row in rows()]

    assert len(files) == len(set(files))
