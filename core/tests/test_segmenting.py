import pytest

from traduko.segmenting import refine_segments


def seg(id_: int, start: float, end: float, text: str) -> dict:
    return {"id": id_, "start": start, "end": end, "text": text}


def test_merges_short_fragments_until_sentence_end() -> None:
    out = refine_segments(
        [seg(1, 0.0, 1.0, "I went"), seg(2, 1.1, 2.0, "to the store."), seg(3, 2.5, 3.5, "Then home.")]
    )
    assert [s["text"] for s in out] == ["I went to the store.", "Then home."]
    assert out[0]["start"] == 0.0 and out[0]["end"] == 2.0
    assert [s["id"] for s in out] == [1, 2]


def test_cjk_merge_has_no_space() -> None:
    out = refine_segments([seg(1, 0.0, 1.0, "我走進"), seg(2, 1.1, 2.0, "商店。")])
    assert out[0]["text"] == "我走進商店。"


def test_does_not_merge_across_large_gap() -> None:
    out = refine_segments([seg(1, 0.0, 1.0, "Hello"), seg(2, 3.0, 4.0, "world.")])
    assert len(out) == 2


def test_splits_long_line_at_punctuation_with_proportional_timing() -> None:
    text = "First sentence is here. Second one follows."
    out = refine_segments([seg(1, 0.0, 6.0, text)], max_chars=30)
    assert len(out) == 2
    assert out[0]["text"] == "First sentence is here."
    assert out[1]["text"] == "Second one follows."
    total_chars = len(out[0]["text"]) + len(out[1]["text"])
    assert out[0]["end"] == pytest.approx(6.0 * len(out[0]["text"]) / total_chars, abs=0.01)
    assert out[1]["start"] == out[0]["end"]
    assert out[1]["end"] == 6.0


def test_hard_split_without_punctuation() -> None:
    out = refine_segments([seg(1, 0.0, 4.0, "word " * 20)], max_chars=30)
    assert all(len(s["text"]) <= 30 for s in out)


def test_drops_empty_segments() -> None:
    out = refine_segments([seg(1, 0.0, 1.0, "  "), seg(2, 1.0, 2.0, "ok.")])
    assert [s["text"] for s in out] == ["ok."]
