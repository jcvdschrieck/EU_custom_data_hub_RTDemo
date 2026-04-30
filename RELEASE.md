# Release runbook

Maintainer-side procedure for publishing a new EU Custom Data Hub
demo release to SharePoint. End users download the resulting ZIP and
follow [INSTALL.md](INSTALL.md) — they don't touch this document.

---

## When to cut a release

- A new feature has landed and been validated end-to-end.
- A bug fix needs to reach demoers (typically the SharePoint
  audience).
- Quarterly cadence even if nothing changed, so the bundled
  dependencies stay reasonably fresh.

Releases are versioned `MAJOR.MINOR.PATCH` (semver) in the top-level
`VERSION` file:

- **MAJOR** — breaking change that needs a fresh extract / re-config
  (e.g. config.env schema change, Python version bump).
- **MINOR** — new feature, backward-compatible. End users can extract
  over the old folder if they want, but a clean extract is safer.
- **PATCH** — bug fix only. Re-running install.sh against the same
  folder is enough.

---

## Steps

### 1. Bump the version

```bash
# Edit VERSION (e.g. 1.0.0 → 1.1.0) — single line, no quotes.
echo 1.1.0 > VERSION
git add VERSION && git commit -m "Release v1.1.0"
```

### 2. Build a ZIP per target OS

The Python wheels in the package are platform-specific, so each OS
needs its own build. Run `scripts/build_release.sh` (or
`build_release.ps1`) on each target, then collect the three resulting
ZIPs.

#### macOS

On a Mac (Apple Silicon recommended for forward compatibility):

```bash
./scripts/build_release.sh
# → releases/EU-Custom-Data-Hub-v1.1.0-macos.zip
```

#### Linux

On Ubuntu 22.04 LTS (or any glibc-compatible distro):

```bash
./scripts/build_release.sh
# → releases/EU-Custom-Data-Hub-v1.1.0-linux.zip
```

#### Windows

In PowerShell on Windows 10/11:

```powershell
.\scripts\build_release.ps1
# → releases\EU-Custom-Data-Hub-v1.1.0-windows.zip
```

> **Build environment**: each builder needs Python 3.11+, Node 18+,
> and internet access (the build script downloads wheels and the HF
> embedder cache). Allow 5–10 minutes per platform.

#### What's in each ZIP

| Artefact | Source | Size |
|---|---|---:|
| Source tree (`api.py`, `lib/`, `frontend/src/`, …) | Working copy | ~30 MB |
| `wheels/*.whl` | `pip download -r requirements.txt` | ~150 MB (varies) |
| `frontend/dist/` | `npm run build` for internal frontend | ~1 MB |
| `customsandtaxriskmanagemensystem/dist/` | `npm run build` for C&T dashboard | ~3 MB |
| `models/hf-cache/hub/` | Repo-tracked (refresh below) | ~87 MB |
| `data/*.db` | `seed_databases.py` | ~10 MB |
| `.packaged` marker | Build script | < 1 KB |
| **Total ZIPped** | | **~120–180 MB** |

`node_modules/` is **not** bundled — the C&T dashboard ships pre-built
into `dist/` and is served by Python's `http.server` at runtime. No
Node needed at install time on the end-user's machine.

### 3. Smoke-test each ZIP on a clean machine

A "clean machine" means no `.venv/`, no prior install. Run this on
each target OS:

```bash
mkdir /tmp/release-test && cd /tmp/release-test
unzip /path/to/EU-Custom-Data-Hub-v1.1.0-<os>.zip
cd EU-Custom-Data-Hub-v1.1.0-<os>
./install.sh   # or .\install.ps1 on Windows
```

Verify:

- [ ] **Packaged mode detected** message appears at the top of the
      install log.
- [ ] **Installing Python dependencies (offline, from wheels/)** —
      not "from PyPI".
- [ ] **HF cache pre-shipped** — not "Warming the Hugging Face
      embedder cache".
- [ ] **Databases already pre-seeded** — not "Seeding databases".
- [ ] **Active LLM configuration** block at the end shows the
      provider you set in `config.env`.
- [ ] `./run.sh` (or `.\run.ps1`) starts without errors.
      C&T dashboard line says `[static (python http.server, dist/)]`.
