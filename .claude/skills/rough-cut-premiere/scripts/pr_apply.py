#!/usr/bin/env python
"""Rewrite the exported sequence XML as the cut sequence, for import into Premiere.

Premiere's scripting surface cannot build this edit. `split_clip` and
`ripple_delete` exist, but they run through the QE DOM — undocumented, version-
dependent, and one bridge round trip per operation. A 300-cut pass would be 600
mutating calls against a project that is already open, with no atomic point and
no way back if the twohundredth fails. The interchange route replaces all of it
with one file and one `import_fcp_xml`.

The rewrite is a razor, expressed as arithmetic:

  * every clipitem is split at the keep-range boundaries, and each fragment gets
    its own `<start>` / `<end>` (record) and `<in>` / `<out>` (source);
  * the source range is derived from the ORIGINAL clipitem's own record-to-source
    ratio, so a clip that was already conformed or retimed keeps its speed
    instead of being silently normalised to 1x;
  * items with no source range — titles, graphics, colour mattes, transitions —
    cannot be split. One that sits entirely inside kept audio is carried across
    and shifted; one that a removal falls inside is dropped and named, because
    moving it would put it somewhere the editor did not choose.

The original sequence is never modified: this writes a NEW file with a NEW
sequence uuid, and Premiere imports it alongside what is already there.

usage: pr_apply.py --work-dir DIR [--name NAME] [--out FILE] [--dry-run]
"""

from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pr_common as rc  # noqa: E402
import pr_xmeml as X  # noqa: E402


# ── keep ranges in frames ────────────────────────────────────────────────────

class Remap:
    """Record frames of the original sequence -> record frames of the cut one."""

    def __init__(self, keep_seconds: List[Tuple[float, float]], fps: float):
        self.fps = fps
        self.ranges: List[Tuple[int, int, int]] = []      # (from, to, new start)
        cursor = 0
        for a, b in keep_seconds:
            fa, fb = int(round(a * fps)), int(round(b * fps))
            if fb <= fa:
                continue
            self.ranges.append((fa, fb, cursor))
            cursor += fb - fa
        self.total = cursor

    def clip(self, start: int, end: int):
        """Yield (keep index, new start, old from, old to) for each intersection."""
        for index, (fa, fb, new) in enumerate(self.ranges):
            lo, hi = max(start, fa), min(end, fb)
            if hi - lo >= 1:
                yield index, new + (lo - fa), lo, hi

    def point(self, frame: int) -> Optional[int]:
        for fa, fb, new in self.ranges:
            if fa <= frame < fb:
                return new + (frame - fa)
        return None

    def edge(self, frame: int) -> Optional[int]:
        """A frame that fell in removed audio but sits on a splice lands on the join."""
        for fa, fb, new in self.ranges:
            if frame == fb:
                return new + (fb - fa)
        return None

    def intact(self, start: int, end: int) -> bool:
        """True when [start, end) survives whole inside one keep range."""
        return any(fa <= start and end <= fb for fa, fb, _ in self.ranges)


# ── link groups ──────────────────────────────────────────────────────────────

def original_link_groups(seq: ET.Element) -> Dict[str, str]:
    """clipitem id -> group key, from the sequence's own `<link>` elements."""
    parent: Dict[str, str] = {}

    def find(node: str) -> str:
        while parent.get(node, node) != node:
            parent[node] = parent.get(parent[node], parent[node])
            node = parent[node]
        return node

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for item in seq.iter("clipitem"):
        item_id = item.get("id")
        if not item_id:
            continue
        parent.setdefault(item_id, item_id)
        for link in item.findall("link"):
            ref = X.text(link, "linkclipref")
            if ref:
                parent.setdefault(ref, ref)
                union(item_id, ref)
    return {node: find(node) for node in parent}


# ── the rewrite ──────────────────────────────────────────────────────────────

