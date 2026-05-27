#!/usr/bin/env python3
"""Regenerate the generated parts of the .well-known/ tree.

Source of truth is the structured layout under
.well-known/{aid,schema,witness}/oobi/<SAID>/index.json, which is hand-authored
and never modified by this script. From it we generate:

1. .well-known/oobi/<SAID>/index.json  -- a flat, type-agnostic mirror (byte-exact
   copies) so a consumer can blindly GET /.well-known/oobi/<AID>/index.json and
   discover whether we publish anything for that identifier, without knowing its
   type. Copies are byte-exact because witness OOBIs are signed CESR streams;
   any change would invalidate their attached signatures.

2. .well-known/oobi/index.json  -- the discovery catalog: a generated inventory
   of every resource, enriched with metadata pulled from the source files
   (schema titles/versions from the schema OOBIs, AID friendly names from
   .well-known/aid/oobi/index.json). This replaces the old hand-authored
   .well-known/index.json, so the catalog can never drift from the tree.

3. .well-known/host-meta.json  -- the canonical entry point: an RFC 6415 JRD
   (Web Host Metadata) advertising link relations + URI templates for resolving
   OOBIs, with its discovery-catalog link pointing at the generated catalog
   above. host-meta describes the *shape* (rels + templates); the catalog
   enumerates the *contents*.

   We use host-meta's static templates rather than WebFinger because WebFinger
   needs a query endpoint, which static GitHub Pages cannot provide.

4. .well-known/index.html  -- a human landing page rendered from the same
   catalog data, so it stays in sync with the tree (do not hand-edit it).

GitHub Pages serves these as static files (Jekyll runs in safe mode, no custom
plugins), so the generated output must be committed. Re-run after any change to
the structured tree:

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

# Structured buckets that feed the flat mirror, in priority order.
SOURCE_TYPES = ("aid", "schema", "witness")
RESOURCE = "index.json"
DEFAULT_HOST = "https://weboftrust.github.io"

# Curated facts carried into the generated catalog (no source file holds these).
ORGANIZATION = "Global Legal Entity Identifier Foundation (GLEIF)"
CONTACT = "https://www.gleif.org"

REPO_ROOT = Path(__file__).resolve().parent.parent
WELL_KNOWN = REPO_ROOT / ".well-known"
FLAT_DIR = WELL_KNOWN / "oobi"

# Advisory media type per bucket (what the link target represents).
TYPE_MEDIA = {
    "aid": "application/json",
    "schema": "application/schema+json",
    "witness": "application/json",
}


def discover() -> tuple[dict[str, dict[str, str]], list[str]]:
    """Return (entries keyed by SAID, collision messages)."""
    entries: dict[str, dict[str, str]] = {}
    collisions: list[str] = []

    for kind in SOURCE_TYPES:
        bucket = WELL_KNOWN / kind / "oobi"
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
    """Map AID SAID -> friendly name from .well-known/aid/oobi/index.json."""
    listing = WELL_KNOWN / "aid" / "oobi" / RESOURCE
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
    """Rebuild the flat mirror + catalog; return resources keyed by SAID."""
    if FLAT_DIR.exists():
        shutil.rmtree(FLAT_DIR)
    FLAT_DIR.mkdir(parents=True)

    aid_names = load_aid_names()
    resources: dict[str, dict] = {}
    for said, info in sorted(entries.items()):
        dest_dir = FLAT_DIR / said
        dest_dir.mkdir()
        shutil.copyfile(REPO_ROOT / info["source"], dest_dir / RESOURCE)

        entry: dict[str, str] = {
            "type": info["type"],
            "oobi": f"/.well-known/oobi/{said}/{RESOURCE}",
            "source": f"/{info['source']}",
        }
        if info["type"] == "aid" and said in aid_names:
            entry["name"] = aid_names[said]
        elif info["type"] == "schema":
            entry.update(schema_meta(REPO_ROOT / info["source"]))
        resources[said] = entry

    catalog = {
        "name": "GLEIF OOBI Discovery Catalog",
        "description": (
            "Generated inventory of every published OOBI resource. GET "
            "/.well-known/oobi/<SAID>/index.json to resolve any one by SAID/AID "
            "without knowing its type. Discoverable via /.well-known/host-meta.json."
        ),
        "generator": "scripts/build-wellknown.py",
        "updated": datetime.date.today().isoformat(),
        "count": len(resources),
        "organization": ORGANIZATION,
        "contact": CONTACT,
        "resources": resources,
    }
    (FLAT_DIR / RESOURCE).write_text(json.dumps(catalog, indent=2) + "\n")
    return resources


def build_host_meta(host: str, present_types: list[str]) -> None:
    """Write an RFC 6415 JRD describing how to discover resources on this host."""
    host = host.rstrip("/")
    rels = f"{host}/rels"
    links = [
        {
            # Type-agnostic flat lookup; no advisory type because the target may
            # be a schema, an AID reply, or a witness CESR stream.
            "rel": f"{rels}/oobi",
            "template": f"{host}/.well-known/oobi/{{said}}/{RESOURCE}",
            "titles": {"en": "Type-agnostic OOBI lookup by SAID/AID"},
        }
    ]
    for kind in present_types:
        links.append(
            {
                "rel": f"{rels}/{kind}-oobi",
                "type": TYPE_MEDIA[kind],
                "template": f"{host}/.well-known/{kind}/oobi/{{said}}/{RESOURCE}",
                "titles": {"en": f"{kind.capitalize()} OOBI lookup by SAID"},
            }
        )
    links.append(
        {
            "rel": f"{rels}/discovery-catalog",
            "type": "application/json",
            "href": f"{host}/.well-known/oobi/{RESOURCE}",
            "titles": {"en": "Generated discovery catalog (all OOBI resources)"},
        }
    )

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
<!-- Generated by scripts/build-wellknown.py from the .well-known/{aid,schema,witness}/oobi tree. Do not edit by hand. -->
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
    groups: dict[str, list] = {t: [] for t in present_types}
    for said, entry in resources.items():
        groups.setdefault(entry["type"], []).append((said, entry))

    sections = []
    for kind in present_types:
        items = sorted(groups.get(kind, []), key=SECTION_SORT[kind])
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
        f"    <p>Generated {datetime.date.today().isoformat()} by "
        "<code>scripts/build-wellknown.py</code> &mdash; do not edit by hand.</p>"
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

    if not WELL_KNOWN.is_dir():
        print(f"error: {WELL_KNOWN} not found", file=sys.stderr)
        return 1

    entries, collisions = discover()
    if collisions:
        print("error: SAID collision across structured buckets:", file=sys.stderr)
        for msg in collisions:
            print(f"  {msg}", file=sys.stderr)
        return 1

    resources = build_catalog(entries)

    by_type: dict[str, int] = {}
    for info in resources.values():
        by_type[info["type"]] = by_type.get(info["type"], 0) + 1
    present_types = [t for t in SOURCE_TYPES if by_type.get(t)]

    build_host_meta(args.host, present_types)
    build_index_html(resources, present_types)

    summary = ", ".join(f"{by_type[t]} {t}" for t in present_types)
    print(f"catalog + flat mirror: {len(resources)} OOBIs ({summary}) -> {FLAT_DIR.relative_to(REPO_ROOT)}/")
    print(f"wrote .well-known/host-meta.json for {args.host.rstrip('/')}")
    print("wrote .well-known/index.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
