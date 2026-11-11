"""Fast render smoke test (frames only, no ffmpeg needed)."""
from __future__ import annotations

import pytest

from content.generators import generate
from content.rotation import find_item
from render.video import build_timeline


@pytest.mark.parametrize("item_id", ["b05", "b09", "q04", "q12"])
def test_library_frames_render(item_id):
    item = find_item(item_id)
    tl = build_timeline(item, "pokerclub")
    assert 15 <= tl.duration <= 25
    for t in (0.5, 5.0, 8.5, 10.5, 12.5, tl.duration - 1):
        f = tl.frame(t)
        assert f.size == (1080, 1920) and f.mode == "RGB"


@pytest.mark.parametrize("fmt,n", [("quiz", 3), ("breakdown", 1)])
def test_generated_frames_render(fmt, n):
    tl = build_timeline(generate(fmt, n), None)
    assert tl.frame(9.0).size == (1080, 1920)