def rebuild(tree: ET.ElementTree, timeline: Dict[str, Any], plan: Dict[str, Any],
            name: str) -> Tuple[ET.ElementTree, Dict[str, Any]]:
    root = tree.getroot()
    seq = X.pick_sequence(root, timeline["timeline"])
    files = X.FileTable(root)
    fps = float(timeline["timeline_fps"])
    remap = Remap([(float(a), float(b)) for a, b in plan["keep"]], fps)
    if not remap.ranges:
        raise SystemExit("Cut plan keeps nothing — refusing.")

    groups = original_link_groups(seq)
    new_groups: Dict[str, List[Tuple[str, str, int]]] = {}
    warnings: List[str] = []
    stats = {"fragments": 0, "cut_items": 0, "carried": 0, "dropped": 0}

    for media_type, track_index, track in X.tracks(seq):
        rebuilt: List[ET.Element] = []
        dropped_here = 0
        for elem in X.timeline_items(track):
            label = (f"{media_type} {track_index} "
                     f"'{X.text(elem, 'name') or elem.tag}'")
            start = X.number(elem, "start")
            end = X.number(elem, "end")
            if start is None or end is None or start < 0 or end <= start:
                warnings.append(f"DROPPED {label}: no usable record position "
                                "(an item inside a transition). Re-place it by hand.")
                stats["dropped"] += 1
                dropped_here += 1
                continue
            start, end = int(start), int(end)

            src_in = X.number(elem, "in")
            src_out = X.number(elem, "out")
            splittable = (elem.tag == "clipitem" and src_in is not None
                          and src_out is not None and src_out > src_in)

            if not splittable:
                # A title, graphic, matte or transition. It has no source range
                # to cut, so it is only safe to move it wholesale.
                if remap.intact(start, end):
                    new_start = remap.point(start)
                    rebuilt.append(X.carry(elem, new_start, new_start + (end - start)))
                    stats["carried"] += 1
                    warnings.append(f"CARRIED {label} across the cut unsplit "
                                    f"(moved {(start - new_start) / fps:.2f}s earlier).")
                else:
                    warnings.append(
                        f"DROPPED {label}: a removal falls inside it and it has no source "
                        "range to cut. Re-place it by hand after the import.")
                    stats["dropped"] += 1
                    dropped_here += 1
                continue

            src_in, src_out = int(src_in), int(src_out)
            src_fps = X.fps_of(elem) or X.fps_of(files.resolve(elem.find("file"))) or fps
            ratio = (src_out - src_in) / float(end - start)
            file_elem = files.resolve(elem.find("file"))
            file_frames = X.number(file_elem, "duration") if file_elem is not None else None

            produced = 0
            for index, new_start, lo, hi in remap.clip(start, end):
                frag_in = src_in + int(round((lo - start) * ratio))
                frag_out = frag_in + max(1, int(round((hi - lo) * ratio)))
                if file_frames is not None and frag_out > file_frames:
                    frag_out = int(file_frames)
                if frag_out <= frag_in:
                    warnings.append(
                        f"DROPPED one fragment of {label} at "
                        f"{rc.hms(lo / fps)}: it lands past the end of the media.")
                    stats["dropped"] += 1
                    dropped_here += 1
                    continue
                frag_id = f"{elem.get('id') or 'clipitem'}-rc{index}"
                frag = X.fragment(elem, frag_id, new_start, new_start + (hi - lo),
                                  frag_in, frag_out, src_fps)
                rebuilt.append(frag)
                key = f"{groups.get(elem.get('id'), elem.get('id'))}#{index}"
                new_groups.setdefault(key, []).append((frag_id, media_type, track_index))
                produced += 1
            stats["fragments"] += produced
            if produced:
                stats["cut_items"] += 1
            else:
                warnings.append(f"DROPPED {label}: every frame of it was removed.")
                stats["dropped"] += 1
                dropped_here += 1

        X.replace_items(track, rebuilt)

        # Overlaps inside one track are always a defect, never a style choice.
        # Gaps are reported only where this run dropped something: a track that
        # simply had a hole in the original still has one, and warning about
        # that would bury the holes the cut actually opened.
        spans = [(int(X.number(i, "start") or 0), int(X.number(i, "end") or 0))
                 for i in X.timeline_items(track)]
        gaps: List[Tuple[int, int]] = []
        for (_, a1), (b0, _) in zip(spans, spans[1:]):
            if b0 < a1:
                warnings.append(
                    f"OVERLAP on {media_type} {track_index} at frame {b0} — do not trust "
                    "this result; re-run the plan.")
                break
            if b0 > a1:
                gaps.append((a1, b0 - a1))
        if spans and spans[0][0] > 0:
            gaps.insert(0, (0, spans[0][0]))
        if gaps and dropped_here:
            total = sum(length for _, length in gaps)
            warnings.append(
                f"{len(gaps)} gap(s) on {media_type} {track_index} totalling {total} frame(s) "
                f"({total / fps:.2f}s) after {dropped_here} dropped item(s). First at "
                f"{rc.hms(gaps[0][0] / fps)}.")

    markers = remap_markers(seq, remap, fps)
    collapsed = X.normalise_file_refs(root)
    linked = X.rebuild_links(seq, new_groups)
    X.set_text(seq, "duration", str(remap.total))
    X.fresh_sequence_identity(seq, name)

    report = {
        "name": name,
        "keep_ranges": len(remap.ranges),
        "result_frames": remap.total,
        "result_seconds": remap.total / fps,
        "source_seconds": float(timeline["timeline_end_frame"]) / fps,
        "markers_remapped": markers["moved"],
        "markers_dropped": markers["lost"],
        "links_rebuilt": linked,
        "file_defs_collapsed": collapsed,
        "warnings": warnings,
        **stats,
    }
    return tree, report


