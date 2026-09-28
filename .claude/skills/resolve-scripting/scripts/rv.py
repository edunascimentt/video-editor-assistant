"""Robust connection to a running DaVinci Resolve, for ad-hoc scripts.

Import this at the top of every one-off script instead of calling
`dvr.scriptapp("Resolve")` directly:

    import sys; sys.path.insert(0, "<skill>/scripts")
    import rv
    resolve, pm, project = rv.app(project="MY PROJECT", folder="Clients")
    tl = rv.timeline(project, "EP 03")
    ...
    rv.save(pm)

Why it exists — three silent failures of the scripting API, all measured:

1. `scriptapp("Resolve")` returns None mid-session while Resolve is alive and
   well, and `GetTimelineByIndex(i)` returns None for valid indices. It is
   transient (seconds). Without a retry the script dies with
   `'NoneType' object has no attribute 'GetProjectManager'` — or worse, dies
   half-way through a rebuild.
2. The current project can change under the script (the editor opens another
   one while you work). Every write must be preceded by a name check.
3. `ProjectManager.LoadProject(name)` only sees the CURRENT database folder and
   returns None (not an error) when the project lives in a subfolder. After a
   fresh launch Resolve sits on "Untitled Project" at the root.
"""
from __future__ import annotations

import os
import sys
import time

_MAC_API = "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting"
_MAC_LIB = "/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so"
_WIN_API = os.path.expandvars(r"%PROGRAMDATA%\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting")
_WIN_LIB = r"C:\Program Files\Blackmagic Design\DaVinci Resolve\fusionscript.dll"
_LNX_API = "/opt/resolve/Developer/Scripting"
_LNX_LIB = "/opt/resolve/libs/Fusion/fusionscript.so"


def bootstrap() -> None:
    """Export RESOLVE_SCRIPT_API / RESOLVE_SCRIPT_LIB and put Modules on sys.path."""
    if sys.platform == "darwin":
        api, lib = _MAC_API, _MAC_LIB
    elif sys.platform.startswith("win"):
        api, lib = _WIN_API, _WIN_LIB
    else:
        api, lib = _LNX_API, _LNX_LIB
    os.environ.setdefault("RESOLVE_SCRIPT_API", api)
    os.environ.setdefault("RESOLVE_SCRIPT_LIB", lib)
    mods = os.path.join(os.environ["RESOLVE_SCRIPT_API"], "Modules")
    if mods not in sys.path:
        sys.path.append(mods)


def _log(msg: str) -> None:
    print(f"[rv] {msg}", file=sys.stderr, flush=True)


def app(project: str | None = None, folder: str | None = None,
        tries: int = 60, wait: float = 5.0):
    """Return (resolve, project_manager, project), retrying until Resolve answers.

    With `project`, make sure that project is the current one (opening
    `folder` first if given) and refuse to return anything else.
    """
    bootstrap()
    import DaVinciResolveScript as dvr  # noqa: E402  (needs bootstrap first)

    last = None
    for n in range(tries):
        try:
            r = dvr.scriptapp("Resolve")
            pm = r.GetProjectManager() if r else None
            p = pm.GetCurrentProject() if pm else None
            if p is not None:
                if project:
                    p = ensure_project(pm, project, folder)
                return r, pm, p
        except Exception as e:  # the remote objects raise odd things when half-up
            last = e
        if n == 0:
            _log("Resolve not answering yet; retrying"
                 f" up to {tries}x every {wait:.0f}s")
        time.sleep(wait)
    raise RuntimeError(f"Resolve did not answer after {tries} tries ({last!r}). "
                       "Is it running, with scripting set to Local?")


def ensure_project(pm, name: str, folder: str | None = None):
    """Make `name` the current project or raise. Never silently continue."""
    p = pm.GetCurrentProject()
    if p and p.GetName() == name:
        return p
    _log(f"current project is {p.GetName() if p else None!r}; loading {name!r}")
    if folder:
        pm.GotoRootFolder()
        for part in folder.strip("/").split("/"):
            if not pm.OpenFolder(part):
                raise RuntimeError(f"database folder {part!r} not found (path {folder!r})")
    p = pm.LoadProject(name)
    if not p:
        raise RuntimeError(
            f"LoadProject({name!r}) returned None. LoadProject only sees the current "
            "database folder — pass folder='<subfolder>' if the project is not at the root.")
    return p


def assert_project(pm, name: str):
    """Call right before every write: the editor may have switched projects."""
    p = pm.GetCurrentProject()
    got = p.GetName() if p else None
    if got != name:
        raise RuntimeError(f"project changed under the script: expected {name!r}, got {got!r}")
    return p


def timeline(project, name: str, tries: int = 10, wait: float = 3.0):
    """Find a timeline by name, retrying over transient None indices."""
    for _ in range(tries):
        count = project.GetTimelineCount() or 0
        seen_none = False
        for i in range(1, count + 1):
            tl = project.GetTimelineByIndex(i)
            if tl is None:
                seen_none = True
                continue
            if tl.GetName() == name:
                return tl
        if not seen_none and count:
            break
        time.sleep(wait)
    raise LookupError(f"timeline {name!r} not found")


def set_current(project, tl) -> None:
    if not project.SetCurrentTimeline(tl):
        raise RuntimeError(f"SetCurrentTimeline({tl.GetName()!r}) failed")


def track_items(tl, kind: str = "video", index: int = 1) -> list:
    """Items on one track, never None."""
    return list(tl.GetItemListInTrack(kind, index) or [])


def describe(tl) -> list[dict]:
    """Snapshot of every item on every track — take one before writing anywhere."""
    out = []
    for kind in ("video", "audio", "subtitle"):
        for t in range(1, (tl.GetTrackCount(kind) or 0) + 1):
            for it in track_items(tl, kind, t):
                out.append({"kind": kind, "track": t, "name": it.GetName(),
                            "start": it.GetStart(), "end": it.GetEnd()})
    return out


def find_clip(folder, name: str):
    """Depth-first search of a media-pool folder for a clip by name."""
    for c in folder.GetClipList() or []:
        if c.GetName() == name:
            return c
    for sub in folder.GetSubFolderList() or []:
        hit = find_clip(sub, name)
        if hit:
            return hit
    return None


def save(pm) -> bool:
    """`ProjectManager.SaveProject()` — `Project.SaveProject` does not exist."""
    ok = bool(pm.SaveProject())
    _log("project saved" if ok else "SaveProject returned False")
    return ok


if __name__ == "__main__":
    r, pm, p = app(tries=3, wait=2)
    tl = p.GetCurrentTimeline()
    print(f"project: {p.GetName()}")
    print(f"timeline: {tl.GetName() if tl else None}"
          f" @ {p.GetSetting('timelineFrameRate')} fps")
