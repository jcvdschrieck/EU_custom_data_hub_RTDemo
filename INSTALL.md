# Install guide

The EU Custom Data Hub demo is distributed as a single ZIP from
SharePoint. **There is no GitHub clone step**. Everything you need —
source, dependencies, pre-built frontend, pre-seeded databases — sits
inside the ZIP.

If you're a developer who wants to work on the project itself rather
than just install and demo, see `README.md` § "Development setup".

---

## 1. Before you start

### 1.1 Check the requirements

See **[HARDWARE.md](HARDWARE.md)** for the full hardware table and
**[PREREQUISITES.md](PREREQUISITES.md)** for software / network /
permissions detail (especially relevant on locked-down corporate
machines or behind a firewall). Quick check:

- **8 GB RAM minimum** if you'll use a cloud LLM (OpenAI / Anthropic / Azure)
- **16 GB RAM** if you want to run the LLM locally via LM Studio
- **2–16 GB free disk** (see [PREREQUISITES.md § 3](PREREQUISITES.md#3-disk-space-breakdown))
- **Windows 10/11**, **macOS 12+**, or **Ubuntu 22.04+**

Python 3.11+ and Node 18+ will be installed automatically by the
installer if they're not already present and you have admin/sudo
rights. If the auto-install can't run on your machine (corporate
policy, no admin), see
[PREREQUISITES.md § 1](PREREQUISITES.md#1-required-software) for the
manual download links.

### 1.2 Pick how the AI agent will think

The fraud-detection agent calls a Large Language Model. You have
four interchangeable options — pick the one that matches your laptop
and your access:

| Option | What you need | Cost | Privacy |
|---|---|---|---|
| **LM Studio (local)** | 16 GB RAM, ~6 GB disk for the model | Free | Fully local |
| **OpenAI** | API key from your OpenAI account | Pay-per-use (~$0.001–0.05 / case) | Sent to OpenAI |
| **Anthropic Claude** | API key from your Anthropic account | Pay-per-use (~$0.005–0.05 / case) | Sent to Anthropic |
| **Azure OpenAI** | Your company's Azure deployment | Per-Azure contract | Stays in your tenant |

You can change provider any time after install — just edit
`config.env` and re-run the installer.

### 1.3 Optional — install LM Studio (only if you picked LM Studio)

1. Download from <https://lmstudio.ai>.
2. Search and download a model — recommended:
   `mistralai/mistral-7b-instruct-v0.3` (~4 GB).
3. Open the **Developer** tab, load the model.
4. Slide **Context Length** to **8192** (the default 4 K is too small
   for the demo's prompts and surfaces as a "Context overflow" error
   at runtime).
5. Click **Start Server** (default port 1234, leave as-is).

You can do this *after* installing the demo — the demo will simply
return "uncertain" for fraud verdicts until LM Studio is running.

---

## 2. Get the package

1. Go to the **EU Custom Data Hub** SharePoint site.
2. Open **Releases / EU-Custom-Data-Hub-vX.Y.zip** — pick the latest
   version.
3. Click **Download**.
4. **Right-click the ZIP → Properties → check "Unblock"** (Windows
   only — flags the file as safe so PowerShell will run scripts from
   inside it).
5. Extract the ZIP. Pick a path *without spaces or special
   characters* — `C:\EU-Custom-Data-Hub` or
   `~/Demos/EU-Custom-Data-Hub` work; `C:\My Documents\Demo (final).zip`
   will cause Node-module resolution failures.

The extracted folder will look like:

```
EU-Custom-Data-Hub-vX.Y/
├── INSTALL.md           ← you are here
├── HARDWARE.md
├── QUICKSTART.md
├── README.md
├── config.env           ← user-editable settings
├── install.sh           ← macOS / Linux setup
├── install.ps1          ← Windows setup
├── run.sh / run.ps1     ← launchers
├── requirements.txt
├── api.py / app.py / seed_databases.py
├── frontend/            ← internal pipeline UI (pre-built into dist/)
├── customsandtaxriskmanagemensystem/   ← C&T operator dashboard
├── vat_fraud_detection/                ← fraud agent + RAG
├── lib/, scripts/, data/, docs/
└── wheels/              ← pre-fetched Python dependencies (offline install)
```

---

## 3. Configure (one minute)

Open `config.env` in any text editor. The four knobs that matter:

```
LLM_PROVIDER=lmstudio          # lmstudio | openai | anthropic | azure
LLM_MODEL=mistralai/mistral-7b-instruct-v0.3
LLM_API_KEY=
LLM_BASE_URL=
```

### If you picked LM Studio

Leave the file as-is. The default is LM Studio.

### If you picked OpenAI

```
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o-mini
LLM_API_KEY=sk-proj-...your-key-here...
```

Other valid `LLM_MODEL` values: `gpt-4o`, `gpt-4-turbo`, `gpt-3.5-turbo`.

### If you picked Anthropic

```
LLM_PROVIDER=anthropic
LLM_MODEL=claude-sonnet-4-6
LLM_API_KEY=sk-ant-api03-...your-key-here...
```

Other valid models: `claude-opus-4-7`, `claude-haiku-4-5-20251001`.

### If you picked Azure OpenAI

```
LLM_PROVIDER=azure
LLM_API_KEY=...your-azure-api-key...
LLM_BASE_URL=                  # leave blank
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com
AZURE_OPENAI_DEPLOYMENT=gpt-4o-deployment   # YOUR deployment name
AZURE_OPENAI_API_VERSION=2024-02-15-preview
```

`AZURE_OPENAI_DEPLOYMENT` is the *deployment name* you set up in
Azure, not the model name.

> **Where the API key lives:** the installer copies it from
> `config.env` into `vat_fraud_detection/.env`, which is git-ignored.
> Don't paste the key into any source file.

### Customise ports (optional)

```
BACKEND_PORT=8505              # FastAPI backend
CT_FRONTEND_PORT=8080          # C&T operator dashboard
```

Change these only if 8505 or 8080 collide with something else on
your machine. The installer wires the new values everywhere they're
referenced — no other files need editing.

---

## 4. Run the installer

### macOS / Linux

```bash
cd EU-Custom-Data-Hub-vX.Y
./install.sh
```

If `./install.sh` says "permission denied":
```bash
chmod +x install.sh run.sh
./install.sh
```

### Windows

Open **PowerShell** (not Command Prompt — search the Start menu for
"PowerShell"). Then:

```powershell
cd EU-Custom-Data-Hub-vX.Y
.\install.ps1
```

If PowerShell blocks the script with *"running scripts is disabled"*,
unblock once with:

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

…and re-run `.\install.ps1`.

### What happens

The installer prints its progress in the terminal. It will:

1. Verify Python ≥ 3.11 and Node ≥ 18 (auto-installing if missing
   via Homebrew / winget / apt).
2. Create a Python virtual environment in `.venv/`.
3. Install Python dependencies — **offline** from the bundled
   `wheels/` directory (no PyPI fetch).
4. Install Node dependencies for the C&T dashboard (`npm install`).
5. Generate `customsandtaxriskmanagemensystem/.env` and
   `vat_fraud_detection/.env` from your `config.env`.
6. Warm the embedder cache so the agent runs offline.
7. Seed the four SQLite databases.
8. Print an **Active LLM configuration** summary so you can verify
   the right provider/model/key got wired.

Total time: 2–5 minutes on a fresh machine, ~30 s on a re-run.

The installer is **idempotent** — re-run it any time you change
`config.env` to re-generate the `.env` files.

---

## 5. Optional — build the RAG knowledge base (~5 min)

Without this step, the fraud agent works but cannot cite specific
articles of Irish VAT legislation:

```bash
# macOS / Linux
cd vat_fraud_detection
.venv/bin/python build_knowledge_base.py --minilm-only
cd ..
```

```powershell
# Windows
cd vat_fraud_detection
..\.venv\Scripts\python.exe build_knowledge_base.py --minilm-only
cd ..
```

This downloads the source documents (VAT Consolidation Act 2010,
Revenue Tax & Duty Manuals) and embeds them into a local ChromaDB
index (~18 MB). Re-runs are idempotent.

---

## 6. Launch

```bash
# macOS / Linux
./run.sh
```

```powershell
# Windows
.\run.ps1
```

Two services come up:

| URL | Role |
|---|---|
| <http://localhost:8505/simulation> | The control deck — click **▶ Start** to begin |
| <http://localhost:8080/customs-authority> | The Irish customs/tax officer view |

Open both. Click **▶ Start** on the simulation page.

> **Don't launch from inside PyCharm or any IDE.** PyCharm's debugger
> wraps the Python process and doubles memory use (≈ 2 GB instead of
> ≈ 300 MB). A plain Terminal / PowerShell is what you want.

For what to demo (the two showcase cases) and the self-test
checklist, see **[QUICKSTART.md](QUICKSTART.md)**.

---

## 7. Switching LLM provider after install

To change provider (or model, or API key) any time:

1. Edit `config.env` — change `LLM_PROVIDER`, `LLM_MODEL`, and / or
   `LLM_API_KEY`.
2. Re-run `./install.sh` (or `.\install.ps1`). It re-generates the
   `.env` files and prints the new active config — nothing else
   needs touching.
3. Restart the demo (`./run.sh`).

You can keep multiple `config.env.cloud`, `config.env.local` etc.
copies and `cp config.env.cloud config.env` before re-running.

---

## 8. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `install.ps1` says *"running scripts is disabled"* | Default PowerShell policy | `Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned`, re-run |
| `install.sh: Permission denied` | Bit not set | `chmod +x install.sh run.sh` |
| `pip install` errors with "externally-managed environment" | System Python on Debian/Ubuntu/macOS-Homebrew | Already mitigated — installer creates a venv. If you ran pip outside the venv, delete `.venv/` and re-run the installer. |
| Fraud agent returns `uncertain` despite a cloud key | Wrong provider name, key not picked up, or SDK not installed | Check the **Active LLM configuration** print at the bottom of the install log. Verify `vat_fraud_detection/.env` contains the provider-specific key (`OPENAI_API_KEY=…`, `ANTHROPIC_API_KEY=…`, etc.). For Anthropic, ensure `pip show anthropic` succeeds in `.venv/`. |
| Fraud agent error: *"Context overflow / n_keep ≥ n_ctx"* | LM Studio context length still at default 4096 | LM Studio → Developer tab → model settings → Context Length → 8192 |
| Fraud agent takes ~30 s instead of ~5 s | LM Studio running on CPU only | Enable GPU offload in LM Studio's model settings (Apple Silicon does it automatically) |
| `npm install` fails with `EACCES` on Windows path | Path contains spaces or `OneDrive` | Move the extracted folder to `C:\EU-Custom-Data-Hub` and re-run installer |
| Customs dashboard shows stale cases after a sim reset | Browser localStorage cache | Hard-refresh the dashboard tab (Ctrl-Shift-R) |
| Memory stays around 2 GB | Backend launched through PyCharm's Run config | Close PyCharm; launch via `./run.sh` from a plain terminal |
| Two demo cases don't appear after first install | `data/` directory got corrupted between extraction and seeding | `rm -rf data/*.db` and re-run installer |

If none of these match your symptom, capture the full installer log
(scroll up in the terminal — the run is timestamped) and send it to
the project maintainer.

---

## 9. Uninstall

The demo lives entirely inside its extracted folder. To remove:

1. Stop any running services (close the terminal windows that
   `run.sh` / `run.ps1` opened).
2. Delete the extracted folder.

That's it — no system-wide installs to undo. (Python and Node, if the
installer auto-installed them, remain on your machine and can be used
for other work or removed via your OS package manager.)
