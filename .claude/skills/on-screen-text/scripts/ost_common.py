"""Shared helpers for the on-screen-text pass.

Dependency-light on purpose: stdlib plus DaVinciResolveScript. No numpy, no
ffmpeg -- this pass never touches audio, it only reads a transcript somebody
else already produced and writes titles and markers into a timeline.

Coordinate systems
------------------
timeline frames   position on the TIMELINE, counted in the TIMELINE's fps.
                  Markers, record frames and clip durations all live here.
                  Frame 0 is the first frame of the timeline even when the
                  timeline's start timecode is 01:00:00:00.
source frames     position inside a media pool item, counted in THAT ITEM's own
                  fps -- which for these Fusion templates is not the timeline's.
                  Only AppendToTimeline's startFrame/endFrame live here, and
                  endFrame is EXCLUSIVE.
transcript sec    seconds from the head of the timeline, as WhisperX reported
                  them for the cut audio. frame = round(sec * timeline_fps).

The fps mismatch between the two frame spaces is the single trap in this whole
pass; `source_range_for` is the only place allowed to know about it.
"""

from __future__ import annotations

import json
import os
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ── Resolve bootstrap ────────────────────────────────────────────────────────

RESOLVE_MCP = Path(os.environ.get(
    "OST_RESOLVE_MCP", str(Path.home() / "Repositories/davinci-resolve-mcp")))
_SCRIPT_API = ("/Library/Application Support/Blackmagic Design/"
               "DaVinci Resolve/Developer/Scripting")


def connect_resolve():
    """Return the Resolve app object, or raise with a diagnosable message."""
    modules = os.environ.get("RESOLVE_SCRIPT_API", _SCRIPT_API) + "/Modules"
    if modules not in sys.path:
        sys.path.append(modules)
    try:
        import DaVinciResolveScript as dvr  # type: ignore
    except ImportError as exc:  # pragma: no cover - environment problem
        raise SystemExit(
            f"DaVinciResolveScript not importable ({exc}).\n"
            f"Run this script with {RESOLVE_MCP}/venv/bin/python and the "
            "RESOLVE_SCRIPT_API / RESOLVE_SCRIPT_LIB / PYTHONPATH env from "
            ".mcp.json."
        ) from exc
    resolve = dvr.scriptapp("Resolve")
    if resolve is None:
        raise SystemExit(
            "scriptapp('Resolve') returned None. Resolve is not running, or "
            "Preferences > General > External scripting using is not 'Local'."
        )
    return resolve


def current_project(resolve):
    proj = resolve.GetProjectManager().GetCurrentProject()
    if proj is None:
        raise SystemExit("No project open in Resolve.")
    return proj


def find_timeline(proj, name: Optional[str]):
    if not name:
        tl = proj.GetCurrentTimeline()
        if tl is None:
            raise SystemExit(
                "No current timeline. Open one, or pass --timeline NAME.")
        return tl
    for i in range(1, int(proj.GetTimelineCount() or 0) + 1):
        tl = proj.GetTimelineByIndex(i)
        if tl and tl.GetName() == name:
            return tl
    raise SystemExit(f"Timeline not found: {name!r}")


def timeline_fps(tl) -> float:
    """The TIMELINE's own rate. Never read this off the project."""
    raw = tl.GetSetting("timelineFrameRate")
    try:
        return float(raw)
    except (TypeError, ValueError):
        raise SystemExit(
            f"Timeline frame rate unreadable ({raw!r}). Refusing to guess -- "
            "every duration in this pass is derived from it.")


# ── work directory ───────────────────────────────────────────────────────────

def slug(text: str) -> str:
    s = re.sub(r"[^\w.-]+", "-", str(text).strip()).strip("-")
    return s[:80] or "untitled"


def workdir(project: str, timeline: str, root: Optional[str] = None) -> Path:
    base = Path(root or os.environ.get(
        "OST_WORK", str(Path.home() / ".cache/on-screen-text")))
    d = base / slug(project) / slug(timeline)
    d.mkdir(parents=True, exist_ok=True)
    return d


def roughcut_dir(project: str, timeline: str) -> Path:
    """Where the rough-cut skill parks its cache for the same timeline."""
    base = Path(os.environ.get(
        "ROUGHCUT_WORK", str(Path.home() / ".cache/rough-cut")))
    return base / slug(project) / slug(timeline)


