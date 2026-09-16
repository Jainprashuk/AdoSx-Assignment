"""
The HTTP layer: read a query string, call a service, serialise, return.

No logic lives here. Scoping is in services.py and the rules are in compare.py,
so a view that looks thin is a view that is doing its job.

Plain JsonResponse rather than a framework. Three read-only endpoints returning
dictionaries do not need a serialiser layer, and an added dependency is
something to justify rather than reach for.
"""

from __future__ import annotations

from decimal import Decimal

from django.http import HttpRequest, JsonResponse
from django.views.decorators.http import require_GET

from .compare import REASONS, Disagreement
from .models import Batch, Entry, ImportIssue, Org, Record
from .services import REASON_LABELS, ScopeError, filter_and_sort, load_org_view


def _money(value: Decimal | None) -> str | None:
    """Serialise money as a string.

    JSON numbers are IEEE doubles, so a Decimal sent as a number arrives in the
    browser as a float and 156337.55 can come back as 156337.549999. Every
    amount here crosses the wire as a string and is never arithmetic in
    JavaScript -- the one place a difference is needed, the API computes it.
    """
    return None if value is None else str(value)


def _disagreement(item: Disagreement) -> dict:
    return {
        "reason": item.reason,
        "reason_label": REASON_LABELS[item.reason],
        "key": item.key,
        "record_id": item.record_id,
        "location_code": item.location_code,
        "a_value": _money(item.a_value),
        "a_value_raw": item.a_value_raw,
        "b_value": _money(item.b_value),
        "b_value_raw": item.b_value_raw,
        "difference": _money(item.difference),
        "entry_ids": list(item.entry_ids),
        "detail": item.detail,
        "source_lines": list(item.source_lines),
    }


@require_GET
def batches(request: HttpRequest) -> JsonResponse:
    """Every batch, newest first. No org scoping: a batch is a container, and
    its label and row counts say nothing about any org's data."""
    rows = []
    for batch in Batch.objects.all():
        rows.append({
            "id": batch.pk,
            "label": batch.label,
            "created_at": batch.created_at.isoformat(),
            "records": Record.objects.filter(batch=batch).count(),
            "entries": Entry.objects.filter(batch=batch).count(),
            "issues": ImportIssue.objects.filter(batch=batch).count(),
        })
    return JsonResponse({"batches": rows})


@require_GET
def orgs(request: HttpRequest) -> JsonResponse:
    """The orgs in one batch. Requires a batch: orgs are batch-scoped, and a
    list across batches would offer selections that cannot be honoured."""
    batch_id = request.GET.get("batch")
    if not batch_id:
        return JsonResponse({"error": "a batch must be named"}, status=400)

    if not Batch.objects.filter(pk=batch_id).exists():
        return JsonResponse({"error": f"no batch {batch_id!r}"}, status=400)

    rows = [
        {"id": org.pk, "code": org.org_code}
        for org in Org.objects.filter(batch_id=batch_id)
    ]
    return JsonResponse({"orgs": rows})


@require_GET
def discrepancies(request: HttpRequest) -> JsonResponse:
    """One org's disagreements in one batch.

    Both `batch` and `org` are required and a missing one is a 400, not a
    default. The brief's hard rule is that a row belonging to one tenant must
    never be visible to another, and the only way to be sure of that is to
    refuse to answer a question that does not say whose data it is about.
    """
    try:
        view = load_org_view(request.GET.get("batch"), request.GET.get("org"))
        rows = filter_and_sort(
            view.disagreements,
            reason=request.GET.get("reason"),
            sort=request.GET.get("sort"),
        )
    except ScopeError as exc:
        return JsonResponse({"error": str(exc)}, status=400)

    return JsonResponse({
        "batch": {"id": view.batch.pk, "label": view.batch.label},
        "org": {"id": view.org.pk, "code": view.org.org_code},
        "total": len(view.disagreements),
        # Counts are of the whole org view, not of the filtered rows, so the
        # filter can show what each choice would give before it is chosen.
        "counts": [
            {"reason": reason, "label": REASON_LABELS[reason], "count": view.counts[reason]}
            for reason in REASONS
        ],
        "disagreements": [_disagreement(item) for item in rows],
        "issues": [
            {
                "source_file": issue.source_file,
                "line_number": issue.line_number,
                "field": issue.field,
                "raw_value": issue.raw_value,
                "problem": issue.problem,
            }
            for issue in view.issues
        ],
    })
