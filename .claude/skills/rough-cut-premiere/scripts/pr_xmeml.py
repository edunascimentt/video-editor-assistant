"""FCP7 XML (xmeml v4) reading and rewriting — the Premiere side of the pipeline.

Premiere Pro has no scripting call that razors a clip and no call that appends a
source range at an explicit record frame, so the rough cut is not applied through
the API at all. It is applied as an *interchange* round trip:

    export_as_fcp_xml  ->  parse here  ->  plan  ->  rewrite here  ->  import_fcp_xml

That is the same route commercial silence-removers take, and it has two
properties the API route does not: every cut is frame-exact because it is
arithmetic on integers, and the whole edit lands in one atomic import instead of
several hundred bridge round trips through the undocumented QE DOM.

What the format says, and this module relies on
-----------------------------------------------
* `<start>` / `<end>` are RECORD frames in the sequence's own timebase, and
  `<end>` is EXCLUSIVE (duration = end - start).
* `<in>` / `<out>` are SOURCE frames in the clipitem's own `<rate>`, which is
  the media's rate and need not equal the sequence's. `<out>` is exclusive too.
* `<start>` is -1 on a clipitem that lives inside a transition rather than on
  the track proper. Those are not cuttable and are reported, never guessed at.
* NTSC rates are `timebase * 1000/1001`: `<timebase>30</timebase>` with
  `<ntsc>TRUE</ntsc>` is 29.97, and treating it as 30 drifts a frame every 33
  seconds — half a minute into a lesson the cuts no longer land on the words.
* A `<file>` is defined once, in document order, and referenced by
  `<file id="..."/>` after that. Repeating a full definition makes Premiere
  import the same media several times, so `normalise_file_refs` collapses them.
* Premiere additionally writes `<pproTicksIn>` / `<pproTicksOut>`, its own
  254016000000-ticks-per-second source positions. They are rewritten in step
  with `<in>` / `<out>`; a stale tick value next to a fresh frame value is the
  kind of inconsistency that produces a plausible, wrongly-timed sequence.
"""

from __future__ import annotations

import copy
import urllib.parse
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

PPRO_TICKS_PER_SECOND = 254016000000


# ── reading ──────────────────────────────────────────────────────────────────

def load(path: str | Path) -> ET.ElementTree:
    return ET.parse(str(path))


def sequences(root: ET.Element) -> List[ET.Element]:
    return list(root.iter("sequence"))


def pick_sequence(root: ET.Element, name: Optional[str] = None) -> ET.Element:
    found = sequences(root)
    if not found:
        raise SystemExit("No <sequence> in this XML. Export the ACTIVE sequence with "
                         "export_as_fcp_xml, not a project-wide XML.")
    if name:
        for seq in found:
            if text(seq, "name") == name:
                return seq
        raise SystemExit(f"Sequence {name!r} not in this XML. Present: "
                         + ", ".join(repr(text(s, 'name')) for s in found))
    if len(found) > 1:
        raise SystemExit("This XML holds several sequences; pass --sequence NAME. Present: "
                         + ", ".join(repr(text(s, 'name')) for s in found))
    return found[0]


def text(elem: Optional[ET.Element], tag: str, default: Optional[str] = None) -> Optional[str]:
    if elem is None:
        return default
    child = elem.find(tag)
    return default if child is None or child.text is None else child.text.strip()


def number(elem: Optional[ET.Element], tag: str, default: Optional[float] = None) -> Optional[float]:
    raw = text(elem, tag)
    try:
        return float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def fps_of(elem: Optional[ET.Element], default: Optional[float] = None) -> Optional[float]:
    """Frames per second from a `<rate>` child, honouring the NTSC pull-down."""
    if elem is None:
        return default
    rate = elem.find("rate")
    if rate is None:
        return default
    timebase = number(rate, "timebase")
    if not timebase:
        return default
    ntsc = (text(rate, "ntsc") or "").upper() in ("TRUE", "1")
    return timebase * 1000.0 / 1001.0 if ntsc else float(timebase)


def file_path_of(file_elem: Optional[ET.Element]) -> Optional[str]:
    """Local filesystem path from a `<pathurl>`, or None for a title/generator."""
    url = text(file_elem, "pathurl")
    if not url:
        return None
    parsed = urllib.parse.urlparse(url)
    path = urllib.parse.unquote(parsed.path)
    if parsed.netloc and parsed.netloc.lower() != "localhost":
        return f"//{parsed.netloc}{path}"          # UNC share
    # A local pathurl is written as file://localhost/... on both platforms, and
    # an exporter that keeps the path's own leading slash produces a doubled one.
    while path.startswith("//"):
        path = path[1:]
    # file://localhost/C:/... on Windows arrives as /C:/...
    if len(path) > 2 and path[0] == "/" and path[2] == ":":
        path = path[1:]
    return path


