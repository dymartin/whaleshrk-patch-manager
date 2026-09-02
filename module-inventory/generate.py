from __future__ import annotations

import html
import io
import json
import re
import struct
import sys
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from system.rig.catalog.discovery import live_httpx_client
from system.rig.catalog.patchstorage import discover_union_items, fetch_detail, list_patches

MODULE_INVENTORY = ROOT / "module-inventory"
CACHE = MODULE_INVENTORY / ".cache"
CATALOG = ROOT / "system/data/catalog.json"
ORGANELLE_PLATFORM = 154
STOP = set("a an and are as at audio based be by can designed do does effect effects for from in into is it its module of on or patch pd that the this to tool using with your".split())
ALIASES = {
    "delays": "delay", "echoes": "delay", "echo": "delay", "reverbs": "reverb",
    "synthesizer": "synth", "synthesis": "synth", "sequencing": "sequencer",
    "sequences": "sequencer", "samplers": "sampler", "sampling": "sampler",
    "looping": "looper", "loops": "looper", "filters": "filter",
    "distortion": "distort", "distorted": "distort", "compressor": "compress",
    "granulation": "granular", "granulator": "granular", "arpeggio": "arpeggiator",
}
CAPABILITIES = (
    "additive synth", "fm synth", "subtractive synth", "wavetable synth", "physical modeling",
    "granular sampler", "sample slicer", "sample player", "drum machine", "drum synth",
    "step sequencer", "euclidean sequencer", "midi sequencer", "arpeggiator", "looper",
    "tape delay", "stereo delay", "ping pong delay", "delay", "plate reverb", "reverb",
    "chorus", "flanger", "phaser", "tremolo", "vibrato", "ring modulator", "bit crusher",
    "distort", "compress", "limiter", "equalizer", "filter", "vocoder", "pitch shifter",
    "envelope follower", "midi controller", "midi monitor", "metronome", "tuner",
)


def cached(name: str, loader):
    path = CACHE / name
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    value = loader()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")
    return value


def plain(value: object, limit: int = 260) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", str(value or "")))
    text = re.sub(r"\s+", " ", text).strip(" -\n\r\t")
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def names(items: object) -> list[str]:
    return [plain(x.get("name") or x.get("slug")) for x in (items or []) if isinstance(x, dict)]


def words(text: str) -> set[str]:
    found = set()
    for word in re.findall(r"[a-z0-9]+", text.lower()):
        word = ALIASES.get(word, word)
        if len(word) > 2 and word not in STOP:
            found.add(word)
    return found


def capabilities(text: str) -> set[str]:
    normalized = " ".join(ALIASES.get(w, w) for w in re.findall(r"[a-z0-9]+", text.lower()))
    found = {cap for cap in CAPABILITIES if cap in normalized}
    return {cap for cap in found if not any(cap != longer and cap in longer for longer in found)}


def item_text(item: dict) -> str:
    return " ".join([
        plain(item.get("title") or item.get("display")), plain(item.get("excerpt")),
        " ".join(names(item.get("categories"))), " ".join(names(item.get("tags"))),
        str(item.get("category", "")), " ".join(item.get("param_labels", [])),
    ])


def logline(item: dict) -> str:
    excerpt = plain(item.get("excerpt"))
    if excerpt:
        return excerpt
    cats = names(item.get("categories")) or [str(item.get("category", "module")).replace("/", " / ")]
    params = item.get("param_labels", [])[:5]
    detail = f" Controls: {', '.join(params)}." if params else ""
    return f"{plain(item.get('title') or item.get('display'))} is a {' / '.join(cats)} patch.{detail}"


def md_inventory(title: str, intro: str, items: list[dict]) -> str:
    lines = [f"# {title}", "", intro, "", f"Total: **{len(items)}**.", ""]
    for item in items:
        source = item.get("url")
        label = f"[{item['title']}]({source})" if source else item["title"]
        meta = []
        if item.get("key"): meta.append(f"`{item['key']}`")
        if item.get("state"): meta.append(item["state"])
        if item.get("category"): meta.append(item["category"])
        lines += [f"## {label}", "", " · ".join(meta), "", logline(item), ""]
    return "\n".join(lines)


