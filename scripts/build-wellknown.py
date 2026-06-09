#!/usr/bin/env python3
"""Generate the published .well-known/ discovery surface from source OOBIs.

This is a *reference* build script. The only thing standardized for consumers is
the published surface under .well-known/ that it emits; how you organize your
source is your business ("bring your own build-wellknown.py"). This repo keeps
hand-authored source OOBIs in repo-root buckets named by resource type:

    {aid,schema,witness}/<SAID>/index.json   (never served; see _config.yml)

and from them generates everything under .well-known/, which is 100% build
output -- do not hand-edit it:

1. .well-known/oobi/<SAID>/index.json  -- a flat, type-agnostic mirror (byte-exact
   copies) so a consumer can blindly GET /.well-known/oobi/<AID>/index.json and
   discover whether we publish anything for that identifier, without knowing its
   type. Copies are byte-exact because witness OOBIs are signed CESR streams;
   any change would invalidate their attached signatures.

2. .well-known/oobi/index.json  -- the discovery catalog: a generated inventory
   of every resource, enriched with metadata from the source files (schema
   titles/versions from the schema OOBIs, AID friendly names from
   aid/index.json). Generated, so it can never drift from the source.

3. .well-known/host-meta.json  -- the canonical entry point: an RFC 6415 JRD
   (Web Host Metadata). It describes only the *published* contract -- the flat
   /oobi/ lookup template + a link to the catalog -- not the source layout.

   We use host-meta's static templates rather than WebFinger because WebFinger
   needs a query endpoint, which static GitHub Pages cannot provide.

4. .well-known/index.html  -- a human landing page rendered from the same catalog.

GitHub Pages serves these as static files (Jekyll runs in safe mode, no custom
plugins), so the generated output must be committed. Re-run after any source
change:

    python3 scripts/build-wellknown.py [--host https://weboftrust.github.io]
"""

from __future__ import annotations

import argparse
import datetime
import html
import json
import shutil
import sys
from pathlib import Path

# Hand-authored source buckets (at repo root, never served). Each is a bucket of
# <SAID>/index.json source files; the bucket name is the resource type.
SOURCE_TYPES = ("aid", "schema", "witness")
RESOURCE = "index.json"
DEFAULT_HOST = "https://weboftrust.github.io"

# Curated facts carried into the generated catalog (no source file holds these).
ORGANIZATION = "Global Legal Entity Identifier Foundation (GLEIF)"
CONTACT = "https://www.gleif.org"

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE_ROOT = REPO_ROOT  # source buckets live at repo root: <type>/<SAID>/
WELL_KNOWN = REPO_ROOT / ".well-known"  # generated output (published) lives here
FLAT_DIR = WELL_KNOWN / "oobi"
# Legacy compatibility mirror at the repo root (/oobi/...). Older OOBI consumers
# still GET /oobi/<SAID>/index.json (the pre-.well-known contract); we keep that
# path alive as a byte-exact copy of FLAT_DIR. The canonical surface remains
# .well-known/; this is a generated duplicate, never hand-edited.
LEGACY_DIR = REPO_ROOT / "oobi"


def discover() -> tuple[dict[str, dict[str, str]], list[str]]:
    """Return (entries keyed by SAID, collision messages)."""
    entries: dict[str, dict[str, str]] = {}
    collisions: list[str] = []

    for kind in SOURCE_TYPES:
        bucket = SOURCE_ROOT / kind
        if not bucket.is_dir():
            continue
        for said_dir in sorted(p for p in bucket.iterdir() if p.is_dir()):
            said = said_dir.name
            resource = said_dir / RESOURCE
            if not resource.is_file():
                continue  # skip stray dirs without an index.json
            if said in entries:
                collisions.append(
                    f"{said}: present in both '{entries[said]['type']}' and '{kind}'"
                )
                continue
            entries[said] = {
                "type": kind,
                "source": str(resource.relative_to(REPO_ROOT)),
            }
    return entries, collisions


def load_aid_names() -> dict[str, str]:
    """Map AID SAID -> friendly name from the aid/index.json source listing."""
    listing = SOURCE_ROOT / "aid" / RESOURCE
    if not listing.is_file():
        return {}
    try:
        data = json.loads(listing.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
    return {said: name for name, said in data.get("aids", {}).items()}


def schema_meta(path: Path) -> dict[str, str]:
    """Pull title/credentialType/version out of a schema OOBI (a JSON Schema)."""
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}
    meta: dict[str, str] = {}
    for key in ("title", "credentialType", "version"):
        value = data.get(key)
        if value:
            meta[key] = value
    return meta


