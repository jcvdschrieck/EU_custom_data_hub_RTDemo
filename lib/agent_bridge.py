"""
Subprocess bridge to the vat_fraud_detection analyser.

Runs _analyse_tx.py inside the vat_fraud_detection project directory as an
isolated subprocess so the two projects' `lib` packages do not conflict.

Environment variables are resolved in this priority order:
  1. Already set in the parent process (e.g. exported before running uvicorn)
  2. vat_fraud_detection/.env  (auto-loaded if present)

Returns:
    {"verdict": "correct"|"incorrect"|"uncertain", "reasoning": str, "success": bool}
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

# Path to the vat_fraud_detection git submodule (lives inside this project)
_VFD_DIR = Path(__file__).parent.parent / "vat_fraud_detection"
_SCRIPT  = _VFD_DIR / "_analyse_tx.py"

# Demo-mode override file — short-circuits the real agent for specific
# transaction signatures so the operator isn't waiting ~1 min for the
# LLM+RAG round-trip on cases we want to showcase deterministically.
# File lives under data/ (re-read on every invocation, so edits apply
# on the next case without a server restart).
_OVERRIDES_FILE  = Path(__file__).parent.parent / "data" / "demo_fraud_overrides.json"
_VALID_VERDICTS  = {"correct", "incorrect", "uncertain"}
_DEFAULT_VERDICT = "incorrect"   # drives the Customs Officer to Recommend Control


def _load_overrides() -> list[dict]:
    """Return the list of demo overrides, or [] if the file is missing
    or unreadable. Keys starting with '_' in the JSON are documentation
    fields ignored here."""
    if not _OVERRIDES_FILE.is_file():
        return []
    try:
        data = json.loads(_OVERRIDES_FILE.read_text(encoding="utf-8"))
        return list(data.get("overrides") or [])
    except Exception as e:
        print(f"[agent_bridge] Failed to parse {_OVERRIDES_FILE}: {e}")
        return []


def _override_matches(tx: dict, match: dict) -> bool:
    """True when the tx satisfies every field in the match dict. Empty
    or missing match fields are skipped (== wildcard)."""
    seller_want = (match.get("seller_name") or "").strip()
    desc_want   = (match.get("item_description_contains") or "").strip().lower()
    if seller_want and seller_want != (tx.get("seller_name") or ""):
        return False
    if desc_want and desc_want not in (tx.get("item_description") or "").lower():
        return False
    # Both empty → matches nothing (avoid accidentally overriding every tx).
    if not seller_want and not desc_want:
        return False
    return True


def _try_apply_override(tx: dict) -> dict | None:
    """If the tx matches any override entry, sleep for delay_seconds then
    return a pre-canned result in the same shape as the real agent.
    Returns None otherwise (caller falls through to the real subprocess)."""
    for ovr in _load_overrides():
        match = ovr.get("match") or {}
        if not _override_matches(tx, match):
            continue

        delay = ovr.get("delay_seconds", 0)
        try:
            delay = max(0, int(delay))
        except (TypeError, ValueError):
            delay = 0

        verdict = (ovr.get("recommendation") or "").strip().lower()
        if verdict not in _VALID_VERDICTS:
            verdict = _DEFAULT_VERDICT

        rationale = (ovr.get("rationale") or "").strip() or "(no rationale provided)"
        source    = (ovr.get("source") or "").strip()

        # Fake an expected_rate consistent with the verdict so the
        # downstream VAT-gap math in _agent_worker runs normally.
        applied_rate = float(tx.get("vat_rate") or 0.0)
        correct_rate = tx.get("correct_vat_rate")
        if verdict == "incorrect":
            # Prefer the tx's own correct_vat_rate if the seeder set one;
            # otherwise fall back to Ireland's 23% standard for the demo.
            try:
                expected_rate = float(correct_rate) if correct_rate is not None else 0.23
            except (TypeError, ValueError):
                expected_rate = 0.23
        elif verdict == "correct":
            expected_rate = applied_rate
        else:  # uncertain
            expected_rate = None

        legislation_refs = []
        if source:
            legislation_refs.append({
                "ref":       source,
                "source":    source,
                "section":   None,
                "url":       None,
                "page":      None,
                "paragraph": None,
            })

        print(f"[agent_bridge] demo override '{ovr.get('name', '(anon)')}' "
              f"matched — sleeping {delay}s, returning verdict={verdict}")
        time.sleep(delay)

        return {
            "verdict":          verdict,
            "reasoning":        rationale,
            "legislation_refs": legislation_refs,
            "line_verdicts": [{
                "line_item_id":  "LI-0001",
                "verdict":       verdict,
                "applied_rate":  applied_rate,
                "expected_rate": expected_rate,
                "reasoning":     rationale,
            }],
            "success":          True,
        }
    return None


def _load_dotenv(env_path: Path) -> dict[str, str]:
    """
    Parse a .env file and return its key=value pairs.
    Skips blank lines and comments.  Strips inline comments and quotes.
    Does NOT override values already present in os.environ.
    """
    result: dict[str, str] = {}
    if not env_path.is_file():
        return result
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, rest = line.partition("=")
        key = key.strip()
        # Strip inline comment (but not inside URL strings like ://)
        value = rest.split(" #")[0].split("\t#")[0].strip()
        # Strip surrounding quotes
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        result[key] = value
    return result


def analyse_transaction_sync(tx: dict) -> dict:
    """
    Run the VAT fraud detection analyser on a single transaction dict.
    Blocking — call from a thread pool when used inside asyncio.

    Demo-mode overrides (data/demo_fraud_overrides.json) are consulted
    FIRST — if the tx signature matches an entry, a pre-canned result
    is returned after the configured delay without spawning the real
    agent subprocess at all.
    """
    override = _try_apply_override(tx)
    if override is not None:
        return override

    # Build subprocess environment: start from current env, then layer .env
    # on top for any keys not already set.
    env = dict(os.environ)
    dotenv_vals = _load_dotenv(_VFD_DIR / ".env")
    for k, v in dotenv_vals.items():
        env.setdefault(k, v)   # parent-process vars take priority

    try:
        result = subprocess.run(
            [sys.executable, str(_SCRIPT)],
            input=json.dumps(tx),
            capture_output=True,
            text=True,
            cwd=str(_VFD_DIR),
            env=env,
            timeout=90,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return {
                "verdict":   "uncertain",
                "reasoning": f"Subprocess error (rc={result.returncode}): {result.stderr[:500]}",
                "success":   False,
            }
        return json.loads(result.stdout.strip())
    except subprocess.TimeoutExpired:
        return {
            "verdict":   "uncertain",
            "reasoning": "Agent timed out after 90 seconds.",
            "success":   False,
        }
    except Exception as e:
        return {
            "verdict":   "uncertain",
            "reasoning": f"Bridge error: {e}",
            "success":   False,
        }
