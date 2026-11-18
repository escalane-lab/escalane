#!/usr/bin/env python3
"""Optional live smoke for Ollama d3 decision models (https://ollama.com/library/d3).

Safe to run anytime:
- If Ollama is down → exit 0 with skipped_live (does not fail CI).
- If model missing → attempts `ollama pull` only when --pull is passed.
- Never unloads other models; user must free eGPU / start serve themselves.

Examples:
  uv run python scripts/smoke_d3.py
  uv run python scripts/smoke_d3.py --model d3:2b --pull
  uv run python scripts/smoke_d3.py --model d3:4b --pull --harness
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from escalane.catalog import load_catalog  # noqa: E402
from escalane.state import normalize_state  # noqa: E402
from escalane.systemone import (  # noqa: E402
    HttpSystemOne,
    build_systemone_request,
    ollama_reachable,
)


def _have_model(base_url: str, model: str) -> bool:
    try:
        with httpx.Client(timeout=5.0) as client:
            r = client.get(f"{base_url.rstrip('/')}/api/tags")
            r.raise_for_status()
            names = {m.get("name") for m in (r.json().get("models") or [])}
            return any(
                n == model or (isinstance(n, str) and n.startswith(model)) for n in names
            )
    except Exception:
        return False


def _pull(model: str) -> int:
    ollama = shutil.which("ollama")
    if not ollama:
        print(json.dumps({"status": "error", "reason": "ollama_cli_missing"}))
        return 2
    print(json.dumps({"status": "pulling", "model": model}), flush=True)
    return subprocess.run([ollama, "pull", model], check=False).returncode


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Smoke-test Ollama d3 via /v1/systemone")
    p.add_argument("--base-url", default="http://localhost:11434")
    p.add_argument("--model", default="d3:2b", help="d3:2b (APU) | d3 | d3:4b (eGPU)")
    p.add_argument("--pull", action="store_true", help="ollama pull if model missing")
    p.add_argument(
        "--harness",
        action="store_true",
        help="Also run packed choice+noul+score against seed catalog + php_502 state",
    )
    args = p.parse_args(argv)

    if not ollama_reachable(args.base_url):
        print(
            json.dumps(
                {
                    "status": "skipped_live",
                    "reason": "ollama_unreachable",
                    "hint": "Start ollama serve when eGPU/APU is free, then: ollama pull d3:2b",
                    "library": "https://ollama.com/library/d3",
                    "requires_ollama": ">=0.40.9",
                },
                indent=2,
            )
        )
        return 0

    if not _have_model(args.base_url, args.model):
        if not args.pull:
            print(
                json.dumps(
                    {
                        "status": "skipped_live",
                        "reason": "model_not_pulled",
                        "model": args.model,
                        "hint": f"uv run python scripts/smoke_d3.py --model {args.model} --pull",
                    },
                    indent=2,
                )
            )
            return 0
        rc = _pull(args.model)
        if rc != 0:
            return rc

    payload = {
        "model": args.model,
        "state": "Hello World",
        "questions": {
            "says_hello": {
                "type": "noul",
                "instructions": "Does the state text contain a greeting?",
                "criteria": {
                    "true": "The state text contains a greeting.",
                    "false": "The state text does not contain a greeting.",
                },
            }
        },
    }
    with httpx.Client(timeout=180.0) as http:
        r = http.post(f"{args.base_url.rstrip('/')}/v1/systemone", json=payload)
        r.raise_for_status()
        hello = r.json()

    out: dict = {
        "status": "ok",
        "model": args.model,
        "hello_noul": (hello.get("answers") or {}).get("says_hello"),
        "usage": hello.get("usage"),
        "library": "https://ollama.com/library/d3",
    }

    if args.harness:
        catalog = load_catalog(REPO / "datasets/sysops_decide/catalog.yaml")
        state = normalize_state(
            json.loads(
                (REPO / "src/escalane/examples/incidents/php_502.json").read_text(
                    encoding="utf-8"
                )
            )
        )
        client = HttpSystemOne(base_url=args.base_url, model=args.model)
        resp = client.decide(state, catalog, model=args.model)
        out["harness"] = {
            "playbook": (resp.answers.get("playbook") or {}).get("choice"),
            "noul": (resp.answers.get("safe_to_act") or {}).get("noul"),
            "blast": (resp.answers.get("blast") or {}).get("score"),
            "confidence_playbook": (resp.answers.get("playbook") or {}).get("confidence"),
            "questions": list(
                build_systemone_request(state, catalog, args.model)["questions"]
            ),
        }

    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
