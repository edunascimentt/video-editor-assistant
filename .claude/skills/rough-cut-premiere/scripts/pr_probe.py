#!/usr/bin/env python
"""Dump a Premiere sequence's structure to <workdir>/timeline.json.

Premiere is not read through the bridge one clip at a time. The sequence is
exported once as FCP7 XML — `export_as_fcp_xml{output_path}` in the Premiere MCP,
or File > Export > Final Cut Pro XML by hand — and everything the pipeline needs
is read out of that single file: track layout, record positions, source ranges,
media paths, rates, markers.

That export is also the input to `pr_apply.py`, so it is copied into the work
directory next to the plan. Re-exporting after editing the sequence and re-running
this script is the supported way to pick up changes; a plan built against a stale
export would cut at the wrong frames.

usage: pr_probe.py --fcpxml FILE [--sequence NAME] [--project NAME] [--work DIR]
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pr_common as rc  # noqa: E402
import pr_xmeml as X  # noqa: E402


def probe(fcpxml: str, sequence_name=None, project_name=None, work_root=None):
    tree = X.load(fcpxml)
    root = tree.getroot()
    seq = X.pick_sequence(root, sequence_name)
    files = X.FileTable(root)

    seq_fps = X.fps_of(seq)
    if not seq_fps:
        raise SystemExit("The sequence has no readable <rate>. Re-export the XML.")

    items, warnings = [], []
    for media_type, track_index, track in X.tracks(seq):
        for item_index, elem in enumerate(X.timeline_items(track)):
            where = f"{media_type} {track_index} item {item_index}"
            if elem.tag == "transitionitem":
                warnings.append(
                    f"{where} is a transition — transitions are dropped from the cut; "
                    "re-apply them after the import.")
                continue
            row = X.describe(elem, media_type, track_index, item_index, seq_fps, files)
            if row["start"] is None or row["end"] is None or row["start"] < 0:
                warnings.append(
                    f"{where} ({row['name']}) has no record position (it lives inside a "
                    "transition) — it will be carried through UNCUT.")
                continue
            if not row["file_path"]:
                warnings.append(
                    f"{where} ({row['name']}) has no media file (title, graphic, colour "
                    "matte or nested sequence) — it will be carried through UNCUT.")
            elif row["retimed"]:
                warnings.append(
                    f"{where} ({row['name']}) is retimed (speed={row['speed']}) — it is cut "
                    "at the same record frames as everything else, but no word timing is "
                    "read from it.")
            if row["has_timeremap"]:
                warnings.append(
                    f"{where} ({row['name']}) carries a Time Remapping filter — its "
                    "keyframes do not survive being split. Check it after the import.")
            if not row["enabled"]:
                warnings.append(
                    f"{where} ({row['name']}) is disabled — it is cut with the rest but "
                    "contributes no words.")
            items.append(row)

    ends = [i["end"] for i in items if i["end"] is not None]
    payload = {
        "nle": "premiere",
        "source_xml": str(Path(fcpxml).resolve()),
        "project": project_name or X.text(root.find("project"), "name") or "premiere",
        "timeline": X.text(seq, "name") or "sequence",
        "timeline_fps": seq_fps,
        # Record frames in FCP7 XML are 0-based from the head of the sequence,
        # whatever start timecode the sequence displays. The display timecode
        # rides along in the XML and is preserved by the rewrite.
        "timeline_start_frame": 0,
        "timeline_end_frame": int(X.number(seq, "duration") or (max(ends) if ends else 0)),
        "track_counts": {
            "video": sum(1 for t, _, _ in X.tracks(seq) if t == "video"),
            "audio": sum(1 for t, _, _ in X.tracks(seq) if t == "audio"),
            "subtitle": 0,
        },
        "items": items,
        "warnings": warnings,
    }

    out = rc.workdir(payload["project"], payload["timeline"], work_root)
    kept = out / "source.xml"
    if Path(fcpxml).resolve() != kept.resolve():
        shutil.copyfile(fcpxml, kept)
    payload["source_xml"] = str(kept)
    rc.write_json(out / "timeline.json", payload)
    return payload, out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fcpxml", required=True,
                    help="the XML written by export_as_fcp_xml")
    ap.add_argument("--sequence", help="sequence name (needed only if the XML holds several)")
    ap.add_argument("--project", help="project name, used only to name the work directory")
    ap.add_argument("--work", help="work root (default: $ROUGHCUT_WORK or ~/.cache/rough-cut)")
    args = ap.parse_args()

    payload, out = probe(args.fcpxml, args.sequence, args.project, args.work)
    fps = payload["timeline_fps"]
    duration = payload["timeline_end_frame"] / fps
    print(f"project : {payload['project']}")
    print(f"sequence: {payload['timeline']}  {fps:g} fps  {rc.hms(duration)}  "
          f"({len(payload['items'])} items)")
    for kind, count in payload["track_counts"].items():
        print(f"  {kind:9s}: {count} track(s)")
    files = sorted({i["file_path"] for i in payload["items"] if i.get("file_path")})
    print(f"source files: {len(files)}")
    for path in files:
        exists = "" if Path(path).exists() else "   [MISSING]"
        print(f"  {path}{exists}")
    for warning in payload["warnings"]:
        print(f"WARNING: {warning}")
    print(f"\nwrote {out / 'timeline.json'}")
    print(f"work dir: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
