# DEPRECATED

This `/oobi/` directory is deprecated and will be retired in a future release.

OOBI resources are now served from the `.well-known/` structure, which provides
a discoverable index and a category-per-resource layout:

| Resource type  | New location                                  |
| -------------- | --------------------------------------------- |
| AID OOBIs      | `/.well-known/aid/oobi/<SAID>/index.json`     |
| Schema OOBIs   | `/.well-known/schema/oobi/<SAID>/index.json`  |
| Witness OOBIs  | `/.well-known/witness/oobi/<SAID>/index.json` |

The discovery index at [`/.well-known/index.json`](../.well-known/index.json)
lists every resource currently available, along with metadata. Please update
any cached or hardcoded references to point at the corresponding
`/.well-known/` path before this directory is removed.
