r"""Freeze a pilot version: copy the code, templates and config that decide how it flies.

    python flightops/freeze.py v0 --from-zip baseline/original.zip --desc "pre-hackathon pilot"
    python flightops/freeze.py v1 --parent v0 --set gate_pilot.forward_pitch=0.33 --desc "..."
    python flightops/freeze.py --verify v0        # exit 1 if any frozen file changed
    python flightops/freeze.py --list

A version lives in versions/<name>/ as a complete, runnable copy (pilot/runner.py
runs from inside it). Evaluation flies that copy, so later edits to the workspace can't
change a frozen pilot, and nothing an evaluation does is written back to its code or config.
--set overrides are baked into the version's config.json; version.json records them, the
source, and a sha256 of every file. Freezing never overwrites an existing version.
"""
import argparse
import json
import shutil
import sys
import tempfile
import time
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from flightops.common import ROOT, VERSIONS, is_version_file, tree_hash, version_files  # noqa: E402


def _apply_overrides(cfg_path, overrides):
    from core import config as C
    cfg = C.apply_overrides(C.load(cfg_path), overrides)
    C.save(cfg, cfg_path)


def freeze(name, source_root, overrides=(), desc="", parent=None, source_label=None, versions=None):
    versions = versions or VERSIONS
    if not name.replace("_", "").replace("-", "").isalnum() or name == "workspace":
        raise SystemExit(f"bad version name {name!r}")
    dest = Path(versions) / name
    if dest.exists():
        raise SystemExit(f"{dest} exists; versions are never overwritten (pick a new name)")
    src = Path(source_root)
    files = version_files(src)
    if "config.json" not in files or "pilot/runner.py" not in files:
        raise SystemExit(f"{src} doesn't look like the drone folder (no config.json / pilot/runner.py)")
    tmp = Path(versions) / f".{name}.tmp"
    if tmp.exists():
        shutil.rmtree(tmp)
    for rel in files:
        out = tmp / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src / rel, out)
    for pkg in ("core", "pilot", "tools"):
        (tmp / pkg).mkdir(exist_ok=True)
    if overrides:
        _apply_overrides(tmp / "config.json", list(overrides))
    frozen = version_files(tmp)
    meta = {"name": name, "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "parent": parent,
            "description": desc, "source": source_label or str(src), "overrides": list(overrides),
            "tree_sha256": tree_hash(frozen), "files": frozen}
    (tmp / "version.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    tmp.rename(dest)
    return meta


def verify(name, versions=None):
    """[] if the frozen copy is intact, else a list of problems."""
    versions = versions or VERSIONS
    d = Path(versions) / name
    if not (d / "version.json").exists():
        return [f"no version {name!r} in {versions}"]
    meta = json.loads((d / "version.json").read_text(encoding="utf-8"))
    now = version_files(d)
    want = meta["files"]
    probs = [f"changed: {k}" for k in want if k in now and now[k] != want[k]]
    probs += [f"missing: {k}" for k in want if k not in now]
    probs += [f"added: {k}" for k in now if k not in want]
    return probs


def load_version(name, versions=None):
    versions = versions or VERSIONS
    return json.loads((Path(versions) / name / "version.json").read_text(encoding="utf-8"))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("name", nargs="?")
    p.add_argument("--from-zip", type=Path, help="freeze the contents of a snapshot zip")
    p.add_argument("--from-version", help="start from an existing frozen version")
    p.add_argument("--parent", help="recorded as the parent version (and the source, unless --from-* is given)")
    p.add_argument("--set", action="append", default=[], metavar="KEY=VALUE")
    p.add_argument("--desc", default="")
    p.add_argument("--verify", metavar="NAME")
    p.add_argument("--list", action="store_true")
    a = p.parse_args()
    if a.list:
        for d in sorted(VERSIONS.glob("*/version.json")):
            m = json.loads(d.read_text(encoding="utf-8"))
            bad = verify(m["name"])
            print(f"{m['name']:12} {m['created']}  {'OK ' if not bad else 'CHANGED'}  {m['description']}")
        return
    if a.verify:
        bad = verify(a.verify)
        print("intact" if not bad else "\n".join(bad))
        raise SystemExit(1 if bad else 0)
    if not a.name:
        p.error("name required")
    VERSIONS.mkdir(parents=True, exist_ok=True)
    if a.from_zip:
        with tempfile.TemporaryDirectory() as td:
            with zipfile.ZipFile(a.from_zip) as z:
                for info in z.infolist():
                    if is_version_file(info.filename):
                        z.extract(info, td)
            meta = freeze(a.name, td, a.set, a.desc, a.parent, source_label=f"zip:{a.from_zip.as_posix()}")
    else:
        base = a.from_version or a.parent
        src = VERSIONS / base if base else ROOT
        if base and verify(base):
            raise SystemExit(f"version {base} has changed since it was frozen; won't build on it")
        meta = freeze(a.name, src, a.set, a.desc, a.parent, source_label=f"version:{base}" if base else "workspace")
    print(f"froze {meta['name']}: {len(meta['files'])} files, tree {meta['tree_sha256'][:12]}")


if __name__ == "__main__":
    main()
