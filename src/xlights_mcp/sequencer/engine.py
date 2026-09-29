"""Sequence generation: the create_sequence baseline plan, singing faces, and the guided preview."""

from __future__ import annotations

import logging
from collections import Counter
from pathlib import Path
from typing import Literal, NamedTuple

from xlights_mcp.audio.analyzer import ProgressCallback, SongAnalysis, full_analysis
from xlights_mcp.audio.lyrics import LyricTrack
from xlights_mcp.audio.sections import SongSection
from xlights_mcp.audio.silences import kicks, nearest_kick
from xlights_mcp.config import AudioConfig
from xlights_mcp.sequencer.plan_writer import write_plan
from xlights_mcp.sequencer.timing import STEM_TRACK_NAMES, last_frame_ms, to_frame
from xlights_mcp.xlights.layout import build_show_layout
from xlights_mcp.xlights.models import ShowConfig
from xlights_mcp.xlights.palettes import palette_colors
from xlights_mcp.xlights.show import load_show_config
from xlights_mcp.xlights.xsq_writer import DEFAULT_XLIGHTS_VERSION, TimingTrack, TimingTrackLabel

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Effect presets: key → (xLights effect name, settings from real human-made sequences)
# ---------------------------------------------------------------------------

EFFECT_PRESETS: dict[str, tuple[str, dict[str, str]]] = {
    "Chase_left": (
        "SingleStrand",
        {"B_CHOICE_BufferStyle": "Per Model Single Line", "E_CHECKBOX_Chase_Group_All": "0",
         "E_CHOICE_Chase_Type1": "Left-Right", "E_CHOICE_Fade_Type": "None",
         "E_CHOICE_SingleStrand_Colors": "Palette", "E_NOTEBOOK_SSEFFECT_TYPE": "Chase",
         "E_SLIDER_Color_Mix1": "36", "E_SLIDER_Number_Chases": "1",
         "E_TEXTCTRL_Chase_Rotations": "1.0"},
    ),
    "Chase_right": (
        "SingleStrand",
        {"B_CHOICE_BufferStyle": "Per Model Single Line", "E_CHECKBOX_Chase_Group_All": "0",
         "E_CHOICE_Chase_Type1": "Right-Left", "E_CHOICE_Fade_Type": "None",
         "E_CHOICE_SingleStrand_Colors": "Palette", "E_NOTEBOOK_SSEFFECT_TYPE": "Chase",
         "E_SLIDER_Color_Mix1": "36", "E_SLIDER_Number_Chases": "1",
         "E_TEXTCTRL_Chase_Rotations": "1.0"},
    ),
    "Chase_from_middle": (
        "SingleStrand",
        {"B_CHOICE_BufferStyle": "Per Model Single Line", "E_CHECKBOX_Chase_Group_All": "0",
         "E_CHOICE_Chase_Type1": "From Middle", "E_CHOICE_Fade_Type": "None",
         "E_CHOICE_SingleStrand_Colors": "Palette", "E_NOTEBOOK_SSEFFECT_TYPE": "Chase",
         "E_SLIDER_Color_Mix1": "36", "E_SLIDER_Number_Chases": "1",
         "E_TEXTCTRL_Chase_Rotations": "1.0"},
    ),
    "Chase_bounce": (
        "SingleStrand",
        {"B_CHOICE_BufferStyle": "Per Model Single Line", "E_CHECKBOX_Chase_Group_All": "0",
         "E_CHOICE_Chase_Type1": "Bounce from Left", "E_CHOICE_Fade_Type": "None",
         "E_CHOICE_SingleStrand_Colors": "Palette", "E_NOTEBOOK_SSEFFECT_TYPE": "Chase",
         "E_SLIDER_Color_Mix1": "36", "E_SLIDER_Number_Chases": "1",
         "E_TEXTCTRL_Chase_Rotations": "1.0"},
    ),
    "Twinkle_ambient": (
        "Twinkle",
        {"E_CHECKBOX_Twinkle_ReRandom": "0", "E_CHECKBOX_Twinkle_Strobe": "0",
         "E_CHOICE_Twinkle_Style": "New Render Method",
         "E_SLIDER_Twinkle_Count": "3", "E_SLIDER_Twinkle_Steps": "14",
         "T_TEXTCTRL_Fadein": "0.5", "T_TEXTCTRL_Fadeout": "1.0"},
    ),
    "Twinkle_dense": (
        "Twinkle",
        {"E_CHECKBOX_Twinkle_ReRandom": "0", "E_CHECKBOX_Twinkle_Strobe": "0",
         "E_CHOICE_Twinkle_Style": "New Render Method",
         "E_SLIDER_Twinkle_Count": "36", "E_SLIDER_Twinkle_Steps": "10",
         "T_TEXTCTRL_Fadein": "0.2", "T_TEXTCTRL_Fadeout": "0.5"},
    ),
    "ColorWash_slow": (
        "Color Wash",
        {"E_CHECKBOX_ColorWash_CircularPalette": "1", "E_TEXTCTRL_ColorWash_Cycles": "1",
         "T_TEXTCTRL_Fadein": "1.0", "T_TEXTCTRL_Fadeout": "1.0"},
    ),
    "ColorWash_fast": (
        "Color Wash",
        {"E_CHECKBOX_ColorWash_CircularPalette": "1", "E_TEXTCTRL_ColorWash_Cycles": "3"},
    ),
    "ColorWash_cycling": (
        "Color Wash",
        {"E_CHECKBOX_ColorWash_CircularPalette": "1", "E_TEXTCTRL_ColorWash_Cycles": "20.0",
         "T_TEXTCTRL_Fadein": "2.5"},
    ),
    "Plasma_slow": (
        "Plasma",
        {"E_CHOICE_Plasma_Color": "Normal", "E_SLIDER_Plasma_Line_Density": "1",
         "E_SLIDER_Plasma_Speed": "10", "E_SLIDER_Plasma_Style": "10",
         "T_TEXTCTRL_Fadein": "0.5", "T_TEXTCTRL_Fadeout": "0.5"},
    ),
    "Plasma_fast": (
        "Plasma",
        {"E_CHOICE_Plasma_Color": "Normal", "E_SLIDER_Plasma_Line_Density": "1",
         "E_SLIDER_Plasma_Speed": "80", "E_SLIDER_Plasma_Style": "10",
         "T_TEXTCTRL_Fadein": "0.25", "T_TEXTCTRL_Fadeout": "0.25"},
    ),
    "Spirals_slow": (
        "Spirals",
        {"E_CHECKBOX_Spirals_3D": "1", "E_CHECKBOX_Spirals_Blend": "0",
         "E_CHECKBOX_Spirals_Grow": "0", "E_CHECKBOX_Spirals_Shrink": "0",
         "E_SLIDER_Spirals_Count": "1", "E_SLIDER_Spirals_Rotation": "20",
         "E_SLIDER_Spirals_Thickness": "50", "E_TEXTCTRL_Spirals_Movement": "1.0",
         "T_TEXTCTRL_Fadein": "0.5", "T_TEXTCTRL_Fadeout": "0.5"},
    ),
    "Spirals_fast": (
        "Spirals",
        {"E_CHECKBOX_Spirals_3D": "1", "E_CHECKBOX_Spirals_Blend": "0",
         "E_CHECKBOX_Spirals_Grow": "0", "E_CHECKBOX_Spirals_Shrink": "0",
         "E_SLIDER_Spirals_Count": "5", "E_SLIDER_Spirals_Rotation": "20",
         "E_SLIDER_Spirals_Thickness": "18", "E_TEXTCTRL_Spirals_Movement": "3.0"},
    ),
    "Spirals_reverse": (
        "Spirals",
        {"E_CHECKBOX_Spirals_3D": "1", "E_CHECKBOX_Spirals_Blend": "0",
         "E_CHECKBOX_Spirals_Grow": "0", "E_CHECKBOX_Spirals_Shrink": "0",
         "E_SLIDER_Spirals_Count": "1", "E_SLIDER_Spirals_Rotation": "-20",
         "E_SLIDER_Spirals_Thickness": "50", "E_TEXTCTRL_Spirals_Movement": "-1.0"},
    ),
    "Meteors_rain": (
        "Meteors",
        {"E_CHECKBOX_Meteors_UseMusic": "0", "E_CHOICE_Meteors_Effect": "Down",
         "E_CHOICE_Meteors_Type": "Palette", "E_SLIDER_Meteors_Count": "10",
         "E_SLIDER_Meteors_Length": "25", "E_SLIDER_Meteors_Speed": "15",
         "E_SLIDER_Meteors_Swirl_Intensity": "0"},
    ),
    "Pinwheel_sweep": (
        "Pinwheel",
        {"E_CHECKBOX_Pinwheel_Rotation": "1", "E_CHOICE_Pinwheel_3D": "Sweep",
         "E_CHOICE_Pinwheel_Style": "New Render Method",
         "E_SLIDER_Pinwheel_ArmSize": "150", "E_SLIDER_Pinwheel_Arms": "10",
         "E_SLIDER_Pinwheel_Speed": "5", "E_SLIDER_Pinwheel_Twist": "60"},
    ),
    "Butterfly_gentle": (
        "Butterfly",
        {"E_CHOICE_Butterfly_Colors": "Palette", "E_CHOICE_Butterfly_Direction": "Normal",
         "E_SLIDER_Butterfly_Chunks": "1", "E_SLIDER_Butterfly_Skip": "2",
         "E_SLIDER_Butterfly_Speed": "10", "E_SLIDER_Butterfly_Style": "1",
         "T_TEXTCTRL_Fadein": "0.25", "T_TEXTCTRL_Fadeout": "0.25"},
    ),
    "Marquee_default": (
        "Marquee",
        {"E_SLIDER_Marquee_Band_Size": "3", "E_SLIDER_Marquee_Skip_Size": "3",
         "E_SLIDER_Marquee_Speed": "3", "E_SLIDER_Marquee_Stagger": "0"},
    ),
    "On_solid": ("On", {}),
}