def build_catalog(entries: dict[str, dict[str, str]]) -> dict[str, dict]:
    """Rebuild the flat mirror + catalog; return resources grouped by type."""
    if FLAT_DIR.exists():
        shutil.rmtree(FLAT_DIR)
    FLAT_DIR.mkdir(parents=True)

    aid_names = load_aid_names()
    # Grouped by type: {kind: {SAID: entry}}. The group key carries the type, so
    # entries don't repeat it. "oobi" is kept last for readability.
    resources: dict[str, dict] = {kind: {} for kind in SOURCE_TYPES}
    for said, info in sorted(entries.items()):
        dest_dir = FLAT_DIR / said
        dest_dir.mkdir()
        shutil.copyfile(REPO_ROOT / info["source"], dest_dir / RESOURCE)

        kind = info["type"]
        if kind == "schema":
            entry = schema_meta(REPO_ROOT / info["source"])
        elif kind == "aid":
            entry = {"name": aid_names[said]} if said in aid_names else {}
        else:
            entry = {}
        entry["oobi"] = f"/.well-known/oobi/{said}/{RESOURCE}"
        resources[kind][said] = entry

    # Drop empty groups; keep SOURCE_TYPES order.
    resources = {kind: resources[kind] for kind in SOURCE_TYPES if resources[kind]}
    total = sum(len(group) for group in resources.values())

    catalog = {
        "name": "GLEIF OOBI Discovery Catalog",
        "description": (
            "Generated inventory of every published OOBI resource, grouped by "
            "type. GET /.well-known/oobi/<SAID>/index.json to resolve any one by "
            "SAID/AID without knowing its type. Discoverable via "
            "/.well-known/host-meta.json."
        ),
        "generator": "scripts/build-wellknown.py",
        "updated": datetime.date.today().isoformat(),
        "count": total,
        "organization": ORGANIZATION,
        "contact": CONTACT,
        "resources": resources,
    }
    (FLAT_DIR / RESOURCE).write_text(json.dumps(catalog, indent=2) + "\n")
    return resources


def mirror_legacy_oobi() -> None:
    """Copy the flat mirror to the repo-root /oobi/ for backward compatibility.

    Pre-.well-known consumers fetch /oobi/<SAID>/index.json directly; this keeps
    that path serving the same byte-exact OOBIs (signed CESR streams must not be
    altered). Regenerated from FLAT_DIR every build, so it can never drift.
    """
    if LEGACY_DIR.exists():
        shutil.rmtree(LEGACY_DIR)
    shutil.copytree(FLAT_DIR, LEGACY_DIR)


def build_host_meta(host: str) -> None:
    """Write an RFC 6415 JRD describing the published discovery surface.

    It advertises only the public contract -- the flat /oobi/ lookup template and
    the catalog -- not the source layout. Clients that want a specific type read
    the catalog's per-entry "type" field; there are no per-type URL namespaces.
    """
    host = host.rstrip("/")
    rels = f"{host}/rels"
    links = [
        {
            # Type-agnostic flat lookup; no advisory type because the target may
            # be a schema, an AID reply, or a witness CESR stream.
            "rel": f"{rels}/oobi",
            "template": f"{host}/.well-known/oobi/{{said}}/{RESOURCE}",
            "titles": {"en": "Type-agnostic OOBI lookup by SAID/AID"},
        },
        {
            "rel": f"{rels}/discovery-catalog",
            "type": "application/json",
            "href": f"{host}/.well-known/oobi/{RESOURCE}",
            "titles": {"en": "Generated discovery catalog (all OOBI resources)"},
        },
    ]
    jrd = {"subject": host, "links": links}
    (WELL_KNOWN / "host-meta.json").write_text(json.dumps(jrd, indent=2) + "\n")


SECTION_LABELS = {
    "aid": "GLEIF Identifiers (AIDs)",
    "schema": "vLEI Credential Schemas",
    "witness": "KERI Witnesses",
}
# How to label and order each resource within its section.
SECTION_SORT = {
    "aid": lambda item: item[1].get("name", item[0]).lower(),
    "schema": lambda item: item[1].get("title", item[0]).lower(),
    "witness": lambda item: item[0],
}

