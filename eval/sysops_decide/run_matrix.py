#!/usr/bin/env python3
"""Sequential live matrix: d3:2b, qwen3.5:4b, then d3:4b if it appears.

Does not pull models. Inference is one model at a time. Polls Ollama tags
for d3:4b until a deadline, then runs that size or records a skip.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVAL = Path(__file__).resolve().parent
PY = sys.executable
REPRO_RESULTS = ROOT / "repro" / "escalane" / "results"
REPRO_EPISODES = REPRO_RESULTS / "episodes"
LOG = EVAL / "results" / "matrix_log.txt"
POLL_SECONDS = 75
D3_4B_WAIT_S = 30 * 60


def log(msg: str) -> None:
    line = f"{datetime.now(timezone.utc).isoformat()} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def tags() -> list[str]:
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=5) as resp:
            data = json.loads(resp.read().decode())
    except Exception as exc:
        log(f"tags_error {type(exc).__name__}")
        return []
    return [m.get("name", "") for m in data.get("models") or []]


def has_model(name: str) -> bool:
    names = tags()
    return any(n == name or n.startswith(name + ":") for n in names)


def _last_json(text: str) -> dict:
    text = text.strip()
    decoder = json.JSONDecoder()
    try:
        obj = decoder.decode(text)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    last = None
    idx = 0
    while idx < len(text):
        while idx < len(text) and text[idx].isspace():
            idx += 1
        if idx >= len(text):
            break
        try:
            obj, end = decoder.raw_decode(text, idx)
        except json.JSONDecodeError:
            nxt = text.find("{", idx + 1)
            if nxt < 0:
                break
            idx = nxt
            continue
        if isinstance(obj, dict):
            last = obj
        idx = end
    if last is None:
        raise ValueError(text[:400])
    return last


def _run(cmd: list[str]) -> dict:
    log("RUN " + " ".join(cmd))
    proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        log(f"FAIL rc={proc.returncode} stderr={proc.stderr[-500:]}")
        return {"status": "error", "returncode": proc.returncode, "stderr": proc.stderr[-800:]}
    try:
        return _last_json(proc.stdout)
    except Exception as exc:
        log(f"PARSE_FAIL {exc}")
        return {"status": "error", "reason": "parse", "stdout_tail": proc.stdout[-400:]}


def _copy_decide(summary: dict) -> None:
    if summary.get("status") in ("error", "skipped_live") or not summary.get("results"):
        return
    REPRO_RESULTS.mkdir(parents=True, exist_ok=True)
    REPRO_EPISODES.mkdir(parents=True, exist_ok=True)
    model = str(summary.get("model", "model")).replace(":", "")
    subset = str(summary.get("subset", "subset"))
    backend = str(summary.get("backend", "ollama"))
    src = Path(summary["results"])
    dest = REPRO_RESULTS / f"repro_{backend}_{model}_{subset}.json"
    shutil.copy2(src, dest)
    ep = summary.get("episodes")
    if ep and Path(ep).is_file():
        # Filename tokens: repro_{backend}_{subset}_... so the CSV parser keeps subset.
        shutil.copy2(Path(ep), REPRO_EPISODES / f"repro_{backend}_{subset}_{model}.jsonl")
    log(f"COPIED {dest.name}")


def _copy_gen(summary: dict) -> None:
    if summary.get("status") != "ok" or not summary.get("results"):
        return
    REPRO_RESULTS.mkdir(parents=True, exist_ok=True)
    src = Path(summary["results"])
    subset = str(summary.get("subset", "subset"))
    model = str(summary.get("model", "model")).replace(":", "")
    dest = REPRO_RESULTS / f"generative_{model}_{subset}.json"
    shutil.copy2(src, dest)
    log(f"COPIED {dest.name}")


def decide(model: str, subset: str) -> dict:
    summary = _run(
        [
            PY,
            str(EVAL / "runner.py"),
            "--backend",
            "ollama",
            "--model",
            model,
            "--subset",
            subset,
            "--timeout",
            "180",
            "--require-live",
        ]
    )
    _copy_decide(summary)
    phase = summary.get("phase_a") or {}
    log(
        f"DECIDE {model} {subset} status={summary.get('status', summary.get('label'))} "
        f"n={summary.get('n_records')} acc={phase.get('choice_accuracy')} "
        f"argv={summary.get('unauthorized_argv_total')}"
    )
    return summary


def generative(subset: str) -> dict:
    summary = _run(
        [
            PY,
            str(EVAL / "generative_baseline.py"),
            "--backend",
            "ollama",
            "--model",
            "qwen3.5:4b",
            "--subset",
            subset,
            "--timeout",
            "300",
            "--require-live",
        ]
    )
    _copy_gen(summary)
    metrics = summary.get("metrics") or {}
    log(
        f"GEN {subset} status={summary.get('status')} n={metrics.get('n')} "
        f"fp={metrics.get('injection_false_permit')} argv={metrics.get('unauthorized_argv')} "
        f"p50={metrics.get('latency_p50_ms')}"
    )
    return summary


def latency(model: str) -> dict:
    summary = _run(
        [
            PY,
            str(EVAL / "latency_probe.py"),
            "--model",
            model,
            "--subset",
            "injection",
            "--limit",
            "4",
            "--timeout",
            "180",
        ]
    )
    if summary.get("results"):
        src = Path(summary["results"])
        if src.is_file():
            REPRO_RESULTS.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, REPRO_RESULTS / f"latency_probe_{model.replace(':', '')}.json")
    log(
        f"LAT {model} packed_p50={summary.get('packed_p50_ms')} "
        f"seq_p50={summary.get('sequential_p50_ms')} ratio={summary.get('ratio_p50')}"
    )
    return summary


def main() -> None:
    log(f"MATRIX_START tags={tags()}")
    started = time.time()
    deadline = started + D3_4B_WAIT_S
    decide("d3:2b", "injection")
    decide("d3:2b", "all")
    latency("d3:2b")
    gen_inj = generative("injection")
    p50 = (gen_inj.get("metrics") or {}).get("latency_p50_ms")
    # Second System One size before the optional full generative pass.
    found = has_model("d3:4b")
    while not found and time.time() < deadline:
        log("WAIT d3:4b")
        time.sleep(POLL_SECONDS)
        found = has_model("d3:4b")
    if found:
        log("d3:4b present")
        decide("d3:4b", "injection")
        decide("d3:4b", "all")
        latency("d3:4b")
    else:
        log("SKIP d3:4b still missing after wait")
        skip = {
            "status": "skipped_live",
            "reason": "model_missing",
            "model": "d3:4b",
            "waited_s": round(time.time() - started, 1),
            "note": "d3:4b was not in ollama tags before the wait deadline. Not pulled by this run.",
        }
        path = EVAL / "results" / "d3_4b_skipped.json"
        path.write_text(json.dumps(skip, indent=2), encoding="utf-8")
    if isinstance(p50, (int, float)) and p50 < 30000 and gen_inj.get("status") == "ok":
        generative("all")
    else:
        log(f"SKIP generative all p50_ms={p50}")
    log(f"MATRIX_DONE elapsed_s={round(time.time() - started, 1)} tags={tags()}")


if __name__ == "__main__":
    main()