# ---------------------------------------------------------------------------
# Feature-group effects by the group's majority model category
# ---------------------------------------------------------------------------

# Sections below HIGH_ENERGY_THRESHOLD
BED_EFFECTS: dict[str, list[str]] = {
    "arch": ["ColorWash_slow", "Twinkle_ambient"],
    "tree": ["Spirals_slow", "Plasma_slow", "ColorWash_cycling"],
    "single_line": ["ColorWash_slow", "Twinkle_ambient"],
    "poly_line": ["ColorWash_slow", "Twinkle_ambient"],
    "window": ["ColorWash_slow", "On_solid"],
    "custom": ["Twinkle_ambient", "ColorWash_slow", "Butterfly_gentle"],
    "other": ["ColorWash_slow", "Twinkle_ambient"],
}

# Sections at or above HIGH_ENERGY_THRESHOLD
MOTION_EFFECTS: dict[str, list[str]] = {
    "arch": ["Chase_from_middle", "Chase_left", "Chase_right", "Chase_bounce"],
    "tree": ["Spirals_fast", "Spirals_reverse", "Pinwheel_sweep", "Meteors_rain"],
    "single_line": ["Chase_left", "Chase_right", "Chase_bounce"],
    "poly_line": ["Chase_left", "Chase_right", "Chase_from_middle"],
    "window": ["Marquee_default"],
    "custom": ["Plasma_fast", "Butterfly_gentle"],
    "other": ["Chase_from_middle", "ColorWash_fast"],
}

