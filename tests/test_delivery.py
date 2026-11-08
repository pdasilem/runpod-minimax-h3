import base64

from delivery import collect_outputs, emit_file


def test_small_file_goes_back_inline():
    used = [0]

    result = emit_file("scene.mp4", b"video", {}, used)

    assert result == {"filename": "scene.mp4", "b64": base64.b64encode(b"video").decode()}
    assert used == [5]


def test_collects_the_saved_video_of_the_finished_prompt():
    history = {"outputs": {"save": {"gifs": [{"filename": "t2va_00001.mp4", "subfolder": "video", "type": "output"}]}}}
    asked = []

    def fetch(path: str) -> bytes:
        asked.append(path)
        return b"mp4"

    outputs = collect_outputs(history, {}, fetch)

    assert [o["filename"] for o in outputs] == ["t2va_00001.mp4"]
    assert asked == ["/view?filename=t2va_00001.mp4&subfolder=video&type=output"]
