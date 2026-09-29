"""create_sequence auto mode: the baseline plan written through write_plan."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import pytest
from show_fixtures import make_analysis

from xlights_mcp.audio.cache import save_cached
from xlights_mcp.audio.lyrics import LyricTrack, LyricWord, PhonemeEvent
from xlights_mcp.audio.sections import SongSection
from xlights_mcp.config import AudioConfig
from xlights_mcp.sequencer import engine
from xlights_mcp.sequencer.engine import generate_sequence


@pytest.fixture
def audio(tmp_path: Path, click_track: Path) -> AudioConfig:
    config = AudioConfig(cache_dir=tmp_path / "cache")
    analysis = make_analysis(
        20.0,
        np.arange(0, 20, 0.5).tolist(),
        np.arange(0, 20, 2.0).tolist(),
        path=click_track,
        sections=[
            SongSection(label="intro", start_time=0.0, end_time=4.0, energy_level=0.2),
            SongSection(label="chorus", start_time=4.0, end_time=20.0, energy_level=0.8),
        ],
    )
    save_cached(analysis, click_track, config.cache_dir)
    return config


def _generate(click_track, show, audio, **kw) -> dict:
    return generate_sequence(mp3_path=click_track, show_path=show, mode="auto", audio_config=audio, **kw)


def _elements(path: str) -> dict[str, list[ET.Element]]:
    root = ET.parse(path).getroot()
    return {
        el.get("name"): [e for layer in el.iterfind("EffectLayer") for e in layer.iterfind("Effect")]
        for el in root.iterfind("ElementEffects/Element")
    }


def _faces_timing_tracks(path: str, model: str) -> list[str]:
    root = ET.parse(path).getroot()
    db = [e.text or "" for e in root.iterfind("EffectDB/Effect")]
    settings = [dict(kv.split("=", 1) for kv in db[int(e.get("ref"))].split(",")) for e in _elements(path)[model]
                if e.get("name") == "Faces"]
    return [s["E_CHOICE_Faces_TimingTrack"] for s in settings]


def _add_groups(show: Path, *names: str) -> None:
    xml = show / "xlights_rgbeffects.xml"
    groups = "".join(f'<modelGroup name="{n}" models="Door L,Door R"/>' for n in names)
    xml.write_text(xml.read_text(encoding="utf-8").replace("</modelGroups>", f"{groups}</modelGroups>"), encoding="utf-8")


def test_writes_the_baseline_with_beats_and_bars(click_track, show_copy, audio):
    result = _generate(click_track, show_copy, audio, palette_hint="orange and teal")

    assert result["success"] is True
    assert Path(result["output_path"]) == show_copy / f"{click_track.stem}.xsq"
    assert result["timing_tracks"] == ["Beats", "Bars"]
    assert result["palette"] == ["#FF6600"]
    assert result["palette_unrecognised"] == ["teal"]
    assert result["total_effects"] > 0
    elements = _elements(result["output_path"])
    assert elements["Everything Flat"][0].get("name") == "Color Wash"


def test_a_timing_track_named_like_a_show_element_is_left_out(click_track, show_copy, audio):
    _add_groups(show_copy, "Beats")

    result = _generate(click_track, show_copy, audio)

    assert result["success"] is True
    assert result["timing_tracks"] == ["Bars"]
    assert any("Beats timing track skipped" in w for w in result["warnings"])


def test_a_show_without_groups_lets_props_take_turns(click_track, show_copy, audio):
    xml = show_copy / "xlights_rgbeffects.xml"
    text = xml.read_text(encoding="utf-8")
    xml.write_text(re.sub(r"<modelGroup [^>]*/>", "", text), encoding="utf-8")

    result = _generate(click_track, show_copy, audio)

    assert result["success"] is True
    assert any(w.startswith("No feature groups in this show; props take turns") for w in result["warnings"])
    assert "No wash group, so intro/outro/breakdown sections stay dark" in result["warnings"]
    elements = _elements(result["output_path"])
    assert elements["Pipe 1"] and not elements.get("Roof Left")


def test_a_show_of_only_silent_singers_is_an_error(tmp_path, click_track, audio, monkeypatch):
    monkeypatch.setattr(engine, "_try_extract_vocal_tracks", lambda _path: [])
    show = tmp_path / "singers"
    show.mkdir()
    (show / "xlights_rgbeffects.xml").write_text(
        '<xrgb><models><model name="Singer" DisplayAs="Custom"><faceInfo Name="Face"/></model></models></xrgb>',
        encoding="utf-8",
    )

    result = _generate(click_track, show, audio)

    assert "get_show_layout" in result["error"] and "xlights-mcp.json" in result["error"]
    assert list(show.glob("*.xsq")) == []


def test_a_plan_the_writer_rejects_returns_its_errors(click_track, show_copy, audio, monkeypatch):
    bad = {"element": "Nope", "effect": "On", "start_ms": 0, "end_ms": 1000}
    monkeypatch.setattr(engine, "_baseline_placements", lambda *_a: [bad])

    result = _generate(click_track, show_copy, audio)

    assert set(result) == {"error", "errors", "warnings"}
    assert "unknown element 'Nope'" in result["errors"][0]
    assert list(show_copy.glob("*.xsq")) == []


def test_never_overwrites_an_existing_sequence(click_track, show_copy, audio):
    (show_copy / f"{click_track.stem}.xsq").write_text("mine", encoding="utf-8")

    result = _generate(click_track, show_copy, audio)

    assert Path(result["output_path"]).name == f"{click_track.stem} (generated 1).xsq"
    assert (show_copy / f"{click_track.stem}.xsq").read_text(encoding="utf-8") == "mine"


def test_a_show_with_only_placeholders_is_an_error(tmp_path, click_track, audio):
    show = tmp_path / "placeholders"
    show.mkdir()
    (show / "xlights_rgbeffects.xml").write_text(
        '<xrgb><models><model name="Spare - Dont Map" DisplayAs="Single Line"/></models></xrgb>', encoding="utf-8"
    )

    assert "error" in _generate(click_track, show, audio)


def _add_faces(show: Path, *lanterns: tuple[str, str]) -> None:
    xml = show / "xlights_rgbeffects.xml"
    text = xml.read_text(encoding="utf-8")
    for name, y in lanterns:
        text = text.replace(
            f'<model name="{name}" DisplayAs="Custom" WorldPosY="{y}"/>',
            f'<model name="{name}" DisplayAs="Custom" WorldPosY="{y}"><faceInfo Name="Singing Face"/></model>',
        )
    xml.write_text(text, encoding="utf-8")


@pytest.fixture
def singing_show(show_copy: Path) -> Path:
    _add_faces(show_copy, ("Lantern2", "100.0"))
    return show_copy


def _lyrics(name: str = "Vocals") -> LyricTrack:
    return LyricTrack(
        words=[LyricWord(word="boo", start_time=1.0, end_time=1.5)],
        phonemes=[PhonemeEvent(phoneme="U", start_time_ms=1000, end_time_ms=1500)],
        track_name=name,
        available=True,
    )


def test_lyric_marks_sit_on_the_frame_grid_without_overlapping():
    track = LyricTrack(
        words=[
            LyricWord(word="gone", start_time=1.0, end_time=1.0),
            LyricWord(word="off", start_time=2.01, end_time=2.49),
            LyricWord(word="late", start_time=3.5, end_time=4.0),
            LyricWord(word="early", start_time=3.0, end_time=3.6),
            LyricWord(word="end", start_time=9.9, end_time=10.5),
        ],
        phonemes=[
            PhonemeEvent(phoneme="U", start_time_ms=1000, end_time_ms=1010),
            PhonemeEvent(phoneme="O", start_time_ms=2010, end_time_ms=2490),
        ],
        track_name="Vocals",
        available=True,
    )

    words, _, phonemes = engine._lyric_timing_track(track, 10000).labels

    assert [(m.label, m.start_time_ms, m.end_time_ms) for m in words] == [
        ("off", 2000, 2500), ("early", 3000, 3500), ("late", 3500, 4000), ("end", 9900, 10000),
    ]
    assert [(m.label, m.start_time_ms, m.end_time_ms) for m in phonemes] == [("O", 2000, 2500)]


def test_singing_models_without_lyrics_get_no_effects_and_a_warning(click_track, singing_show, audio, monkeypatch):
    monkeypatch.setattr(engine, "_try_extract_vocal_tracks", lambda _path: [])

    result = _generate(click_track, singing_show, audio)

    assert any("Lyrics unavailable" in w for w in result["warnings"])
    elements = _elements(result["output_path"])
    assert not elements.get("Lantern2")
    assert sum(e.get("name") == "On" for effects in elements.values() for e in effects) == len(range(4, 20, 2))


def test_singing_models_need_assignments_before_anything_is_written(click_track, singing_show, audio, monkeypatch):
    monkeypatch.setattr(engine, "_try_extract_vocal_tracks", lambda _path: [_lyrics()])

    result = _generate(click_track, singing_show, audio)

    assert result["needs_vocal_assignment"] is True
    assert list(singing_show.glob("*.xsq")) == []


def test_faces_are_sequenced_and_groups_holding_them_left_out(click_track, singing_show, audio, monkeypatch):
    monkeypatch.setattr(engine, "_try_extract_vocal_tracks", lambda _path: [_lyrics()])

    result = _generate(click_track, singing_show, audio, vocal_assignments={"all": "Vocals"})

    assert result["has_lyrics"] is True and result["singing_models"] == ["Lantern2"]
    elements = _elements(result["output_path"])
    assert any(e.get("name") == "Faces" for e in elements["Lantern2"])
    assert not any(e.get("name") == "On" for e in elements["Lantern2"])
    assert not elements.get("Lanterns") and not elements.get("Everything Flat")
    assert "Vocals" in result["timing_tracks"]


@pytest.mark.parametrize(
    "groups, renamed", [(("Door",), "Door (lyrics)"), (("Door", "Door (lyrics)"), "Door (lyrics) 2")]
)
def test_a_lyric_track_named_like_a_show_element_is_renamed(
    click_track, singing_show, audio, monkeypatch, groups, renamed
):
    _add_groups(singing_show, *[g for g in groups if g != "Door"])
    monkeypatch.setattr(
        engine, "_try_extract_vocal_tracks", lambda _path: [_lyrics().model_copy(update={"track_name": "Door"})]
    )

    result = _generate(click_track, singing_show, audio, vocal_assignments={"all": "Door"})

    assert result["success"] is True
    assert result["timing_tracks"] == ["Beats", "Bars", renamed]
    assert result["vocal_assignments"] == {"Lantern2": renamed}
    assert _faces_timing_tracks(result["output_path"], "Lantern2") == [renamed]
    assert any(f"renamed to {renamed!r}" in w for w in result["warnings"])


def test_an_unknown_assigned_track_falls_back_to_the_first_with_a_warning(click_track, singing_show, audio, monkeypatch):
    monkeypatch.setattr(engine, "_try_extract_vocal_tracks", lambda _path: [_lyrics()])

    result = _generate(click_track, singing_show, audio, vocal_assignments={"all": "Nope"})

    assert result["vocal_assignments"] == {"Lantern2": "Vocals"}
    assert result["warnings"].count("vocal_assignments names unknown track 'Nope'; using 'Vocals'") == 1


def test_an_assignment_for_a_model_that_does_not_sing_is_reported(click_track, singing_show, audio, monkeypatch):
    monkeypatch.setattr(engine, "_try_extract_vocal_tracks", lambda _path: [_lyrics()])

    result = _generate(click_track, singing_show, audio, vocal_assignments={"Lantern9": "Vocals"})

    assert result["vocal_assignments"] == {"Lantern2": "Vocals"}
    assert "vocal_assignments key 'Lantern9' isn't a singing model" in result["warnings"]


def test_each_singing_model_gets_its_assigned_track(click_track, show_copy, audio, monkeypatch):
    _add_faces(show_copy, ("Lantern1", "90.0"), ("Lantern2", "100.0"))
    monkeypatch.setattr(engine, "_try_extract_vocal_tracks", lambda _path: [_lyrics(), _lyrics("Backing")])

    result = _generate(
        click_track, show_copy, audio, vocal_assignments={"Lantern1": "Backing", "Lantern2": "Vocals"}
    )

    assert result["vocal_assignments"] == {"Lantern1": "Backing", "Lantern2": "Vocals"}
    assert _faces_timing_tracks(result["output_path"], "Lantern1") == ["Backing"]
    assert _faces_timing_tracks(result["output_path"], "Lantern2") == ["Vocals"]
    assert not any("vocal_assignments" in w for w in result["warnings"])