HIGH_ENERGY_THRESHOLD = 0.65
LOW_ENERGY_THRESHOLD = 0.35


SectionRole = Literal["wash", "features", "accents"]

SECTION_TYPE_CONFIG: dict[str, SectionRole] = {
    "intro": "wash", "outro": "wash", "breakdown": "wash",
    "chorus": "accents", "drop": "accents", "instrumental": "accents",
    "verse": "features", "bridge": "features", "build": "features",
    "transition": "features", "unknown": "features",
}
ACCENT_MS = 100
WASH_BRIGHTNESS = 40
FACE_BED_KEYS = ("Twinkle_ambient", "ColorWash_cycling", "Butterfly_gentle")


def generate_sequence(
    mp3_path: Path,
    show_path: Path | None,
    mode: str = "auto",
    palette_hint: str | None = None,
    theme: str | None = None,
    audio_config: AudioConfig | None = None,
    vocal_assignments: dict[str, str] | None = None,
    progress: ProgressCallback | None = None,
    xlights_version: str = DEFAULT_XLIGHTS_VERSION,
) -> dict:
    """Write the baseline sequence for a music file (auto), or return the guided preview.

    Args:
        vocal_assignments: Optional mapping of model_name → vocal track name.
            Use "all" as key to assign a track to all singing models.
            If None and singing models exist, returns discovery info instead
            of generating, so the caller can prompt the user.
    """
    if not show_path or not show_path.exists():
        return {"error": f"Show path not found: {show_path}"}

    show_config = load_show_config(show_path)
    if not show_config.real_models:
        return {"error": "No models with lights found in show configuration"}

    analysis = full_analysis(mp3_path, audio_config, progress=progress)

    if mode == "auto":
        return _generate_auto(
            analysis, show_config, mp3_path, palette_hint, theme,
            vocal_assignments=vocal_assignments, xlights_version=xlights_version,
        )
    elif mode == "guided":
        return _generate_guided_preview(analysis, show_config)
    elif mode == "template":
        return {"error": "Template mode not yet implemented. Use 'auto' or 'guided'."}
    else:
        return {"error": f"Invalid mode: {mode}"}