class FileTable:
    """Resolves `<file id="x"/>` back-references to the full definition."""

    def __init__(self, root: ET.Element):
        self.by_id: Dict[str, ET.Element] = {}
        for elem in root.iter("file"):
            fid = elem.get("id")
            if fid and (elem.find("pathurl") is not None or elem.find("name") is not None):
                self.by_id.setdefault(fid, elem)

    def resolve(self, file_elem: Optional[ET.Element]) -> Optional[ET.Element]:
        if file_elem is None:
            return None
        if file_elem.find("pathurl") is not None or file_elem.find("name") is not None:
            return file_elem
        return self.by_id.get(file_elem.get("id") or "")


def tracks(seq: ET.Element) -> Iterator[Tuple[str, int, ET.Element]]:
    """(media type, 1-based track index, track element) in document order."""
    media = seq.find("media")
    if media is None:
        return
    for media_type in ("video", "audio"):
        section = media.find(media_type)
        if section is None:
            continue
        for index, track in enumerate(section.findall("track"), start=1):
            yield media_type, index, track


def timeline_items(track: ET.Element) -> List[ET.Element]:
    return [child for child in track if child.tag in ("clipitem", "transitionitem")]


# ── describing one clipitem ──────────────────────────────────────────────────

def describe(item: ET.Element, media_type: str, track_index: int, item_index: int,
             seq_fps: float, files: FileTable) -> Dict[str, Any]:
    """One clipitem, flattened into the schema the analyser already speaks."""
    file_elem = files.resolve(item.find("file"))
    path = file_path_of(file_elem)
    src_fps = fps_of(item) or fps_of(file_elem) or seq_fps

    start = number(item, "start")
    end = number(item, "end")
    # A title, matte or generator carries <in>-1</in><out>-1</out>: it has no
    # source range at all, which is not the same as a range starting at zero.
    src_in = number(item, "in")
    src_out = number(item, "out")
    if src_in is None or src_in < 0 or src_out is None or src_out <= src_in:
        src_in = src_out = None

    row: Dict[str, Any] = {
        "xml_id": item.get("id"),
        "name": text(item, "name") or "(unnamed)",
        "track_type": media_type,
        "track_index": track_index,
        "item_index": item_index,
        "start": int(start) if start is not None else None,
        "end": int(end) if end is not None else None,
        "source_start": int(src_in) if src_in is not None else None,
        "source_end": int(src_out) if src_out is not None else None,
        "source_fps": src_fps,
        "file_path": path,
        "media_pool_item_id": (file_elem.get("id") if file_elem is not None else None),
        "master_clip_id": text(item, "masterclipid"),
        "enabled": (text(item, "enabled") or "TRUE").upper() != "FALSE",
    }
    row["source_start_seconds"] = None if src_in is None else src_in / src_fps
    row["source_end_seconds"] = None if src_out is None else src_out / src_fps

    # Speed: read from the record/source duration ratio rather than from the
    # timeremap filter, because a conformed frame rate produces the same
    # ratio and must be treated the same way by everything downstream.
    speed = None
    if None not in (start, end, src_in, src_out) and end > start:
        rec_seconds = (end - start) / seq_fps
        src_seconds = (src_out - src_in) / src_fps
        if rec_seconds > 0:
            speed = src_seconds / rec_seconds
    row["speed"] = None if speed is None else round(speed, 6)
    row["retimed"] = bool(speed is not None and abs(speed - 1.0) > 0.02)
    row["has_timeremap"] = any(
        (text(f.find("effect"), "effectid") or "").lower() == "timeremap"
        for f in item.findall("filter"))
    return row


# ── rewriting ────────────────────────────────────────────────────────────────

def set_text(parent: ET.Element, tag: str, value: str) -> None:
    child = parent.find(tag)
    if child is None:
        child = ET.SubElement(parent, tag)
    child.text = value


def retime_ppro_ticks(item: ET.Element, src_in: int, src_out: int, src_fps: float) -> None:
    """Keep Premiere's own tick positions in step with `<in>` / `<out>`."""
    for tag, frame in (("pproTicksIn", src_in), ("pproTicksOut", src_out)):
        if item.find(tag) is not None:
            set_text(item, tag, str(int(round(frame / src_fps * PPRO_TICKS_PER_SECOND))))