def similarity(a: dict, b: dict) -> tuple[float, str]:
    at, bt = words(item_text(a)), words(item_text(b))
    title_a = re.sub(r"[^a-z0-9]", "", str(a.get("title", "")).lower())
    title_b = re.sub(r"[^a-z0-9]", "", str(b.get("title", "")).lower())
    if title_a and title_a == title_b:
        return 1.0, "same normalized title"
    shared = at & bt
    score = len(shared) / len(at | bt) if at | bt else 0
    ac, bc = capabilities(item_text(a)), capabilities(item_text(b))
    # Conservative: capability alone is insufficient unless the patch is generic.
    if ac and ac == bc:
        score = max(score, 0.76)
    return score, f"shared terms: {', '.join(sorted(shared)[:8])}" if shared else ""


def best_match(item: dict, baseline: list[dict]) -> tuple[dict | None, float, str]:
    ranked = [(similarity(item, other), other) for other in baseline]
    (score, reason), other = max(ranked, key=lambda row: row[0][0])
    shared = words(item_text(item)) & words(item_text(other))
    duplicate = score == 1 or (score >= 0.55 and len(shared) >= 2) or score >= 0.72
    return (other if duplicate else None), score, reason


def archive_scan(data: bytes) -> dict:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
        files = [n for n in archive.namelist() if not n.endswith("/") and "__MACOSX" not in n]
    except (zipfile.BadZipFile, OSError) as exc:
        return {"verdict": "INCOMPATIBLE", "evidence": f"unreadable archive: {exc}"}
    pd_names = [n for n in files if n.lower().endswith(".pd")]
    mains = [n for n in pd_names if Path(n).name.lower() == "main.pd"]
    if not mains:
        return {"verdict": "INCOMPATIBLE", "evidence": "archive has no main.pd entry point"}
    text = "\n".join(archive.read(n).decode("utf-8", "replace") for n in pd_names if archive.getinfo(n).file_size < 4_000_000)
    lower = text.lower()
    wrong_elf = []
    for name in files:
        if name.lower().endswith((".pd_linux", ".so")):
            blob = archive.read(name)[:52]
            if blob[:4] == b"\x7fELF" and len(blob) >= 40:
                endian = "<" if blob[5] == 1 else ">"
                machine = struct.unpack(endian + "H", blob[18:20])[0]
                flags = struct.unpack(endian + "I", blob[36:40])[0]
                if machine != 40 or not flags & 0x400:
                    wrong_elf.append(name)
    canonical_controls = bool(re.search(r"\br (knob[1-4]|notes|aux|fs)\b", lower))
    audio = "dac~" in lower or "throw~ outl" in lower or "throw~ outr" in lower
    custom_mother = any(Path(n).name.lower() == "mother.pd" for n in pd_names)
    dynamic = any(x in lower for x in ("pd-$", r"pd-\$", "dynamicpatch", "iemguts", "canvasobjectposition"))
    device = any(x in lower for x in ("shell ", "comport", "/dev/", "netsend", "netreceive", "tcpclient", "system "))
    absolute = bool(re.search(r"(?:/home/|/root/|/tmp/|/usbdrive/|[a-z]:[/\\])", lower))
    scripts = any(Path(n).suffix.lower() in {".sh", ".py", ".lua"} or Path(n).name in {"pd-opts.txt", "install.txt"} for n in files)
    if custom_mother:
        verdict, why = "INCOMPATIBLE", "bundles/replaces mother.pd; it is a standalone runtime"
    elif wrong_elf or dynamic or device:
        flags = (["non-Organelle native binary"] if wrong_elf else []) + (["dynamic Pd patching"] if dynamic else []) + (["shell/device/network dependency"] if device else [])
        verdict, why = "REJECTED", ", ".join(flags)
    elif absolute or scripts or not canonical_controls:
        flags = (["absolute paths"] if absolute else []) + (["scripts/options"] if scripts else []) + (["noncanonical controls"] if not canonical_controls else [])
        verdict, why = "EXPANDED", ", ".join(flags) + "; requires a broader wrapper/rewriter"
    elif audio:
        verdict, why = "CONFIRMED", "canonical Organelle controls and audio entry point; no static blockers found"
    else:
        verdict, why = "PROBABLE", "canonical controls and no static blockers; audio routing needs a small deterministic wrapper"
    return {"verdict": verdict, "evidence": why, "main": mains[0], "pd_files": len(pd_names)}