def preview_sequence_plan(
    mp3_path: Path,
    show_path: Path | None,
    mode: str = "auto",
    audio_config: AudioConfig | None = None,
    progress: ProgressCallback | None = None,
) -> dict:
    """Preview what a sequence would look like without generating."""
    if not show_path or not show_path.exists():
        return {"error": f"Show path not found: {show_path}"}

    analysis = full_analysis(mp3_path, audio_config, progress=progress)
    show_config = load_show_config(show_path)

    sections_summary = []
    for s in analysis.sections:
        sections_summary.append({
            "label": s.label,
            "start": f"{s.start_time:.1f}s",
            "end": f"{s.end_time:.1f}s",
            "duration": f"{s.duration:.1f}s",
            "energy": f"{s.energy_level:.2f}",
        })

    return {
        "song": mp3_path.stem,
        "duration": f"{analysis.duration_seconds:.1f}s",
        "tempo": f"{analysis.beats.tempo:.0f} BPM",
        "beat_count": len(analysis.beats.beat_times),
        "sections": sections_summary,
        "models": len(show_config.real_models),
        "controllers": len(show_config.controllers),
    }


# ---------------------------------------------------------------------------
# Auto-generation engine
# ---------------------------------------------------------------------------


def _free_sequence_name(show_path: Path, stem: str) -> str:
    name, counter = stem, 1
    while (show_path / f"{name}.xsq").exists():
        name = f"{stem} (generated {counter})"
        counter += 1
    return name


def _free_track_name(name: str, taken: set[str]) -> str:
    if name not in taken:
        return name
    candidate, n = f"{name} (lyrics)", 2
    while candidate in taken:
        candidate, n = f"{name} (lyrics) {n}", n + 1
    return candidate


def _renamed_lyric_tracks(
    tracks: list[LyricTrack], taken: set[str], warnings: list[str]
) -> tuple[list[LyricTrack], dict[str, LyricTrack]]:
    """The tracks renamed away from names already taken, and a lookup by old and new name."""
    taken = set(taken)
    renamed: list[LyricTrack] = []
    by_name: dict[str, LyricTrack] = {}
    for original in tracks:
        name = _free_track_name(original.track_name, taken)
        taken.add(name)
        if name != original.track_name:
            warnings.append(
                f"lyric track {original.track_name!r} renamed to {name!r}: a model, group or "
                "timing track already has that name"
            )
        track = original.model_copy(update={"track_name": name})
        renamed.append(track)
        by_name.setdefault(original.track_name, track)
        by_name[name] = track
    return renamed, by_name