HTML_HEAD = """<!DOCTYPE html>
<!-- Generated by scripts/build-wellknown.py from the {aid,schema,witness}/ source tree. Do not edit by hand. -->
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="description" content="GLEIF .well-known discovery for KERI OOBIs and vLEI schemas">
  <title>GLEIF .well-known Discovery</title>
  <style>
    body { font-family: system-ui, sans-serif; max-width: 52rem; margin: 2rem auto; padding: 0 1rem; line-height: 1.5; }
    code { font-size: 0.85em; word-break: break-all; }
    .ver { color: #555; font-weight: normal; }
    .count { color: #888; font-weight: normal; font-size: 0.8em; }
    li { margin-bottom: 0.6rem; }
    footer { margin-top: 2rem; border-top: 1px solid #ddd; padding-top: 1rem; color: #555; font-size: 0.9em; }
  </style>
</head>
<body>
  <h1>GLEIF <code>.well-known</code> Discovery</h1>
  <p>Discovery resources for GLEIF's KERI (Key Event Receipt Infrastructure)
  identifiers and vLEI credential schemas.</p>
  <p><strong>Machine clients</strong> should start at
  <a href="/.well-known/host-meta.json">host-meta.json</a> (RFC 6415 link
  relations + lookup templates), or fetch the full
  <a href="/.well-known/oobi/index.json">discovery catalog</a>. To resolve a
  known identifier directly, GET
  <code>/.well-known/oobi/&lt;SAID&gt;/index.json</code>.</p>
"""


def _html_item(kind: str, said: str, entry: dict) -> str:
    if kind == "schema":
        heading = f"<strong>{html.escape(entry.get('title', said))}</strong>"
        version = entry.get("version")
        if version:
            heading += f' <span class="ver">v{html.escape(version)}</span>'
    elif kind == "aid":
        heading = f"<strong>{html.escape(entry.get('name', said))}</strong>"
    else:
        heading = "<strong>Witness</strong>"
    return (
        "      <li>\n"
        f"        {heading}<br>\n"
        f"        <code>{html.escape(said)}</code><br>\n"
        f'        <a href="{html.escape(entry["oobi"])}">OOBI</a>\n'
        "      </li>"
    )


def build_index_html(resources: dict[str, dict], present_types: list[str]) -> None:
    """Render the human landing page from the catalog (root-relative links)."""
    sections = []
    for kind in present_types:
        items = sorted(resources.get(kind, {}).items(), key=SECTION_SORT[kind])
        rows = "\n".join(_html_item(kind, said, entry) for said, entry in items)
        sections.append(
            f'  <section>\n    <h2>{html.escape(SECTION_LABELS.get(kind, kind))}'
            f' <span class="count">({len(items)})</span></h2>\n    <ul>\n'
            f"{rows}\n    </ul>\n  </section>"
        )

    footer = [
        "  <footer>",
        f"    <p>{html.escape(ORGANIZATION)} &middot; "
        f'<a href="{html.escape(CONTACT)}">{html.escape(CONTACT)}</a></p>',
    ]
    if (WELL_KNOWN / "external").is_dir():
        footer.append(
            '    <p>Federated discovery: see '
            '<a href="/.well-known/external/">external endpoints</a>.</p>'
        )
    footer.append(
        f"    <p>Generated {datetime.date.today().isoformat()} do not edit by hand.</p> "
    )
    footer.append("  </footer>")

    doc = HTML_HEAD + "\n".join(sections) + "\n" + "\n".join(footer) + "\n</body>\n</html>\n"
    (WELL_KNOWN / "index.html").write_text(doc)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help=f"Canonical origin for absolute URLs (default: {DEFAULT_HOST})",
    )
    args = parser.parse_args()

    entries, collisions = discover()
    if collisions:
        print("error: SAID collision across source buckets:", file=sys.stderr)
        for msg in collisions:
            print(f"  {msg}", file=sys.stderr)
        return 1
    if not entries:
        buckets = ", ".join(f"{t}/" for t in SOURCE_TYPES)
        print(f"error: no source OOBIs found under: {buckets}", file=sys.stderr)
        return 1

    resources = build_catalog(entries)
    mirror_legacy_oobi()

    present_types = [t for t in SOURCE_TYPES if resources.get(t)]
    by_type = {t: len(resources[t]) for t in present_types}

    build_host_meta(args.host)
    build_index_html(resources, present_types)

    total = sum(by_type.values())
    summary = ", ".join(f"{by_type[t]} {t}" for t in present_types)
    print(f"catalog + flat mirror: {total} OOBIs ({summary}) -> {FLAT_DIR.relative_to(REPO_ROOT)}/")
    print(f"legacy mirror: {total} OOBIs -> {LEGACY_DIR.relative_to(REPO_ROOT)}/")
    print(f"wrote .well-known/host-meta.json for {args.host.rstrip('/')}")
    print("wrote .well-known/index.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
