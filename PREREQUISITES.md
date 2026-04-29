# Prerequisites

What needs to be on the target machine before you run `install.sh` /
`install.ps1`. Most users won't have to lift a finger — the
installer auto-fetches Python and Node when missing. This page is for:

- IT teams whitelisting endpoints behind a corporate firewall
- Users on locked-down machines where the auto-install can't run
- Anyone planning capacity for the demo (RAM / disk / network)

For tier-by-tier RAM and CPU specs, see [HARDWARE.md](HARDWARE.md).
For the install flow itself, see [INSTALL.md](INSTALL.md).

---

## 1. Required software

### Python 3.11+

The backend, simulator, fraud agent, RAG pipeline and seed scripts
all run on CPython.

| Path | What happens | Notes |
|---|---|---|
| **Already installed (≥ 3.11)** | Installer creates a venv and uses it | Verify with `python3 --version` (mac/Linux) or `python --version` (Windows) |
| **Auto-install (default)** | `install.sh` calls Homebrew / apt / dnf; `install.ps1` calls winget | Needs admin/sudo and outbound HTTPS to package mirrors |
| **Manual fallback** | Download from <https://www.python.org/downloads/release/python-3119/> and re-run installer | Choose the 64-bit installer; tick **Add python.exe to PATH** on Windows |

**3.10 and earlier are not supported** — `lib/llm_client.py` uses
`Protocol`-based typing and `match`-statement fallthroughs that 3.10
won't parse.

### Node.js 18+