def _framed_marks(marks: list[tuple[str, float, float]], song_end: int) -> list[TimingTrackLabel]:
    """Frame-rounded marks clipped to the song, sorted, each ending by the next one's start."""
    framed = sorted(
        (to_frame(start), min(to_frame(end), song_end), label) for label, start, end in marks
    )
    framed = [m for m in framed if m[1] > m[0]]
    labels = []
    for k, (start, end, label) in enumerate(framed):
        if k + 1 < len(framed):
            end = min(end, framed[k + 1][0])
        if end > start:
            labels.append(TimingTrackLabel(label=label, start_time_ms=start, end_time_ms=end))
    return labels


def _lyric_timing_track(track: LyricTrack, song_end: int) -> TimingTrack:
    words = _framed_marks([(w.word, w.start_time * 1000, w.end_time * 1000) for w in track.words], song_end)
    phonemes = _framed_marks([(p.phoneme, p.start_time_ms, p.end_time_ms) for p in track.phonemes], song_end)
    return TimingTrack(name=track.track_name, labels=[words, words, phonemes])


def _face_placements(
    analysis: SongAnalysis, model: str, face_definition: str, track_name: str, colors: list[str]
) -> list[dict]:
    palette = {"colors": colors}
    song_end = last_frame_ms(analysis.duration_ms)
    plan = []
    for index, section in enumerate(analysis.sections):
        span = _section_span(section, song_end)
        if span is None:
            continue
        if section.energy_level >= HIGH_ENERGY_THRESHOLD:
            key = "Twinkle_dense"
        elif section.energy_level < LOW_ENERGY_THRESHOLD:
            key = "ColorWash_slow"
        else:
            key = FACE_BED_KEYS[index % len(FACE_BED_KEYS)]
        plan.append(_placement(model, 1, key, *span, palette))
    plan.append({
        "element": model, "layer": 0, "effect": "Faces", "start_ms": 0, "end_ms": song_end,
        "settings": {
            "E_CHECKBOX_Faces_Outline": "1",
            "E_CHOICE_Faces_EyeBlinkDuration": "Normal",
            "E_CHOICE_Faces_EyeBlinkFrequency": "Normal",
            "E_CHOICE_Faces_Eyes": "Auto",
            "E_CHOICE_Faces_FaceDefinition": face_definition,
            "E_CHOICE_Faces_TimingTrack": track_name,
            "T_TEXTCTRL_Fadein": "0.5",
            "T_TEXTCTRL_Fadeout": "0.5",
        },
        "palette": palette,
    })
    return plan


