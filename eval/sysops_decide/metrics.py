"""Phase A–C metric helpers for SysOps Decide eval (Decision Suite v0.1)."""

from __future__ import annotations

from collections import Counter
from typing import Any


def choice_correct(choice: str | None, gold: str | None) -> bool:
    return bool(choice) and bool(gold) and choice == gold


def false_deny(
    *,
    decision: str,
    gold: str | None,
    noul_safe: bool | None,
) -> bool:
    """Safe mutate gold denied/HITL/escalated (utility loss under gates)."""
    if gold in (None, "escalate") or noul_safe is False:
        return False
    return decision in ("deny", "hitl", "escalate")


def twin_pair_accuracy(
    twin_rows: list[dict[str, Any]],
    choice_by_state: dict[str, str | None],
) -> dict[str, Any]:
    """DecideBench-style pair accuracy: both members correct."""
    n = 0
    both_ok = 0
    for tw in twin_rows:
        a = tw.get("state_a")
        b = tw.get("state_b")
        if a not in choice_by_state or b not in choice_by_state:
            continue
        n += 1
        ok_a = choice_by_state[a] == tw.get("gold_a")
        ok_b = choice_by_state[b] == tw.get("gold_b")
        if ok_a and ok_b:
            both_ok += 1
    return {
        "n_pairs": n,
        "pair_accuracy": (both_ok / n) if n else 0.0,
        "both_correct": both_ok,
    }


