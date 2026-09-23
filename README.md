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
| `/.well-known/oobi/index.json` | Discovery catalog — every resource, grouped by type, with witness endpoint `urls` and AID ↔ witness cross-links |
| `/.well-known/index.html` | Human landing page (`/` redirects here) |
| `/oobi/<SAID>/index.json` | Legacy path, byte-exact mirror of `/.well-known/oobi/` for pre-`.well-known` consumers |

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

### Witness entries

A witness entry is the witness's **own controller OOBI**, captured verbatim
from the witness itself:

```sh
curl http://<host>:<port>/oobi/<W>/controller > witness/<W>/index.json
```

It is a signed CESR stream containing the witness's inception event followed
by witness-signed `rpy` messages on `/loc/scheme` (`{eid, scheme, url}` — the
witness's endpoint, one per scheme) and `/end/role/add`. That signed
`/loc/scheme` reply **is** the per-witness endpoint record; it is what a
verifier holding only a witness AID should trust. Because it sits after the
inception event inside the stream, it is easy to miss when reading the file by
eye — which is why the build also lifts it into the catalog.

An AID entry is the AID's `/oobi/witness` reply, listing the witness OOBI URLs
that AID has designated. The build matches those URLs against the witnesses'
`/loc/scheme` URLs (by scheme and host:port) to cross-link the two.

In the catalog this shows up as:

```json
"witness": {
  "BDkq35LU…": {
    "urls": { "http": "http://65.21.253.212:5623/" },
    "witnessFor": ["EINmHd5g…"],
    "oobi": "/.well-known/oobi/BDkq35LU…/index.json"
  }
},
"aid": {
  "EDP1vHcw…": {
    "name": "GLEIF RoOT",
    "witnesses": ["BDwydI_F…", "BGYJwPAz…", "…"],
    "oobi": "/.well-known/oobi/EDP1vHcw…/index.json"
  }
}
```

`urls` and the cross-links are derived, never hand-entered, so they cannot
drift from the signed source. The build warns (but does not fail) if a witness
entry has no `/loc/scheme` reply or an AID's witness URL matches no published
witness.

## Regenerate

After adding or changing anything under the source buckets:

```sh
python3 scripts/build-wellknown.py        # rebuilds .well-known/ from source
git add -A && git commit                  # GitHub Pages serves static files; commit the output
```

The script regenerates the flat mirror, catalog, `host-meta.json`,
`index.html`, and the legacy `/oobi/` mirror — so they can never drift from the
source.

To confirm the stored witness entries still match what each witness serves
live (network only; writes nothing, exits non-zero on any mismatch):

```sh
python3 scripts/build-wellknown.py --check-live
```