Required for **building** the two frontends. Not needed at runtime
in **packaged mode** (the build artefacts ship inside the zip and
get served by Python's `http.server`).

| Path | What happens | Notes |
|---|---|---|
| **Already installed (≥ 18)** | Installer skips its Node bootstrap | Verify with `node --version` |
| **Auto-install (default)** | Homebrew on macOS, NodeSource apt repo on Debian/Ubuntu, winget on Windows | Needs admin/sudo |
| **Manual fallback** | LTS .pkg / .msi from <https://nodejs.org> | Open a **new** terminal afterwards so PATH is picked up |
| **Packaged install (zip from SharePoint)** | Not needed | Pre-built `dist/` ships in the zip |

**Node 16 and earlier are not supported** — Vite ≥ 5 requires Node 18+.

### Git

**Only needed for the developer workflow** (`git clone`). End users
installing from the SharePoint zip don't need Git at all.

### LM Studio (optional)

Only required if `LLM_PROVIDER=lmstudio` in `config.env` (the
default). Users picking OpenAI / Anthropic / Azure can skip it.

| Item | Value |
|---|---|
| Download | <https://lmstudio.ai> |
| Minimum version | 0.3.0 (older versions don't support OpenAI-compatible streaming) |
| Disk for the 7B model | ~4 GB (Q4_K_M) |
| RAM at idle | ~500 MB |
| RAM at inference | ~9 GB total (model + KV cache + Python overhead) |

See [INSTALL.md § 1.3](INSTALL.md#13-optional--install-lm-studio-only-if-you-picked-lm-studio)
for the four-step LM Studio setup.

---

## 2. Network — endpoints to whitelist

The demo can run **fully offline at runtime in tiers A and C**
(see HARDWARE.md). It just needs network access at one or more of
these phases. Send this table to your IT team if you're behind a
corporate firewall:

### 2.1 At install time

| Endpoint | When | Why |
|---|---|---|
| `pypi.org` + `files.pythonhosted.org` | If no bundled `wheels/` | Python dependencies (~150 MB) |
| `registry.npmjs.org` | If no bundled `dist/` | Node deps for building both frontends (~250 MB) |
| `huggingface.co` + `cdn-lfs.huggingface.co` | If no bundled `models/hf-cache/` | `all-MiniLM-L6-v2` SentenceTransformer weights (~90 MB) |
| `python.org`, `nodejs.org` | If auto-install runs | Python and Node installers |
| `formulae.brew.sh`, `dl-cdn.alpinelinux.org`, `archive.ubuntu.com` | OS-specific | Package-manager mirrors used by Homebrew / apt |
| `winget.microsoft.com`, `aka.ms`, `cdn.winget.microsoft.com` | Windows auto-install | winget package manifests |

A SharePoint-distributed install (zip with `wheels/` + `dist/` +
`models/`) needs **none** of the rows above — only the SharePoint
download itself.

### 2.2 At runtime — local LLM (Tier C)

**No outbound traffic at all.** The agent talks to LM Studio on
`http://localhost:1234`, fully on-machine.

### 2.3 At runtime — cloud LLM (Tier B)

| Provider | Endpoint | Outbound bytes per agent run |
|---|---|---|
| OpenAI | `api.openai.com:443` | ~30 KB request, ~20 KB response |
| Anthropic | `api.anthropic.com:443` | ~30 KB request, ~20 KB response |
| Azure | `<your-resource>.openai.azure.com:443` | Same as OpenAI |
| OpenAI-compatible (Together / Groq / Mistral cloud) | Whatever you set in `LLM_BASE_URL` | Same shape |

The fraud agent fires once per "Submit for Tax Review" click — this
is **not** a continuously chatty workload. Expect 5–20 calls per
demo session.

### 2.4 At runtime — additional optional fetches

| Endpoint | When | Why |
|---|---|---|
| `huggingface.co` | First agent run after install if `HF_HOME` cache is missing | Embedder weights (one-off) |
| RAG legislation sources (~10 URLs in `vat_fraud_detection/ireland_vat_demo_dataset/reference_pack_ireland_vat_sources.pdf`) | Only when running `build_knowledge_base.py` | Irish VAT legislation PDFs / web pages |

---

## 3. Disk space breakdown

| Component | Disk |
|---|---:|
| Extracted zip (source + bundled artefacts) | ~250 MB |
| Python venv (after pip install) | ~600 MB |
| C&T `node_modules/` (dev install only — not in packaged zip) | ~280 MB |
| `frontend/node_modules/` (dev install only) | ~120 MB |
| Pre-built `dist/` directories | ~5 MB |
| HuggingFace embedder cache | ~90 MB |
| ChromaDB RAG index (after `build_knowledge_base.py`) | ~18 MB |
| 4 SQLite databases | ~10 MB |
| LM Studio + 7B Mistral model | ~5 GB |
| LM Studio + 13B model | ~13 GB |
| Logs / event files (grow with use) | ~1–10 MB |

**Headline numbers** for planning:

| Scenario | Free disk needed |
|---|---:|
| Packaged install + cloud LLM (Tier B) | **2 GB** |
| Packaged install + LM Studio 7B (Tier C) | **8 GB** |
| Packaged install + LM Studio 13B (Tier D) | **16 GB** |
| Developer git clone + LM Studio 7B | **9 GB** (adds node_modules) |

---

## 4. Permissions

### Admin / sudo

Needed only if the installer auto-installs Python or Node. Once
both are in place, neither `install.sh` / `install.ps1` nor
`run.sh` / `run.ps1` need elevation.

| Step | Elevated? |
|---|---|
| Auto-install Python via brew / apt / winget | yes |
| Auto-install Node via brew / apt / winget | yes |
| Create `.venv/` | no |
| `pip install` into venv | no |
| `npm install` (build only) | no |
| Run uvicorn + http.server | no |
| Bind to ports 8505 / 8080 | no (high ports, no privilege) |

If the user can't get admin rights, they need to install Python and
Node manually first (Path 3 in § 1) and then run the installer as
a normal user.

### Antivirus / EDR

Some corporate AV products quarantine pip-installed scientific
packages (numpy / pandas / sentence-transformers) on first import,
producing import errors that look like missing dependencies. If
`pip show numpy` succeeds but `import numpy` fails:

1. Check the AV quarantine log for entries under
   `<install-path>\.venv\Lib\site-packages\numpy*`.
2. Whitelist the entire `.venv\` directory.

The packaged install (`wheels/`) doesn't dodge this — AV scans on
import, not on download. Same caveat applies.

### File-system path

Avoid:
- Paths with **spaces** (`C:\Program Files\...`) — break some npm
  scripts on Windows.
- Paths with **non-ASCII characters** — break Python's HF cache lookup.
- Network drives (`Z:\`) and OneDrive-synced folders — `.venv/`
  binaries don't always survive the OneDrive virtualisation.

A path like `C:\EU-Custom-Data-Hub` or `~/Demos/EU-Custom-Data-Hub`
is safe.

---

## 5. PowerShell on Windows

`install.ps1` and `run.ps1` declare `#Requires -Version 5.1`. Any
Windows 10 build 19041+ has 5.1 in the box. Older Windows (or
PowerShell 4.0) won't run these scripts.

If PowerShell blocks the scripts with *"running scripts is disabled
on this system"* — that's the default policy, not a missing version.
Unblock once with:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

`-Scope CurrentUser` doesn't require admin and only affects scripts
the current user runs.

---

## 6. Browser

Both dashboards use Server-Sent Events, modern CSS (Tailwind), and
ES2020 features. Tested on:

| Browser | Minimum version | Notes |
|---|---|---|
| **Chrome** | 100+ | Recommended |
| **Edge** | 100+ | Same engine as Chrome |
| **Firefox** | 100+ | |
| **Safari** | 16+ | macOS Ventura or later |

Internet Explorer is unsupported (no SSE, no modern fetch).

The pages use `localStorage` to persist a few UI flags between
reloads — private/incognito mode works but resets state across
sessions.

---

## 7. Pre-flight checklist

Before sharing the SharePoint zip with a non-technical demoer, run
through this on a representative machine:

- [ ] Python ≥ 3.11 installed (verify: `python3 --version`)
- [ ] Node ≥ 18 installed (only required for *dev* path or if the
      package is missing pre-built `dist/`; verify: `node --version`)
- [ ] Outbound HTTPS allowed to either:
      - SharePoint (always), **plus** the LLM provider's API endpoint
        if Tier B, **OR**
      - Nothing (Tier A or fully-offline Tier C)
- [ ] Disk free per § 3 above
- [ ] Path with no spaces / non-ASCII chars
- [ ] Browser current
- [ ] (Tier C) LM Studio installed and the chosen model downloaded
- [ ] (Cloud tier) LLM API key handed to the user *out-of-band*
      (don't paste keys into a Teams thread)

If all eight tick, the demoer should be able to extract → run
`install.sh` → run `run.sh` → demo within ~5 minutes on a fresh
machine.