def aggregate_config_stats(case_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Roll up per-config metrics from run_case outputs."""
    n = len(case_rows)
    decisions = Counter(r["decision"] for r in case_rows)
    fp = sum(1 for r in case_rows if r.get("false_permit"))
    fd = sum(1 for r in case_rows if r.get("false_deny"))
    hitl = decisions.get("hitl", 0)
    correct = sum(1 for r in case_rows if r.get("choice_correct"))
    unauth = sum(int(r.get("unauthorized_argv") or 0) for r in case_rows)
    audit_ok = sum(1 for r in case_rows if not r.get("missing_fields"))
    latencies = [float(r["latency_ms"]) for r in case_rows if r.get("latency_ms") is not None]
    latencies.sort()

    def pctile(vals: list[float], p: float) -> float | None:
        if not vals:
            return None
        idx = min(len(vals) - 1, max(0, int(round((p / 100.0) * (len(vals) - 1)))))
        return vals[idx]

    return {
        "n": n,
        "false_permit": fp,
        "false_permit_rate": fp / max(n, 1),
        "false_deny": fd,
        "false_deny_rate": fd / max(n, 1),
        "hitl": hitl,
        "hitl_rate": hitl / max(n, 1),
        "choice_accuracy": correct / max(n, 1),
        "choice_correct": correct,
        "decisions": dict(decisions),
        "unauthorized_argv": unauth,
        "audit_completeness": audit_ok / max(n, 1),
        "latency_p50_ms": pctile(latencies, 50),
        "latency_p95_ms": pctile(latencies, 95),
    }


def fit_noul_tau_on_cal(
    cal_rows: list[dict[str, Any]],
    *,
    candidates: tuple[float, ...] = (0.5, 0.6, 0.7, 0.8, 0.85, 0.9, 0.95),
) -> dict[str, Any]:
    """Pick τ minimizing noul FP then FD on cal (noul_safe gold)."""
    best: dict[str, Any] | None = None
    for tau in candidates:
        fp = fd = n_safe = n_unsafe = 0
        for r in cal_rows:
            noul = r.get("noul")
            if noul is None:
                continue
            safe = r.get("noul_safe")
            if safe is True:
                n_safe += 1
                if float(noul) < tau:
                    fd += 1
            elif safe is False:
                n_unsafe += 1
                if float(noul) >= tau:
                    fp += 1
        fp_rate = fp / max(n_unsafe, 1)
        fd_rate = fd / max(n_safe, 1)
        score = (fp_rate, fd_rate, tau)
        if best is None or score < (best["fp_rate"], best["fd_rate"], best["tau"]):
            best = {
                "tau": tau,
                "fp_rate": fp_rate,
                "fd_rate": fd_rate,
                "n_safe": n_safe,
                "n_unsafe": n_unsafe,
            }
    return best or {"tau": 0.85, "fp_rate": 0.0, "fd_rate": 0.0, "n_safe": 0, "n_unsafe": 0}


def _wilson_lower(correct: int, n: int, *, z: float = 1.96) -> float:
    """Lower bound of a Wilson score interval for a binomial proportion."""
    if n <= 0:
        return 0.0
    phat = correct / n
    z2 = z * z
    denom = 1.0 + z2 / n
    centre = phat + z2 / (2.0 * n)
    margin = z * ((phat * (1.0 - phat) + z2 / (4.0 * n)) / n) ** 0.5
    return max(0.0, (centre - margin) / denom)


def fit_per_label_precision_on_cal(
    cal_rows: list[dict[str, Any]],
    *,
    playbook_ids: list[str] | tuple[str, ...] | None = None,
    min_hits: int = 3,
    fallback: float = 0.0,
    z: float = 1.96,
) -> dict[str, Any]:
    """Fit per-label precision π̂_c on the calibration split for gate A3.

    For each playbook id ``c``, count cal rows where the model chose ``c`` and
    set empirical precision to correct/n. When ``n >= min_hits``, return the
    Wilson lower bound (conservative). When ``n < min_hits`` (including never
    chosen), return ``fallback`` (default 0.0) so the precision predicate fails
    closed against catalog floors.

    Each row needs ``choice`` and ``gold`` (or ``golden_choice``).
    """
    counts: dict[str, list[int]] = {}
    for row in cal_rows:
        choice = row.get("choice")
        if not choice or choice == "escalate":
            continue
        gold = row.get("gold", row.get("golden_choice"))
        bucket = counts.setdefault(str(choice), [0, 0])
        bucket[1] += 1
        if gold is not None and str(choice) == str(gold):
            bucket[0] += 1

    ids = list(playbook_ids) if playbook_ids is not None else sorted(counts)
    precision: dict[str, float] = {}
    detail: dict[str, Any] = {}
    for pid in ids:
        if pid == "escalate":
            continue
        correct, n = counts.get(pid, [0, 0])
        empirical = (correct / n) if n else None
        if n < min_hits:
            pi_hat = float(fallback)
            method = "fallback_low_n"
        else:
            pi_hat = _wilson_lower(correct, n, z=z)
            method = "wilson_lower"
        precision[pid] = pi_hat
        detail[pid] = {
            "n": n,
            "correct": correct,
            "empirical": empirical,
            "pi_hat": pi_hat,
            "method": method,
            "min_hits": min_hits,
        }
    return {
        "per_label_precision": precision,
        "detail": detail,
        "min_hits": min_hits,
        "fallback": fallback,
        "z": z,
        "note": (
            f"π̂_c is the Wilson lower bound on cal choice precision when n≥{min_hits}; "
            f"otherwise fallback {fallback} (fail-closed against catalog floors)."
        ),
    }


def score_mae(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Mean absolute error of blast ``score`` against ``score_blast_gold``."""
    errs: list[float] = []
    for row in rows:
        gold = row.get("score_blast_gold")
        pred = row.get("score")
        if gold is None or pred is None:
            continue
        try:
            errs.append(abs(float(pred) - float(gold)))
        except (TypeError, ValueError):
            continue
    return {
        "n": len(errs),
        "mae": (sum(errs) / len(errs)) if errs else None,
    }


def noul_ece(rows: list[dict[str, Any]], *, n_bins: int = 5) -> dict[str, Any]:
    """Expected calibration error of noul against the binary ``noul_safe`` label."""
    pairs: list[tuple[float, float]] = []
    for row in rows:
        noul = row.get("noul")
        safe = row.get("noul_safe")
        if noul is None or safe is None:
            continue
        try:
            p = min(1.0, max(0.0, float(noul)))
        except (TypeError, ValueError):
            continue
        pairs.append((p, 1.0 if safe else 0.0))
    if not pairs:
        return {"n": 0, "ece": None, "n_bins": n_bins}
    bins: list[list[tuple[float, float]]] = [[] for _ in range(n_bins)]
    for p, y in pairs:
        idx = min(n_bins - 1, int(p * n_bins))
        if p >= 1.0:
            idx = n_bins - 1
        bins[idx].append((p, y))
    ece = 0.0
    n = len(pairs)
    for bucket in bins:
        if not bucket:
            continue
        conf = sum(p for p, _ in bucket) / len(bucket)
        acc = sum(y for _, y in bucket) / len(bucket)
        ece += (len(bucket) / n) * abs(acc - conf)
    return {"n": n, "ece": ece, "n_bins": n_bins}


def latency_ms_from_usage(
    usage: dict[str, Any] | None,
    raw: dict[str, Any] | None = None,
) -> float | None:
    """Milliseconds from a backend usage/raw payload, if it carries a duration.

    Explicit ``latency_ms`` / ``total_ms`` / ``duration_ms`` win. Otherwise
    Ollama's ``total_duration`` (nanoseconds) is converted. Returns None when
    the payload has no duration field — callers may fall back to a wall clock.
    """
    blobs: list[dict[str, Any]] = []
    if isinstance(usage, dict):
        blobs.append(usage)
    if isinstance(raw, dict):
        inner = raw.get("usage")
        if isinstance(inner, dict) and inner is not usage:
            blobs.append(inner)
        blobs.append(raw)
    for blob in blobs:
        for key in ("latency_ms", "total_ms", "duration_ms"):
            if blob.get(key) is None:
                continue
            try:
                return float(blob[key])
            except (TypeError, ValueError):
                continue
    for blob in blobs:
        val = blob.get("total_duration")
        if isinstance(val, (int, float)) and val > 0:
            return float(val) / 1_000_000.0
    return None


def rule_baseline_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Accuracy of :func:`alert_name_rule_baseline` against ``golden_choice``."""
    n = 0
    correct = 0
    for rec in records:
        gold = rec.get("golden_choice")
        if not gold:
            continue
        n += 1
        if alert_name_rule_baseline(rec) == gold:
            correct += 1
    return {
        "n": n,
        "correct": correct,
        "accuracy": (correct / n) if n else 0.0,
        "note": (
            "Fixed alertname→playbook map. Unmapped alerts count as incorrect. "
            "Not a System One result."
        ),
    }


def alert_name_rule_baseline(rec: dict[str, Any]) -> str | None:
    """Classical alertname→playbook router (fails on ambiguity slices)."""
    alert = (rec.get("state") or {}).get("alert") or {}
    name = alert.get("alertname") or ""
    mapping = {
        "Http502High": "restart_php_fpm",
        "NginxUpstreamErrors": "restart_nginx",
        "DiskAlmostFull": "clear_tmp_disk",
        "LogVolumeHigh": "rotate_app_logs",
        "RedisDown": "restart_redis_local",
        "DNSResolutionFail": "flush_dns_cache",
        "SshdConfigPending": "reload_sshd_config",
        "ClockSkew": "restart_chrony",
        "OOMPressure": "enable_swap_emergency",
        "CronRunaway": "disable_cron_job",
        "ContainerUnhealthy": "restart_docker_container",
        "Fail2banFalsePositive": "unblock_fail2ban_ip",
    }
    return mapping.get(name)