def fetch_and_scan(patch_id: int) -> dict:
    with live_httpx_client() as client:
        detail = None
        for attempt in range(8):
            response = client.get(f"https://patchstorage.com/api/beta/patches/{patch_id}")
            if response.status_code != 429:
                response.raise_for_status()
                detail = response.json()
                break
            time.sleep(min(60, int(response.headers.get("Retry-After", "5")) + attempt * 3))
        if detail is None:
            raise RuntimeError("Patchstorage rate limit did not clear after retries")
        files = detail.get("files") or []
        if not files:
            return {"verdict": "INCOMPATIBLE", "evidence": "Patchstorage exposes no downloadable archive"}
        if int(files[0].get("filesize") or 0) > 80_000_000:
            return {"verdict": "REJECTED", "evidence": "archive exceeds the 80 MB practical scan limit"}
        for attempt in range(5):
            response = client.get(files[0]["url"])
            if response.status_code != 429:
                response.raise_for_status()
                break
            time.sleep(min(60, int(response.headers.get("Retry-After", "5")) + attempt * 3))
        else:
            raise RuntimeError("archive rate limit did not clear after retries")
        if len(response.content) > 80_000_000:
            return {"verdict": "REJECTED", "evidence": "archive exceeds the 80 MB practical scan limit"}
        return archive_scan(response.content)