def read_json(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def write_json(path: Path, payload: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    tmp.replace(path)
    return path


# ── media pool ───────────────────────────────────────────────────────────────

def folder_by_path(media_pool, path: str):
    """Resolve a "Master/Sub/Sub" path to a folder object, or None."""
    parts = [p for p in str(path).split("/") if p]
    node = media_pool.GetRootFolder()
    if node is None:
        return None
    if parts and parts[0] in ("Master", node.GetName()):
        parts = parts[1:]
    for part in parts:
        nxt = None
        for sub in (node.GetSubFolderList() or []):
            if sub.GetName() == part:
                nxt = sub
                break
        if nxt is None:
            return None
        node = nxt
    return node


def clip_props(clip, keys: List[str]) -> Dict[str, Any]:
    out = {}
    for k in keys:
        try:
            out[k] = clip.GetClipProperty(k)
        except Exception:
            out[k] = None
    return out


def describe_clip(clip) -> Dict[str, Any]:
    p = clip_props(clip, ["Clip Name", "Type", "Frames", "FPS", "Resolution"])
    frames = p.get("Frames")
    try:
        frames = int(frames)
    except (TypeError, ValueError):
        frames = None
    try:
        fps = float(p.get("FPS"))
    except (TypeError, ValueError):
        fps = None
    return {
        "id": clip.GetUniqueId(),
        "name": p.get("Clip Name") or clip.GetName(),
        "type": p.get("Type"),
        "frames": frames,
        "fps": fps,
        "resolution": p.get("Resolution"),
    }


def clip_by_id(media_pool, clip_id: str):
    """Depth-first hunt for a media pool item by unique id."""
    def walk(folder):
        for c in (folder.GetClipList() or []):
            if c.GetUniqueId() == clip_id:
                return c
        for sub in (folder.GetSubFolderList() or []):
            hit = walk(sub)
            if hit is not None:
                return hit
        return None
    return walk(media_pool.GetRootFolder())


# ── the fps trap ─────────────────────────────────────────────────────────────

def source_range_for(duration_frames: int, template_fps: float,
                     tl_fps: float, available: Optional[int] = None,
                     stretchable: bool = False
                     ) -> Tuple[int, int, List[str]]:
    """Source in/out that yields `duration_frames` TIMELINE frames.

    AppendToTimeline counts startFrame/endFrame in the MEDIA's own rate. A
    60 fps Fusion Title dropped on a 24 fps timeline with endFrame=104 lands as
    41 frames, not 105 -- the generator is 1.75 s long either way. So scale.

    Generators and titles stretch past their nominal length, so `available` is
    never enforced -- but for real media an overshoot means a frozen tail, and
    that is worth a warning.
    """
    warnings: List[str] = []
    if not template_fps or not tl_fps:
        raise SystemExit("source_range_for needs both fps values.")
    end = int(round(duration_frames * (template_fps / tl_fps)))
    if end <= 0:
        raise SystemExit(f"duration {duration_frames} collapses to 0 source frames.")
    if available and end > available and not stretchable:
        warnings.append(
            f"asking {end} source frames from media that only has {available} "
            "-- the tail will freeze")
    return 0, end, warnings


# ── text sizing ──────────────────────────────────────────────────────────────

# ── word layout, measured off AULA 01 ───────────────────────────────────
#
# The word does NOT sit where the Text+ template puts it. Its Fusion Center is
# 0.5,0.5 (dead centre) on every instance; the move to screen-left is done on
# the EDIT page, in the timeline item's own Transform. Those two numbers are
# identical across every word in the lesson, so they are the defaults here:
WORD_PAN = -514.0
WORD_TILT = 130.0

# Final size is Fusion `Size` x the item's Transform `Zoom`, and the reference edit tunes both
# by eye -- PROCESSAMENTO 0.0874x0.924, PLANEJAR 0.2166x0.46, EXEMPLO
# 0.2343x0.54. The effective scales those land on (0.081 / 0.100 / 0.127) do
# not follow a rule, so this is a starting point, not the answer: put the whole
# size in `Size`, leave Zoom at 1, and normalise for width off EXEMPLO.
REF_SIZE = 0.1265
REF_LEN = 7
MIN_SIZE = 0.05

# ── the click ───────────────────────────────────────────────────────────────
#
# Every word (and every slide print) is announced by `Burnin Click.mp4` on A2,
# starting TWO frames before the visual. 10 source frames @30fps = 8 frames on
# a 24 fps timeline.
CLICK_LEAD = 2
CLICK_DUR = 8
CLICK_TRACK = 2


def autosize(text: str, ref_size: float = REF_SIZE,
             ref_len: int = REF_LEN, min_size: float = MIN_SIZE) -> float:
    """Keep the rendered word roughly one screen-width wide.

    A width estimate, not a measurement -- Text+ has no auto-fit and this
    script cannot read a render. Always eyeball the result in the viewer.
    """
    longest = max((len(line) for line in str(text).split("\n")), default=1)
    longest = max(longest, 1)
    return round(max(min_size, min(ref_size, ref_size * ref_len / longest)), 4)


# ── the 60 fps trap that freezes the animation ───────────────────────────────
#
# The `Text+` word template in the media pool is a **60 fps** Fusion Title. On a
# 60 fps timeline (AULA ANTIGA) it animates as authored. On a 24 fps timeline Resolve
# conforms it and the StyledTextFollower NEVER ADVANCES -- the word is simply on,
# full opacity, from its first frame to its last. Comp, splines and Follower
# settings are byte-identical in both cases; only the container rate differs.
# The 24 fps explanation card on the same timeline animates fine, which is the
# control that proves it.
#
# `SetClipProperty("FPS", ...)` is refused, so the fix is to stop using that
# container: place a **24 fps Fusion Composition** and import the word comp into
# it with `TimelineItem.ImportFusionComp`. Verified on screen, not inferred.
WORD_COMP = Path(__file__).resolve().parent.parent / "assets/word-follower.comp"

# NEVER call TimelineItem.SetName() on an item that carries a Fusion comp.
# Renaming FREEZES the comp: the StyledTextFollower stops advancing and the word
# renders at full opacity from its first frame to its last. Verified by A/B on
# one clip -- animating before the rename, static after, nothing else touched.
# This is why the words looked unanimated for three rounds: the culprit was the
# cosmetic rename added for timeline navigability, not the template, not the
# fps, not the clip length. Identify placed items by id (applied.json), not by
# a name you wrote.


# ── word fade-out ────────────────────────────────────────────────────────────
#
# The Text+ template animates on a 171-frame canvas: every Follower spline keys
# at 0 / 30 / 150 / 170, so a 104-frame clip ends in the middle of the HOLD and
# the word is cut off with no out at all.
#
# Retiming those splines to the clip fixes it on paper and looks wrong on
# screen -- that was rejected outright. What is wanted is the template's animation
# left exactly as authored, plus a plain fade at the end.
#
# A fade IS available here -- additive, a spline on the Template's `Alpha1`
# (shading element 1 alpha) that multiplies over whatever the Follower is doing
# and touches no authored keyframe -- but it is OFF by default, because he
# looked at both and chose the raw template. Turn it on per item with
# `"fade_out": 20` when someone asks for it.
#
# It has to happen at the comp, not the Edit page: TimelineItem has no working
# keyframe API on this build (`add_keyframe` raises 'NoneType' object is not
# callable), so clip opacity cannot be ramped from a script.
FADE_OUT = 0


def fade_out_word(comp, n: int, frames: int = FADE_OUT) -> bool:
    """Ramp Template.Alpha1 from 1 to 0 over the last `frames` of an n-frame clip."""
    tool = comp.FindTool("Template")
    if tool is None or int(frames) <= 0:
        return False
    frames = max(2, min(int(frames), n - 2))
    start_f, end_f = float(n - 1 - frames), float(n - 1)
    comp.SetActiveTool(tool)
    tool.Alpha1 = comp.BezierSpline({})
    spline = tool.Alpha1.GetConnectedOutput().GetTool()
    spline.SetKeyFrames({start_f: {1: 1.0}, end_f: {1: 0.0}}, True)
    return abs(float(tool.GetInput("Alpha1", end_f) or 1.0)) < 1e-6


# ── misc ─────────────────────────────────────────────────────────────────────

def norm_word(s: str) -> str:
    s = unicodedata.normalize("NFD", str(s).lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]", "", s)


def timecode(frame: int, fps: float) -> str:
    total = int(frame)
    f = total % max(1, int(round(fps)))
    total //= max(1, int(round(fps)))
    s, m, h = total % 60, (total // 60) % 60, total // 3600
    return f"{h:02d}:{m:02d}:{s:02d}:{f:02d}"


MARKER_COLORS = [
    "Blue", "Cyan", "Green", "Yellow", "Red", "Pink", "Purple", "Fuchsia",
    "Rose", "Lavender", "Sky", "Mint", "Lemon", "Sand", "Cocoa", "Cream",
]

# Namespaced customData, so --clear can tell this pass's annotations from the
# rough-cut skill's leftovers (which carry no custom data at all).
NS = "ost"
KINDS = {
    "slide": ("Blue", f"{NS}:slide"),
    "word": ("Green", f"{NS}:word"),
    "term": ("Yellow", f"{NS}:term"),
    "review": ("Pink", f"{NS}:review"),
}

ITEM_PREFIX = {"word": "PALAVRA · ", "explain": "EXPL · "}
