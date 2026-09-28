# Cloning timeline items through a `.drt`

The scripting API cannot copy a Fusion Title, a generator, or anything without
a media-pool item: `copy_clips`/`duplicate_clips` refuse with
`Timeline item has no MediaPoolItem`, `InsertFusionTitleIntoTimeline` only
accepts installed templates by name (a title pasted from another project
returns `None`), and `TimelineItem` has no `SetStart`/`SetDuration`. When an
editor says *"copy what I put on the other cut"* — intro, lower-third package,
finishing — this is the route. Recreating a similar Text+ is **not** an
answer: the template carries her animation, look and positioning.

## The format

`timeline(action="export", export_type="DRT")` (MCP) or
`timeline.Export(path, resolve.EXPORT_DRT)` writes a zip:

```
project.xml
MediaPool/Master/MpFolder.xml
SeqContainer/<uuid>.xml        ← the timeline
```

Inside the sequence: `<VideoTrackVec>`, `<AudioTrackVec>`, `<SubtitleTrackVec>`,
each a list of `<Sm2TiTrack>`; each track's `<Items>` holds one
`<Element><Sm2TiVideoClip|Sm2TiAudioClip|Sm2TiGenerator DbId="…">` per item.

| field | meaning |
|---|---|
| `<Start>` | record frame |
| `<Duration>` | length in timeline frames |
| `<In>` | source frame — **exact** (the API's `GetSourceStartFrame` was 1 low on 116 of 260 items measured) |
| `<LinkedItemSync>` | pairs video with its audio |
| `<MediaTimemapBA>`, `<MediaStartTime>` | constant per source file — leave alone when changing `<In>` |
| `FieldsBlob`, `EffectFiltersBA` | zstd blobs (magic `8128b52ffd`): Text+ text, the comp, clip gain |

## Clone

Copy the `<Element>` block, replace **every** `DbId` (the nested
`<BtThumnail>` has one too) with a fresh UUID, set `Start`/`Duration`/`In`,
insert before the track's `</Items>`, re-zip, import as a new timeline
(`import_timeline_checked` in the MCP, or `MediaPool.ImportTimelineFromFile`).

`scripts/drtlib.py` does all of it as text edits — tested on a 184-item
export: identity round-trip byte-equal, a clone lands with 0 duplicate ids and
exactly one new item in the signature.

```python
import drtlib
d = drtlib.Drt.load("export.drt")
before = drtlib.signature(d)
v3 = d.tracks("video")[2]
title = d.items(v3)[0]                     # clone the one whose TEXT you want
for f in (1298, 3704, 6498):
    d.insert(v3, drtlib.clone(title, start=f, duration=490))
    v3 = d.tracks("video")[2]              # spans move after each insert
d.save("with-titles.drt")
```

The import always creates a **new** timeline. Rename the old one to a backup
(`… · antes`) and give the new one the original name — `SetName` on a timeline
is safe (the freeze problem is only `SetName` on an *item* with a Fusion comp).
Compare `signature()` of the file you wrote against a fresh export of the
imported timeline: a full round trip of 315 items came back identical.

Offline media paths from another machine (`C:\Users\…`) survive the round trip
as they were; relink in the UI.
