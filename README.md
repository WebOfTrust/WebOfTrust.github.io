# weboftrust.github.io

GLEIF `.well-known` discovery for the KERI/vLEI ecosystem — a reference
implementation of publishing KERI OOBIs (AIDs, schemas, witnesses) at a stable,
type-agnostic location.

## Published surface (generated)

Everything under `.well-known/` is build output. The contract for consumers:

| URL | What |
| --- | --- |
| `/.well-known/host-meta.json` | Entry point — RFC 6415 JRD: a flat OOBI lookup template + a link to the catalog |
| `/.well-known/oobi/<SAID>/index.json` | Resolve any AID/schema/witness by SAID — **type-agnostic** (200 = we have it, 404 = we don't) |
| `/.well-known/oobi/index.json` | Discovery catalog — every resource, grouped by type |
| `/.well-known/index.html` | Human landing page (`/` redirects here) |

How you organize your *source* is your business — only the published surface
above is standardized. ("Bring your own build script"; ours is below.)

## Source (hand-authored, not served)

Repo-root buckets, one per resource type:

```
aid/<SAID>/index.json        + aid/index.json   (SAID → friendly-name map)
schema/<SAID>/index.json
witness/<SAID>/index.json
```

These are excluded from the published site (`_config.yml`). OOBI files are used
verbatim — witness OOBIs are signed CESR streams, so they must not be altered.

## Regenerate

After adding or changing anything under the source buckets:

```sh
python3 scripts/build-wellknown.py        # rebuilds .well-known/ from source
git add -A && git commit                  # GitHub Pages serves static files; commit the output
```

The script regenerates the flat mirror, catalog, `host-meta.json`, and
`index.html` — so they can never drift from the source.