def fragment(item: ET.Element, new_id: str, rec_start: int, rec_end: int,
             src_in: int, src_out: int, src_fps: float) -> ET.Element:
    """A copy of `item` re-timed to one keep range. Filters and labels ride along."""
    clone = copy.deepcopy(item)
    clone.set("id", new_id)
    set_text(clone, "start", str(rec_start))
    set_text(clone, "end", str(rec_end))
    set_text(clone, "in", str(src_in))
    set_text(clone, "out", str(src_out))
    set_text(clone, "duration", str(max(1, src_out - src_in)))
    retime_ppro_ticks(clone, src_in, src_out, src_fps)
    for link in clone.findall("link"):          # rebuilt wholesale afterwards
        clone.remove(link)
    return clone


def carry(item: ET.Element, rec_start: int, rec_end: int) -> ET.Element:
    """A copy of `item` moved to a new record position, source range untouched.

    For a title, matte or generator, `<in>` / `<out>` are -1: there is no source
    range, and writing one turns a graphic into a clip with an invented media
    span. Only the record position may move.
    """
    clone = copy.deepcopy(item)
    clone.set("id", f"{item.get('id') or 'item'}-rc")
    set_text(clone, "start", str(rec_start))
    set_text(clone, "end", str(rec_end))
    for link in clone.findall("link"):
        clone.remove(link)
    return clone


def replace_items(track: ET.Element, items: List[ET.Element]) -> None:
    """Swap a track's clip/transition items, keeping `<enabled>` / `<locked>`."""
    tail = [child for child in track if child.tag not in ("clipitem", "transitionitem")]
    for child in list(track):
        track.remove(child)
    for child in items:
        track.append(child)
    for child in tail:
        track.append(child)


def normalise_file_refs(root: ET.Element) -> int:
    """Full `<file>` definition on first use, bare `<file id="..."/>` after that.

    Fragmenting deep-copies each clipitem, so without this every fragment carries
    a complete media definition and Premiere imports the same file once per
    fragment. Collapsed in document order, which is the order the format's
    back-references are defined against.
    """
    seen: set[str] = set()
    collapsed = 0
    for item in root.iter("clipitem"):
        file_elem = item.find("file")
        if file_elem is None:
            continue
        fid = file_elem.get("id")
        if not fid:
            continue
        if fid in seen:
            if len(file_elem):
                for child in list(file_elem):
                    file_elem.remove(child)
                collapsed += 1
        else:
            seen.add(fid)
    return collapsed


def rebuild_links(seq: ET.Element, groups: Dict[str, List[Tuple[str, str, int]]]) -> int:
    """Re-link the A/V members of each fragment.

    `groups` maps a group key to the (clipitem id, media type, track index) of
    every fragment in it. `<clipindex>` is the 1-based position of that fragment
    within its own track, so it is computed from the rebuilt tracks rather than
    carried over from the original — the original indexes stop being true the
    moment one clip becomes forty.
    """
    position: Dict[str, int] = {}
    for _, _, track in tracks(seq):
        for index, item in enumerate(timeline_items(track), start=1):
            if item.get("id"):
                position[item.get("id")] = index

    by_id: Dict[str, ET.Element] = {item.get("id"): item
                                    for item in seq.iter("clipitem") if item.get("id")}
    written = 0
    for members in groups.values():
        if len(members) < 2:
            continue
        for clip_id, _, _ in members:
            item = by_id.get(clip_id)
            if item is None:
                continue
            for member_id, media_type, track_index in members:
                link = ET.SubElement(item, "link")
                ET.SubElement(link, "linkclipref").text = member_id
                ET.SubElement(link, "mediatype").text = media_type
                ET.SubElement(link, "trackindex").text = str(track_index)
                ET.SubElement(link, "clipindex").text = str(position.get(member_id, 1))
            written += 1
    return written


def fresh_sequence_identity(seq: ET.Element, name: str) -> None:
    """A new name and a new UUID, so Premiere imports a sequence instead of
    matching the existing one and merging into it."""
    set_text(seq, "name", name)
    set_text(seq, "uuid", str(uuid.uuid4()))
    seq.set("id", f"sequence-{uuid.uuid4().hex[:8]}")


def write(tree: ET.ElementTree, path: str | Path) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "wb") as fh:
        fh.write(b'<?xml version="1.0" encoding="UTF-8"?>\n')
        fh.write(b'<!DOCTYPE xmeml>\n')
        tree.write(fh, encoding="utf-8", xml_declaration=False)
    return out
