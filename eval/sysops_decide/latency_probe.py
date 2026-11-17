#!/usr/bin/env python3
"""Packed 3-question System One call versus three sequential calls.

Live only. A missing model or a down server prints skipped_live and exits 0.
The probe does not pull models. n is small on purpose: it measures the
packing ratio, not decision quality.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parents[2]
EVAL_DIR = Path(__file__).resolve().parent
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))
if str(EVAL_DIR) not in sys.path:
    sys.path.insert(0, str(EVAL_DIR))

from runner import (  # noqa: E402
    SUITE_DIR,
    SUITE_VERSION,
    ollama_model_status,
    select_records,
    state_from_record,
)
from escalane.catalog import load_catalog  # noqa: E402
from escalane.systemone import build_systemone_request  # noqa: E402

RESULTS_DIR = EVAL_DIR / "results"


def _pctile(vals: list[float], p: float) -> float | None:
    if not vals:
        return None
    ordered = sorted(vals)
    idx = min(len(ordered) - 1, max(0, int(round((p / 100.0) * (len(ordered) - 1)))))
    return ordered[idx]


def _post(base_url: str, payload: dict[str, Any], timeout: float) -> float:
    t0 = time.perf_counter()
    resp = httpx.post(f"{base_url.rstrip('/')}/v1/systemone", json=payload, timeout=timeout)
    elapsed = (time.perf_counter() - t0) * 1000.0
    resp.raise_for_status()
    return elapsed


def run_probe(
    *,
    model: str = "d3:2b",
    subset: str = "injection",
    limit: int = 4,
    base_url: str = "http://127.0.0.1:11434",
    suite: Path = SUITE_DIR,
    timeout: float = 180.0,
) -> dict[str, Any]:
    status = ollama_model_status(base_url, model)
    if status != "present":
        return {
            "status": "skipped_live",
            "reason": "model_missing" if status == "missing" else "ollama_unreachable",
            "model": model,
            "suite_version": SUITE_VERSION,
            "note": "Packed-versus-sequential probe was not executed.",
        }
    catalog = load_catalog(suite / "catalog.yaml")
    records = select_records(suite=suite, subset=subset)
    if limit > 0:
        records = records[:limit]
    rows: list[dict[str, Any]] = []
    for rec in records:
        state = state_from_record(rec)
        packed_payload = build_systemone_request(state, catalog, model)
        packed_ms = _post(base_url, packed_payload, timeout)
        sequential_ms = 0.0
        parts: dict[str, float] = {}
        for name, question in packed_payload["questions"].items():
            part_ms = _post(
                base_url,
                {"model": model, "state": state, "questions": {name: question}},
                timeout,
            )
            parts[name] = part_ms
            sequential_ms += part_ms
        rows.append(
            {
                "state_id": rec.get("id"),
                "packed_ms": packed_ms,
                "sequential_ms": sequential_ms,
                "ratio_sequential_over_packed": sequential_ms / packed_ms if packed_ms else None,
                "parts_ms": parts,
            }
        )
    packed = [float(r["packed_ms"]) for r in rows]
    seq = [float(r["sequential_ms"]) for r in rows]
    ratios = [float(r["ratio_sequential_over_packed"]) for r in rows if r.get("ratio_sequential_over_packed")]
    summary = {
        "status": "ok",
        "label": "live_optional",
        "suite_version": SUITE_VERSION,
        "backend": "ollama",
        "model": model,
        "catalog_hash": catalog.catalog_hash,
        "subset": subset,
        "n": len(rows),
        "packed_p50_ms": _pctile(packed, 50),
        "packed_p95_ms": _pctile(packed, 95),
        "sequential_p50_ms": _pctile(seq, 50),
        "sequential_p95_ms": _pctile(seq, 95),
        "ratio_p50": _pctile(ratios, 50),
        "rows": rows,
        "note": (
            "Wall-clock of one packed choice+noul+score request versus the sum of "
            "three sequential single-question requests on the same states. "
            "Small n; not a service SLA."
        ),
    }
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = RESULTS_DIR / f"latency_probe_{model.replace(':', '')}_{subset}_{stamp}.json"
    path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    summary["results"] = str(path)
    return summary


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Packed vs sequential System One latency")
    p.add_argument("--model", default="d3:2b")
    p.add_argument("--subset", choices=["injection", "all", "cal", "test"], default="injection")
    p.add_argument("--limit", type=int, default=4)
    p.add_argument("--base-url", default="http://127.0.0.1:11434")
    p.add_argument("--suite", type=Path, default=SUITE_DIR)
    p.add_argument("--timeout", type=float, default=180.0)
    args = p.parse_args(argv)
    summary = run_probe(
        model=args.model,
        subset=args.subset,
        limit=args.limit,
        base_url=args.base_url,
        suite=args.suite,
        timeout=args.timeout,
    )
    printable = {k: v for k, v in summary.items() if k != "rows"}
    print(json.dumps(printable, indent=2))


if __name__ == "__main__":
    main()