def remap_markers(seq: ET.Element, remap: Remap, fps: float) -> Dict[str, Any]:
    """Re-time the sequence's markers into the cut; report the ones that sat in
    removed audio rather than silently relocating them."""
    moved, lost = 0, []
    for marker in list(seq.findall("marker")):
        start = X.number(marker, "in")
        if start is None:
            continue
        at = int(start)
        new = remap.point(at)
        if new is None:
            new = remap.edge(at)
        if new is None:
            lost.append({"at": round(at / fps, 3), "name": X.text(marker, "name") or ""})
            seq.remove(marker)
            continue
        end = X.number(marker, "out")
        X.set_text(marker, "in", str(new))
        if end is not None and end >= 0:
            span = max(0, int(end) - at)
            X.set_text(marker, "out", str(new + span))
        moved += 1
    return {"moved": moved, "lost": lost}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work-dir", required=True)
    ap.add_argument("--name", help="name for the cut sequence (default '<sequence> ROUGH')")
    ap.add_argument("--out", help="output XML path (default <work-dir>/cut.xml)")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the numbers and the warnings, write nothing")
    args = ap.parse_args()

    work = Path(args.work_dir)
    timeline = rc.read_json(work / "timeline.json")
    plan = rc.read_json(work / "cutplan.json")
    source = Path(timeline.get("source_xml") or (work / "source.xml"))
    if not source.exists():
        raise SystemExit(f"Sequence export missing: {source}. Re-run pr_probe.py.")

    name = args.name or f"{timeline['timeline']} ROUGH"
    tree, report = rebuild(X.load(source), timeline, plan, name)

    fps = float(timeline["timeline_fps"])
    print(f"{report['keep_ranges']} keep ranges -> {report['fragments']} clip fragments "
          f"from {report['cut_items']} items")
    print(f"result {rc.hms(report['result_seconds'])} "
          f"(from {rc.hms(report['source_seconds'])})")
    print(f"markers: {report['markers_remapped']} re-timed"
          + (f", {len(report['markers_dropped'])} sat in removed audio and were dropped"
             if report["markers_dropped"] else ""))
    print(f"links rebuilt: {report['links_rebuilt']} fragment group(s)")
    for warning in report["warnings"]:
        print(f"WARNING: {warning}")

    if args.dry_run:
        print("\ndry run — nothing written")
        return 0

    out = Path(args.out or (work / "cut.xml"))
    X.write(tree, out)
    report["path"] = str(out)
    rc.write_json(work / "applied.json", report)
    print(f"\nwrote {out}")
    print(f"import it with: import_fcp_xml {{\"path\": \"{out}\"}}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