- [ ] Backend health check passes:
      `curl http://localhost:8505/health` → `{"status":"ok",…}`.
- [ ] C&T dashboard loads: `http://localhost:8080/customs-authority`
      shows the operator UI.
- [ ] Click ▶ Start on the simulation page → ShenZhen and Delhi
      cases visible within 2 sim-minutes (×1 speed).

If any step fails, **don't ship** — fix and re-build.

### 4. Upload to SharePoint

1. Open the **EU Custom Data Hub** SharePoint site → **Releases**
   library.
2. Upload all three ZIPs:
   - `EU-Custom-Data-Hub-v1.1.0-macos.zip`
   - `EU-Custom-Data-Hub-v1.1.0-linux.zip`
   - `EU-Custom-Data-Hub-v1.1.0-windows.zip`
3. **Pin the latest version** by giving it a higher SharePoint
   metadata "Release rank" (or whatever your tenant's convention
   is) so it's the first thing demoers see.
4. Optionally publish a **release notes** page:
   - One-line summary (the git commit subject usually works).
   - Bullet list of behaviour changes user-visible to demoers.
   - Note any breaking changes (e.g. `config.env` schema
     additions) and what users need to update on their end.

### 5. Notify the demoer audience

Post in the project's Teams channel / Slack:

```
EU Custom Data Hub v1.1.0 released — SharePoint Releases library has
the three OS-specific ZIPs. Headline: <one-liner>. Re-extract and
re-run install.sh; existing config.env can be reused.
```

If MAJOR was bumped, also call out config.env migration steps
explicitly — demoers will skim notifications.

---

## Build-script reference

### What `build_release.sh` skips when something goes wrong

The script never fails the whole build over an optional artefact.
If a step errors out, it strips the artefact from the staging dir
and logs a warning so the resulting ZIP still installs (the install
script falls back to the online path):

| Step | If it fails | End-user impact |
|---|---|---|
| `pip download` | `wheels/` removed from staging | Install needs PyPI access |
| `npm run build` (frontends) | `dist/` not copied | Install runs `npm install`/`build` itself (needs npm registry) |
| HF cache warm | `models/` removed | Install warms cache itself (needs huggingface.co) |
| DB seed | DBs deleted | Install runs seeder itself |

This means a broken build environment still produces a usable —
just not fully offline — package. Check the build log for any
`!!` warnings and rerun the build script on a healthier machine
before publishing.

### Updating `requirements.txt`

When you add a Python dependency, the next `build_release.sh` will
include the new wheel automatically. No build-script change needed.
Same for `package.json` — `npm install` runs at build time.

### Refreshing the carried HF embedder cache

The repo carries a pre-warmed copy of the `all-MiniLM-L6-v2` Hugging
Face embedder under `models/hf-cache/hub/` (~87 MB). `build_release.sh`
copies it straight into the staged release, which means a fresh build
no longer needs internet access to huggingface.co.

Refresh only when the model version itself changes (rare). The
procedure:

```bash
rm -rf models/hf-cache/hub
HF_HOME="$(pwd)/models/hf-cache" python3 scripts/warm_hf_cache.py
git add models/hf-cache/hub
git commit -m "Refresh HF embedder cache"
```

The inner `models/hf-cache/.gitignore` excludes `xet/`, the runtime
log directory `huggingface_hub` writes during warm-up — only the model
blobs themselves get tracked.

### Cross-platform binaries

`pip download` only fetches wheels matching the host's Python tags.
A macOS-built ZIP **will not install** on Windows (and vice versa).
Always run the build script on each target OS — don't try to
cross-build by passing `--platform` flags. It works for pure-Python
deps but breaks on C extensions like `numpy`, `pandas`, `chromadb`.

---

## Rollback

If a release turns out to be broken in the field:

1. In SharePoint, **rename** the broken ZIP to
   `EU-Custom-Data-Hub-v1.1.0-<os>.zip.broken` so users don't grab
   it by accident.
2. **Pin** the previous version (`v1.0.x`) back to the top of the
   Releases library.
3. Push a Teams / Slack notice with the symptom + the version users
   should fall back to.
4. Cut a `v1.1.1` patch with the fix and follow steps 1–5 above.

The end-user installer never deletes the previous extract, so
demoers can simply switch folders — no data migration required.
