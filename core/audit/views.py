"""Log page views, superuser only (FR-L5). Owner: Sunil (Phase 3).

Produces the same keys as `core/sample_context.py` ("Log").
"""

from django.contrib.auth.decorators import user_passes_test
from django.shortcuts import get_object_or_404, render

from core.audit.models import QueryLog

superuser_required = user_passes_test(lambda u: u.is_superuser)

RULE_CHOICES = [f"R{i}" for i in range(1, 12)]
VERDICT_CHOICES = ["answered", "blocked", "failed"]


def _stopped_by(entry: QueryLog) -> str:
    """Who stopped the question, worked out from the verdict and attempts."""
    if entry.verdict == "answered":
        return "none"
    if entry.verdict == "blocked":
        return "validator"
    attempts = entry.attempts_json or []
    if not attempts:
        return "service"
    if attempts[-1].get("sql") is None:
        return "model"
    return "database"


def _entry_dict(e: QueryLog) -> dict:
    return {
        "id": e.id,
        "created_at": e.created_at,
        "connection_name": e.connection.name,
        "question": e.question,
        "verdict": e.verdict,
        "stopped_by": _stopped_by(e),
        "rules_fired": e.rules_fired,
        "attempt_count": e.attempt_count,
        "rows_returned": e.rows_returned,
        "exec_ms": e.exec_ms,
        "anomaly_flags": e.anomaly_flags,
    }


@superuser_required
def log(request):
    verdict = request.GET.get("verdict", "")
    rule = request.GET.get("rule", "")

    rows = QueryLog.objects.select_related("connection")
    if verdict:
        rows = rows.filter(verdict=verdict)

    entries = [_entry_dict(e) for e in rows]
    if rule:
        entries = [e for e in entries if rule in e["rules_fired"]]

    return render(request, "log.html", {
        "entries": entries,
        "filters": {"verdict": verdict, "rule": rule},
        "verdict_choices": VERDICT_CHOICES,
        "rule_choices": RULE_CHOICES,
    })


@superuser_required
def log_detail(request, entry_id):
    e = get_object_or_404(QueryLog.objects.select_related("connection"), pk=entry_id)

    attempts = []
    for a in e.attempts_json or []:
        v = a.get("verdict")
        hits = v["hits"] if v else []
        attempts.append({
            "number": a.get("number"),
            "sql": a.get("sql"),
            "explanation": a.get("explanation", ""),
            "verdict": "" if not v else ("ALLOW" if v["allowed"] else "BLOCK"),
            "rules_fired": [h["rule_id"] for h in hits],
            "messages": [h["message"] for h in hits if h["action"] == "block"],
            "error": a.get("error") or "",
            "exec_ms": a.get("exec_ms"),
        })

    entry = {
        **_entry_dict(e),
        "final_sql": e.final_sql,
        "plan": e.plan_json or [],
        "attempts": attempts,
    }
    return render(request, "log_detail.html", {"entry": entry})