def main() -> None:
    for name in ("ORHACK", "ORAC", "ORGANELLE", "SUITE"):
        (MODULE_INVENTORY / name).mkdir(parents=True, exist_ok=True)
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    with live_httpx_client() as client:
        print("Fetching Patchstorage inventories…")
        orac_uploads = cached("orac.json", lambda: discover_union_items(client))
        organelle = cached("organelle.json", lambda: list_patches(client, platform=ORGANELLE_PLATFORM))
        orhack_upload = cached("orhack.json", lambda: fetch_detail(client, 162128))
    upload_by_slug = {x["slug"]: x for x in orac_uploads}

    def catalog_item(entry: dict) -> dict:
        upload = upload_by_slug.get(entry["source"], {})
        return {
            "title": entry["display"], "display": entry["display"], "key": entry["key"],
            "category": entry["category"], "tags": entry.get("tags", []),
            "param_labels": [p.get("label", p.get("name", "")) for p in entry.get("params", [])],
            "excerpt": upload.get("excerpt", ""), "url": upload.get("url"), "source": entry["source"],
        }

    native = sorted((catalog_item(x) for x in catalog if x["source"] == "orhack"), key=lambda x: x["key"])
    for item in native:
        item["url"] = orhack_upload.get("url")
        item["excerpt"] = ""  # Patchstorage has one distribution description, not per-module prose.
    orac = sorted((catalog_item(x) for x in catalog if x["source"] != "orhack"), key=lambda x: x["key"])
    organs = []
    for x in sorted(organelle, key=lambda row: row["id"]):
        organs.append({
            **x, "title": plain(x.get("title")), "excerpt": plain(x.get("excerpt")),
            "state": plain((x.get("state") or {}).get("name")),
        })

    (MODULE_INVENTORY / "ORHACK/modules.md").write_text(md_inventory("Native ORHACK modules", "Per-module prose is inferred from the native catalog metadata because Patchstorage describes ORHACK as one distribution, not 65 individual uploads.", native), encoding="utf-8")
    (MODULE_INVENTORY / "ORAC/modules.md").write_text(md_inventory("Vendored ORAC modules", "Only accepted modules currently present in the generated catalog are included; descriptions use their Patchstorage upload excerpts.", orac), encoding="utf-8")
    (MODULE_INVENTORY / "ORGANELLE/patches.md").write_text(md_inventory("Patchstorage Organelle patches", "Complete live platform listing, including non-ready and incompatible uploads. Descriptions are Patchstorage excerpts.", organs), encoding="utf-8")
    for path, value in (("ORHACK/modules.json", native), ("ORAC/modules.json", orac), ("ORGANELLE/patches.json", organs)):
        (MODULE_INVENTORY / path).write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")

    overlap = []
    for item in orac:
        match, score, reason = best_match(item, native)
        if match:
            overlap.append((item, match, score, reason))
    lines = ["# Native ORHACK / vendored ORAC functional overlap", "", "Conservative lexical/capability matches; review borderline matches before treating them as interchangeable.", "", f"Matches: **{len(overlap)}**.", ""]
    for item, match, score, reason in overlap:
        lines.append(f"- **{item['title']}** ↔ **{match['title']}** ({score:.0%}; {reason})")
    (MODULE_INVENTORY / "SUITE/overlap.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    baseline = native + orac
    gaps = []
    duplicates = []
    for item in organs:
        match, score, reason = best_match(item, baseline)
        if match:
            duplicates.append({"patch": item["id"], "match": match["key"], "score": score, "reason": reason})
        else:
            gaps.append(item)
    (MODULE_INVENTORY / "SUITE/omitted-duplicates.json").write_text(json.dumps(duplicates, indent=2), encoding="utf-8")

    scan_cache = cached("scans.json", lambda: {})
    # Transport errors are not compatibility verdicts; retry them on every run.
    missing = [x for x in gaps if str(x["id"]) not in scan_cache or "download/scan failed:" in scan_cache[str(x["id"])]["evidence"]]
    print(f"Scanning {len(missing)} new gap archives ({len(gaps)} gaps total)…")
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {pool.submit(fetch_and_scan, x["id"]): x for x in missing}
        done = 0
        for future in as_completed(futures):
            item = futures[future]
            try:
                scan_cache[str(item["id"])] = future.result()
            except Exception as exc:
                scan_cache[str(item["id"])] = {"verdict": "REJECTED", "evidence": f"download/scan failed: {plain(exc)}"}
            done += 1
            print(f"\rScanned {done}/{len(missing)}", end="", flush=True)
    if missing: print()
    (CACHE / "scans.json").write_text(json.dumps(scan_cache, indent=2), encoding="utf-8")

    counts = {v: 0 for v in ("CONFIRMED", "PROBABLE", "EXPANDED", "REJECTED", "INCOMPATIBLE")}
    for item in gaps:
        counts[scan_cache[str(item["id"])]["verdict"]] += 1
    suite = [
        "# Organelle gap suite", "",
        "This contains Patchstorage Organelle uploads for which the conservative metadata matcher found no functionally identical native ORHACK or accepted ORAC module.", "",
        "> Verdicts are reproducible static-analysis estimates, not hardware certification. CONFIRMED means the archive has canonical Organelle control/audio conventions and no detected blocker; PROBABLE needs only a small routing wrapper; EXPANDED needs a broader deterministic rewriter; REJECTED has impractical dynamic/native/external dependencies; INCOMPATIBLE is not a usable module-shaped archive.", "",
        f"Inventory: **{len(organs)}** Organelle uploads; **{len(duplicates)}** omitted functional matches; **{len(gaps)}** gap candidates.", "",
        "Verdicts: " + ", ".join(f"**{name} {count}**" for name, count in counts.items()) + ".", "",
    ]
    for verdict in counts:
        suite += [f"## {verdict}", ""]
        for item in gaps:
            scan = scan_cache[str(item["id"])]
            if scan["verdict"] != verdict: continue
            cats = ", ".join(names(item.get("categories"))) or "Uncategorized"
            suite += [f"### [{item['title']}]({item['url']})", "", f"Patchstorage #{item['id']} · {item['state']} · {cats}", "", logline(item), "", f"**Conversion evidence:** {scan['evidence']}.", ""]
    (MODULE_INVENTORY / "SUITE/suite.md").write_text("\n".join(suite), encoding="utf-8")
    print(f"Done: {len(native)} ORHACK, {len(orac)} ORAC, {len(organs)} Organelle; {len(gaps)} suite gaps.")


if __name__ == "__main__":
    main()
