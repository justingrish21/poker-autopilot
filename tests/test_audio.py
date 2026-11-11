"""Generated audio: sound effects line up with the timeline, the beat fills the video."""
from __future__ import annotations

from render import audio as A
from render.video import build_timeline
from content.rotation import find_item


def test_every_sound_effect_renders():
    for name in A.SFX_GAIN:
        snd = A.sfx(name)
        assert len(snd) > 100 and max(abs(v) for v in snd) > 0.05, name


def test_sfx_track_places_sounds_at_their_times():
    buf = A.sfx_track([(1.0, "ding", 1.0), (2.0, "tick", 1.0)], 3.0)
    assert len(buf) == 3 * A.SR
    assert max(abs(v) for v in buf[: int(0.95 * A.SR)]) == 0          # silence before the first cue
    assert max(abs(v) for v in buf[A.SR: A.SR + 2000]) > 0.05


def test_timelines_schedule_sounds():
    for item_id in ("q04", "b06", "gen-allin-00001"):
        tl = build_timeline(find_item(item_id), "@pokerpilot08")
        names = {n for _, n, _ in tl.sounds}
        assert {"pop", "whoosh"} <= names
        if item_id.startswith("q"):
            assert sum(1 for _, n, _ in tl.sounds if n == "tick") == 3 and "ding" in names
        if item_id.startswith("gen-allin"):
            assert {"thump", "chips", "impact"} <= names and ({"win", "sad"} & names)


def test_beat_fills_duration():
    b = A.beat_track(4.0, seed=3)
    assert len(b) == 4 * A.SR and max(abs(v) for v in b) > 0.1
