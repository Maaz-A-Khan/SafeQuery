"""Log page views, superuser only (FR-L5). Owner: Sunil (Phase 3).

Produces the same keys as `core/sample_context.py` ("Log"). `?state=<name>`
still renders the sample context, so the templates can be built without data.
"""

from django.contrib.auth.decorators import user_passes_test
from django.shortcuts import get_object_or_404, render

from agent.types import Outcome
from core import sample_context
from core.audit.models import QueryLog

superuser_required = user_passes_test(lambda u: u.is_superuser)

RULE_CHOICES = [f"R{i}" for i in range(1, 12)]
VERDICT_CHOICES = [o.value for o in Outcome]
LOG_PAGE_LIMIT = 500   # newest entries shown; older ones stay in the database and admin


def _entry_dict(e: QueryLog) -> dict:
    return {
        "id": e.id,
        "created_at": e.created_at,
        "connection_name": e.connection.name,
        "question": e.question,
        "verdict": e.verdict,
        "stopped_by": e.stopped_by,
        "from_cache": e.from_cache,
        "rules_fired": e.rules_fired,
        "attempt_count": e.attempt_count,
        "rows_returned": e.rows_returned,
        "exec_ms": e.exec_ms,
        "anomaly_flags": e.anomaly_flags,
    }


@superuser_required
def log(request):
    if "state" in request.GET:
        return render(request, "log.html", sample_context.log(request.GET["state"]))
    verdict = request.GET.get("verdict", "")
    rule = request.GET.get("rule", "")

    rows = QueryLog.objects.select_related("connection").order_by("-created_at")
    if verdict in VERDICT_CHOICES:
        rows = rows.filter(verdict=verdict)
    if rule in RULE_CHOICES:
        rows = rows.filter(rules_fired__contains=[rule])   # JSON containment, done in PostgreSQL

    return render(request, "log.html", {
        "entries": [_entry_dict(e) for e in rows[:LOG_PAGE_LIMIT]],
        "filters": {"verdict": verdict, "rule": rule},
        "verdict_choices": VERDICT_CHOICES,
        "rule_choices": RULE_CHOICES,
    })


@superuser_required
def log_detail(request, entry_id: int):
    if "state" in request.GET:
        return render(request, "log_detail.html", sample_context.log_detail(request.GET["state"]))
    e = get_object_or_404(QueryLog.objects.select_related("connection"), pk=entry_id)

    attempts = []
    for a in e.attempts_json or []:
        v = a.get("verdict")
        hits = (v or {}).get("hits", [])
        attempts.append({
            "number": a.get("number"),
            "sql": a.get("sql"),
            "explanation": a.get("explanation", ""),
            "verdict": "" if not v else ("ALLOW" if v.get("allowed") else "BLOCK"),
            "rules_fired": [h["rule_id"] for h in hits],
            "messages": [h["message"] for h in hits],
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