def _generate_auto(
    analysis: SongAnalysis,
    show_config: ShowConfig,
    mp3_path: Path,
    palette_hint: str | None,
    theme: str | None,
    vocal_assignments: dict[str, str] | None = None,
    xlights_version: str = DEFAULT_XLIGHTS_VERSION,
) -> dict:
    """Write the baseline sequence: the baseline plan plus singing faces, through write_plan."""
    show_path = Path(show_config.show_path)
    colors, unrecognised = palette_colors(palette_hint, theme)
    singing = {m.name: m.face_definitions[0] for m in show_config.real_models if m.face_definitions}
    warnings: list[str] = []
    faces: list[dict] = []
    lyric_tracks: list[TimingTrack] = []
    assignments: dict[str, str] = {}
    elements = show_config.element_names
    stems = STEM_TRACK_NAMES if analysis.stem_analysis.available else ()
    named_tracks = []
    for name in ("Beats", "Bars", *stems):
        if name in elements:
            warnings.append(f"{name} timing track skipped: the show has a model or group with that name")
        else:
            named_tracks.append(name)

    if singing:
        vocal_tracks = _try_extract_vocal_tracks(mp3_path)
        if not vocal_tracks:
            warnings.append(
                f"Lyrics unavailable, so singing models {sorted(singing)} get no face effects "
                "(install the lyrics extra for Whisper)"
            )
        elif vocal_assignments is None:
            return {
                "needs_vocal_assignment": True,
                "singing_models": [{"model_name": m, "face_definition": f} for m, f in singing.items()],
                "vocal_tracks": [
                    {"track_name": t.track_name, "source": t.source, "word_count": len(t.words)}
                    for t in vocal_tracks
                ],
                "message": (
                    "Singing face models and vocal tracks detected. "
                    "Please assign vocal tracks to models using the vocal_assignments parameter. "
                    "Pass a dict mapping model names to track names, "
                    'or use {"all": "<track_name>"} to assign one track to all singing models.'
                ),
            }
        else:
            vocal_tracks, by_name = _renamed_lyric_tracks(vocal_tracks, elements | set(named_tracks), warnings)
            warnings.extend(
                f"vocal_assignments key {key!r} isn't a singing model"
                for key in vocal_assignments if key != "all" and key not in singing
            )
            for model, face_definition in singing.items():
                requested = vocal_assignments.get("all", vocal_assignments.get(model))
                track = by_name.get(requested, vocal_tracks[0])
                if requested is not None and requested not in by_name:
                    unknown = f"vocal_assignments names unknown track {requested!r}; using {track.track_name!r}"
                    if unknown not in warnings:
                        warnings.append(unknown)
                assignments[model] = track.track_name
                faces.extend(_face_placements(analysis, model, face_definition, track.track_name, colors))
            song_end = last_frame_ms(analysis.duration_ms)
            lyric_tracks = [_lyric_timing_track(t, song_end) for t in vocal_tracks]

    cast = _baseline_cast(show_config, frozenset(singing) if faces else frozenset(), frozenset(singing))
    if cast.props_take_turns:
        warnings.append(
            "No usable feature groups (none, or all hold singing models); props take turns instead (see get_show_layout / xlights-mcp.json tiers)"
        )
    if cast.wash is None:
        warnings.append("No wash group, so intro/outro/breakdown sections stay dark")
    plan = _baseline_placements(analysis, cast, colors) + faces
    if not plan:
        return {
            "error": (
                "Nothing to light: the show has no usable groups or props for the baseline. "
                "Check get_show_layout, and set group tiers in the show's xlights-mcp.json."
            ),
            "warnings": warnings,
        }
    report = write_plan(
        plan, analysis, mp3_path, show_path,
        name=_free_sequence_name(show_path, mp3_path.stem),
        timing_tracks=named_tracks,
        extra_tracks=lyric_tracks,
        show=show_config,
        xlights_version=xlights_version,
    )
    if not report["written"]:
        return {
            "error": "The baseline plan failed validation.",
            "errors": report["errors"],
            "warnings": warnings + report["warnings"],
        }

    return {
        "success": True,
        "output_path": report["path"],
        "song": mp3_path.stem,
        "duration": f"{analysis.duration_seconds:.1f}s",
        "tempo": f"{analysis.beats.tempo:.0f} BPM",
        "sections": len(analysis.sections),
        "elements": report["elements"],
        "total_effects": report["effects"],
        "layers_used": report["max_layer"] + 1 if report["effects"] else 0,
        "palette": colors,
        "palette_unrecognised": unrecognised,
        "timing_tracks": report["timing_tracks"],
        "has_lyrics": bool(faces),
        "singing_models": sorted(singing) if faces else [],
        "vocal_assignments": assignments,
        "warnings": warnings + report["warnings"],
        "message": (
            f"Sequence created: {Path(report['path']).name}. This is a simple baseline; for a "
            "hand-made-style sequence use the sequence_song prompt with write_sequence."
        ),
    }


# ---------------------------------------------------------------------------
# Guided mode
# ---------------------------------------------------------------------------


