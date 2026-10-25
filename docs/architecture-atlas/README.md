# Architecture Atlas: Am I Covered?

An interactive, evidence-backed map of this repository: components, files, functions, execution flows, data model, API, deployment, security, performance, tests and interview prep. It's documentation only and doesn't touch the application's runtime.

## Open it

The viewer is static HTML with everything vendored (Cytoscape.js, marked), so it works offline.

**Option 1: double-click** `docs/architecture-atlas/index.html`. It loads `data/atlas.js`, so `file://` works in Chrome, Edge and Firefox.

**Option 2: local web server** (recommended if your browser restricts `file://`):

```bash
cd docs/architecture-atlas
python -m http.server 8090
# open http://localhost:8090/
```

## Navigate

| Tab | What you get |
|---|---|
| System overview | purpose, counts, system-context graph, the flows to read first, top findings |
| Components | compound graph of components by group; tick **expand files** to see each component's files |
| Modules & files | directory tree + import graph; select a file and press **Expand symbols of selected file** for its functions and inferred call edges |
| Execution flows | sequence diagrams; click a step for its source evidence |
| Data model | stores, entities, fields, who reads/writes/deletes them |
| API catalog | every endpoint, handler, frontend caller, contract details |
| Deployment | verified vs. planned topology; all settings (secrets masked) |
| Security / Performance & scale | findings with severity, status, evidence, mitigation, plus the full report |
| Tests & quality | test files → modules, untested modules, executed checks |
| Interview prep / All reports | the Markdown reports rendered in place |

**Graph controls:** scroll to zoom, drag to pan, **Fit** / **Reset**, the minimap (click to jump), **Upstream** (what the selected node depends on), **Downstream** (what depends on it), **Neighbours**. Click a node or edge for its detail panel; dashed means inferred, partial or planned.

**Search:** press `/`, type a file, function, endpoint (`POST /api/ask`), setting (`GATE_THRESHOLD`), table field, finding or concept ("injection", "graph"). Arrow keys + Enter open the result in its view.

**Source links:** each reference shows `path:lines` with **VS Code** (a `vscode://` link to this checkout), **raw** (opens the file relative to the atlas) and **copy**.

**Status labels:** `verified` (read directly in code/config), `partial`, `inferred`, `unknown`.

## Regenerate after code changes

```bash
python docs/architecture-atlas/tools/build_atlas.py      # stdlib only, Python 3.10+
```

The script:

1. lists files with `git ls-files --cached --others --exclude-standard` (never reads `.env`, `storage/`, `.cache/`),
2. parses Python with `ast` (symbols, line ranges, imports, FastAPI routes, `Settings` fields, tests, name-resolved calls) and TS/TSX with regexes (declarations, imports, JSX usage, `/api/` URLs),
3. loads the hand-written `data/curated.json` (components, relations, flows, data entities, deployment, findings, decisions) and **resolves every evidence reference** (`file` + `symbol` / regex `match` / `lines`) to real line numbers,
4. validates that every edge, flow participant, data relation and evidence reference points at something that exists, prints any broken ones and exits with status 1,
5. writes `data/atlas.json` (diffable), `data/atlas.js` (for `file://`), and the generated reports `03-module-and-file-catalog.md` and `14-coverage-inventory.md`.

When code moves, the generated layer updates automatically; curated claims that no longer match fail the build instead of drifting silently.

## Layout

```
docs/architecture-atlas/
  index.html            viewer entry point
  assets/app.js         viewer logic (views, graphs, search, detail panels)
  assets/styles.css
  vendor/               cytoscape.min.js 3.30.2, marked.min.js 12.0.2 (MIT, see LICENSES.txt)
  data/curated.json     hand-written architecture layer (edit this)
  data/atlas.json       generated full model
  data/atlas.js         generated, same data as window.ATLAS
  tools/build_atlas.py  generator + validator
  reports/01..14-*.md   reports (03 and 14 are generated)
```

## Reports

01 system overview · 02 architecture · 03 module & file catalog (generated) · 04 execution & data flows · 05 database & data model · 06 API & integrations · 07 security review · 08 deployment & infrastructure · 09 performance & scalability · 10 testing & quality · 11 decisions & trade-offs · 12 interview guide · 13 open questions · 14 coverage inventory (generated)
