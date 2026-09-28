"""Read and edit a DaVinci Resolve .drt (timeline export) as text.

A .drt is a zip: project.xml, MediaPool/.../MpFolder.xml and one
SeqContainer/<uuid>.xml holding the timeline. Tracks live under
<VideoTrackVec>/<AudioTrackVec>/<SubtitleTrackVec>, each <Sm2TiTrack> has
<Items> with one <Element><Sm2Ti...Clip DbId="..."> per item.

This edits the XML as TEXT, on purpose: the file carries hex blobs, empty
elements and formatting that a DOM round-trip would rewrite, and Resolve's
importer is not a forgiving parser. Every operation here is a slice-and-splice
on the original string.

    import drtlib
    d = drtlib.Drt.load("in.drt")
    for tr in d.tracks("video"):
        for el in d.items(tr):
            print(tr.index, drtlib.info(el))
    src = d.items(d.tracks("video")[2])[0]          # the title whose TEXT you want
    new = drtlib.clone(src, start=1298, duration=490)
    d.insert(d.tracks("video")[2], new)
    d.save("out.drt")                                  # then import it as a new timeline

Cloning preserves the Text+ text and the whole comp (they live in the
zstd blobs FieldsBlob / EffectFiltersBA), so clone the item whose text you
want. <MediaTimemapBA> and <MediaStartTime> are per-file constants and do
not change when <In> changes.
"""
from __future__ import annotations

import re
import sys
import uuid
import zipfile
from dataclasses import dataclass

_UUID = re.compile(r'DbId="[0-9a-fA-F-]{36}"')
# clips are Sm2TiVideoClip / Sm2TiAudioClip; subtitles and titles are Sm2TiGenerator
_CLIP = re.compile(r"<(Sm2Ti(?!Track)\w+)\s+DbId=")
_VEC = {"video": "VideoTrackVec", "audio": "AudioTrackVec", "subtitle": "SubtitleTrackVec"}


def _balanced(text: str, start: int, tag: str) -> int:
    """Index just past the </tag> that closes the <tag ...> opening at `start`."""
    pat = re.compile(rf"<{tag}(\s[^>]*)?(/?)>|</{tag}>")
    depth = 0
    for m in pat.finditer(text, start):
        if m.group(0).startswith("</"):
            depth -= 1
            if depth == 0:
                return m.end()
        elif m.group(2) == "/":            # <tag/> — self-closed, no depth change
            if depth == 0:
                return m.end()
        else:
            depth += 1
    raise ValueError(f"unbalanced <{tag}> at {start}")


@dataclass
class Track:
    kind: str
    index: int          # 1-based, as Resolve numbers them
    start: int          # span of the <Sm2TiTrack> element in Drt.text
    end: int


class Drt:
    def __init__(self, members: dict[str, bytes], seq_name: str):
        self.members = members
        self.seq_name = seq_name
        self.text = members[seq_name].decode("utf-8")

    @classmethod
    def load(cls, path: str) -> "Drt":
        with zipfile.ZipFile(path) as z:
            members = {n: z.read(n) for n in z.namelist()}
        seqs = [n for n in members if n.startswith("SeqContainer/") and n.endswith(".xml")]
        if len(seqs) != 1:
            raise ValueError(f"expected one SeqContainer xml, found {seqs}")
        return cls(members, seqs[0])

    def save(self, path: str) -> None:
        self.members[self.seq_name] = self.text.encode("utf-8")
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            for n, b in self.members.items():
                z.writestr(n, b)

    def tracks(self, kind: str = "video") -> list[Track]:
        vec = _VEC[kind]
        a = self.text.find(f"<{vec}>")
        if a < 0:
            return []
        b = _balanced(self.text, a, vec)
        out, pos = [], a
        while True:
            m = re.compile(r"<Sm2TiTrack\s").search(self.text, pos, b)
            if not m:
                break
            e = _balanced(self.text, m.start(), "Sm2TiTrack")
            out.append(Track(kind, len(out) + 1, m.start(), e))
            pos = e
        return out

    def _items_span(self, tr: Track) -> tuple[int, int]:
        a = self.text.find("<Items", tr.start, tr.end)
        if a < 0:
            raise ValueError(f"{tr.kind} {tr.index}: no <Items>")
        if self.text.startswith("<Items/>", a):
            return a, a + len("<Items/>")
        return a, _balanced(self.text, a, "Items")

    def items(self, tr: Track) -> list[str]:
        """The <Element>...</Element> blocks of one track, in file order."""
        a, b = self._items_span(tr)
        out, pos = [], a + len("<Items>")
        while True:
            s = self.text.find("<Element>", pos, b)
            if s < 0:
                break
            e = _balanced(self.text, s, "Element")
            out.append(self.text[s:e])
            pos = e
        return out

    def insert(self, tr: Track, element: str) -> None:
        """Append an element at the end of a track's <Items>. Re-fetch tracks after."""
        a, b = self._items_span(tr)
        if self.text.startswith("<Items/>", a):
            self.text = self.text[:a] + "<Items>\n" + element + "\n</Items>" + self.text[b:]
        else:
            close = self.text.rfind("</Items>", a, b)
            self.text = self.text[:close] + element + "\n" + self.text[close:]

    def remove(self, element: str) -> None:
        i = self.text.find(element)
        if i < 0:
            raise ValueError("element not found")
        self.text = self.text[:i] + self.text[i + len(element):]


def _field(el: str, name: str) -> str | None:
    m = re.search(rf"<{name}>(.*?)</{name}>", el, re.S)
    return m.group(1) if m else None


def info(el: str) -> dict:
    """The fields that matter: kind, name, record start, duration, source in (exact)."""
    kind = _CLIP.search(el)

    def num(n):
        v = _field(el, n)
        return int(v) if v not in (None, "") and v.lstrip("-").isdigit() else None

    return {"kind": kind.group(1) if kind else None, "name": _field(el, "Name"),
            "start": num("Start"), "duration": num("Duration"), "in": num("In"),
            "linked": _field(el, "LinkedItemSync") or None}


def _set(el: str, name: str, value: int) -> str:
    new, n = re.subn(rf"<{name}>-?\d+</{name}>", f"<{name}>{value}</{name}>", el, count=1)
    if n != 1:
        raise ValueError(f"<{name}> not found in element")
    return new


def clone(el: str, start: int | None = None, duration: int | None = None,
          in_: int | None = None) -> str:
    """Copy an element with fresh DbIds (all of them, thumbnail included).

    A clone keeps the original's <LinkedItemSync>; clear or re-pair it yourself
    if the clone must not be linked to the source's audio.
    """
    out = _UUID.sub(lambda _m: f'DbId="{uuid.uuid4()}"', el)
    if start is not None:
        out = _set(out, "Start", start)
    if duration is not None:
        out = _set(out, "Duration", duration)
    if in_ is not None:
        out = _set(out, "In", in_)
    return out


def signature(d: Drt) -> list[tuple]:
    """(kind, track, start, end, name) for every item — compare before/after a round trip."""
    sig = []
    for kind in _VEC:
        for tr in d.tracks(kind):
            for el in d.items(tr):
                i = info(el)
                end = (i["start"] or 0) + (i["duration"] or 0)
                sig.append((kind, tr.index, i["start"], end, i["name"]))
    return sig


if __name__ == "__main__":
    d = Drt.load(sys.argv[1])
    for kind in _VEC:
        for tr in d.tracks(kind):
            els = d.items(tr)
            print(f"{kind[0].upper()}{tr.index}: {len(els)} items")
            for el in els[: int(sys.argv[2]) if len(sys.argv) > 2 else 3]:
                print("   ", info(el))