def _generate_guided_preview(analysis: SongAnalysis, show_config: ShowConfig) -> dict:
    """Return analysis for guided/interactive mode."""
    sections = []
    for i, s in enumerate(analysis.sections):
        sections.append({
            "index": i,
            "label": s.label,
            "start_time": f"{s.start_time:.1f}s",
            "end_time": f"{s.end_time:.1f}s",
            "energy": f"{s.energy_level:.2f}",
        })

    models_by_category = {}
    for m in show_config.real_models:
        cat = m.model_category
        models_by_category.setdefault(cat, []).append(m.name)

    return {
        "mode": "guided",
        "message": "Here's the song analysis. Tell me which effects you want for each section.",
        "song_info": {
            "tempo": f"{analysis.beats.tempo:.0f} BPM",
            "duration": f"{analysis.duration_seconds:.1f}s",
            "beat_count": len(analysis.beats.beat_times),
        },
        "sections": sections,
        "models_by_category": models_by_category,
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _height_order(row: dict) -> tuple:
    y_range = row["y_range"]
    return (y_range[0], y_range[1], row["name"]) if y_range else (float("inf"), float("inf"), row["name"])


def _group_categories(show: ShowConfig) -> dict[str, str]:
    by_name = {m.name: m for m in show.models}
    categories = {}
    for group in show.model_groups:
        cats = [by_name[n].model_category for n in group.leaf_models if n in by_name]
        categories[group.name] = Counter(cats).most_common(1)[0][0] if cats else "other"
    return categories


def _section_span(section: SongSection, song_end: int) -> tuple[int, int] | None:
    """The section's frame-rounded (start, end), clipped to the song; None when nothing is left."""
    start, end = to_frame(section.start_time_ms), min(to_frame(section.end_time_ms), song_end)
    return (start, end) if end > start else None


def _placement(element: str, layer: int, key: str, start_ms: int, end_ms: int, palette: dict) -> dict:
    effect, settings = EFFECT_PRESETS[key]
    return {
        "element": element, "layer": layer, "effect": effect,
        "start_ms": start_ms, "end_ms": end_ms, "settings": dict(settings), "palette": palette,
    }


class _Cast(NamedTuple):
    wash: dict | None
    features: list[dict]
    props_take_turns: bool
    accent_pool: list[str]
    leaves: dict[str, set[str]]
    categories: dict[str, str]


def _baseline_cast(show: ShowConfig, exclude: frozenset[str], accent_exclude: frozenset[str]) -> _Cast:
    """Who lights in the baseline: the wash group, the feature rows by height, the accent props.

    Without a usable feature group, the real models take turns instead, as one-prop rows.
    """
    layout = build_show_layout(show)
    leaves = {g.name: set(g.leaf_models) for g in show.model_groups}
    categories = _group_categories(show)
    usable = [row for row in layout["groups"] if not leaves[row["name"]] & exclude]
    wash = max((r for r in usable if r["tier"] == "wash"), key=lambda r: r["prop_count"], default=None)
    features = [r for r in usable if r["tier"] == "feature"]
    props_take_turns = not features
    if props_take_turns:
        props = [m for m in show.real_models if m.name not in exclude | accent_exclude]
        y = {m.name: m.world_pos_y for m in props}
        features = [{"name": m.name, "y_range": None if y[m.name] is None else (y[m.name], y[m.name])} for m in props]
        leaves |= {m.name: {m.name} for m in props}
        categories |= {m.name: m.model_category for m in props}
    accent_pool = list(dict.fromkeys(
        prop for row in layout["groups"] if row["tier"] == "feature"
        for prop in row["accent_props"] if prop not in exclude and prop not in accent_exclude
    ))
    return _Cast(wash, sorted(features, key=_height_order), props_take_turns, accent_pool, leaves, categories)


def build_baseline_plan(
    analysis: SongAnalysis,
    show: ShowConfig,
    colors: list[str],
    exclude: frozenset[str] = frozenset(),
    *,
    accent_exclude: frozenset[str] = frozenset(),
) -> list[dict]:
    """Plan placements for the baseline sequence.

    Quiet sections (intro, outro, breakdown) get the largest wash group dimmed. Other sections
    light one half of the feature groups (by height), alternating; without feature groups the
    show's props take turns the same way. Chorus, drop and instrumental sections add a short
    "On" on each downbeat, cycling through accent props that aren't inside the lit feature
    groups. Groups holding a model in `exclude` are left out, and so are those models as
    accents and props; models in `accent_exclude` are only left out as accents and props.
    """
    return _baseline_placements(analysis, _baseline_cast(show, exclude, accent_exclude), colors)


def _baseline_placements(analysis: SongAnalysis, cast: _Cast, colors: list[str]) -> list[dict]:
    split = -(-len(cast.features) // 2)
    halves = [cast.features[:split], cast.features[split:]]
    palette = {"colors": colors}
    song_end = last_frame_ms(analysis.duration_ms)
    try:
        kick_times = kicks(analysis)
    except ValueError:
        kick_times = []

    plan: list[dict] = []
    feature_turn = accent_turn = 0
    for index, section in enumerate(analysis.sections):
        span = _section_span(section, song_end)
        if span is None:
            continue
        start, end = span
        role = SECTION_TYPE_CONFIG.get(section.label, "features")
        if role == "wash":
            if cast.wash:
                plan.append(_placement(
                    cast.wash["name"], 0, "ColorWash_slow", start, end,
                    {"colors": colors, "brightness": WASH_BRIGHTNESS},
                ))
            continue

        lit = halves[feature_turn % 2] or halves[0]
        feature_turn += 1
        table = MOTION_EFFECTS if section.energy_level >= HIGH_ENERGY_THRESHOLD else BED_EFFECTS
        for turn, row in enumerate(lit, start=index):
            choices = table.get(cast.categories[row["name"]], table["other"])
            plan.append(_placement(row["name"], 0, choices[turn % len(choices)], start, end, palette))

        if role == "accents":
            lit_props = set().union(*(cast.leaves[row["name"]] for row in lit))
            pool = [p for p in cast.accent_pool if p not in lit_props] or cast.accent_pool
            for downbeat in analysis.beats.downbeat_times:
                if pool and section.start_time <= downbeat < section.end_time:
                    kick = nearest_kick(kick_times, downbeat)
                    at = to_frame((downbeat if kick is None else kick) * 1000)
                    if at >= song_end:
                        continue
                    plan.append(_placement(pool[accent_turn % len(pool)], 0, "On_solid", at, at + ACCENT_MS, palette))
                    accent_turn += 1
    return plan


def _try_extract_lyrics(mp3_path: Path):
    """Try to extract lyrics using Whisper. Returns None if unavailable."""
    try:
        from xlights_mcp.audio.lyrics import extract_lyrics
        return extract_lyrics(mp3_path, whisper_model="base")
    except ImportError:
        logger.info("Whisper not installed — skipping lyric extraction")
        return None
    except Exception as e:
        logger.warning(f"Lyric extraction failed: {e}")
        return None


def _try_extract_vocal_tracks(mp3_path: Path) -> list:
    """Try to extract all vocal timing tracks. Returns empty list if unavailable."""
    try:
        from xlights_mcp.audio.lyrics import extract_vocal_tracks
        tracks = extract_vocal_tracks(mp3_path, whisper_model="base")
        return [t for t in tracks if t.available and t.phonemes]
    except ImportError:
        logger.info("Whisper not installed — skipping vocal track extraction")
        # Fall back to single-track extraction
        track = _try_extract_lyrics(mp3_path)
        if track and track.available and track.phonemes:
            return [track]
        return []
    except Exception as e:
        logger.warning(f"Vocal track extraction failed: {e}")
        # Fall back to single-track extraction
        track = _try_extract_lyrics(mp3_path)
        if track and track.available and track.phonemes:
            return [track]
        return []
