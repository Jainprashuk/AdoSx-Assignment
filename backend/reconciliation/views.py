"""
The HTTP layer: read a query string, call a service, serialise, return.

No logic lives here. Scoping is in services.py and the rules are in compare.py,
so a view that looks thin is a view that is doing its job.

Plain JsonResponse rather than a framework. Four endpoints returning
dictionaries do not need a serialiser layer, and an added dependency is
something to justify rather than reach for.
"""

from __future__ import annotations

import io
from decimal import Decimal

from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods

from .compare import REASONS, Disagreement
from .ingest import (
    LOCATIONS_FILE, SYSTEM_A_FILE, SYSTEM_B_FILE, ImportAborted, import_batch,
)
from .models import Batch, Entry, ImportIssue, Org, Record
from .services import REASON_LABELS, ScopeError, filter_and_sort, load_org_view

# The three files an upload must supply, named as they are in the brief.
UPLOAD_FIELDS = (LOCATIONS_FILE, SYSTEM_A_FILE, SYSTEM_B_FILE)


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


# No CSRF token on the upload. There is no authentication in this project --
# the brief says to skip it entirely -- so there is no session for a forged
# request to borrow: the worst a hostile page could do is create a batch, which
# any visitor can already do through the form. The README says this out loud
# rather than letting it look like an oversight. Restoring CSRF is one
# decorator plus sending the cookie back, and that is what the real version
# would do the moment a login existed.
@csrf_exempt
@require_http_methods(["GET", "POST"])
def batches(request: HttpRequest) -> JsonResponse:
    """GET: every batch, newest first. POST: load three CSVs as a new batch."""
    if request.method == "POST":
        return _create_batch(request)

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


def _create_batch(request: HttpRequest) -> JsonResponse:
    """Load an uploaded set of three CSVs as a new batch.

    Reuses `import_batch` exactly as the management command does -- which is
    why ingestion takes file objects rather than paths. The dirty-data
    behaviour, the row-count invariant and the issue log are the same code
    here as in the seed, so there is no second importer to keep in agreement.

    A new batch never touches an existing one: batches are closed worlds, so a
    reviewer's upload cannot disturb the seeded sample data.
    """
    missing = [name for name in UPLOAD_FIELDS if name not in request.FILES]
    if missing:
        return JsonResponse(
            {"error": f"all three files are required; missing {', '.join(missing)}"},
            status=400,
        )

    # utf-8-sig strips a byte-order mark from a spreadsheet export; newline=""
    # leaves line endings to the csv module, which is what handles a quoted
    # value containing a newline.
    handles = {
        name: io.TextIOWrapper(request.FILES[name].file, encoding="utf-8-sig", newline="")
        for name in UPLOAD_FIELDS
    }
    # Just "Uploaded". The time is already on the batch as `created_at`, and
    # the frontend renders it in the viewer's own timezone -- a timestamp
    # baked into the label here would be the server's timezone (UTC), which is
    # the wrong time for whoever is reading it.
    label = "Uploaded"

    try:
        summary = import_batch(
            label,
            handles[LOCATIONS_FILE],
            handles[SYSTEM_A_FILE],
            handles[SYSTEM_B_FILE],
        )
    except ImportAborted as exc:
        # The transaction has already rolled back, so there is no half-loaded
        # batch to clean up. 400 rather than 500: the upload is the problem,
        # and the message says which line of which file.
        return JsonResponse({"error": str(exc)}, status=400)
    except UnicodeDecodeError:
        return JsonResponse(
            {"error": "one of the files is not text this importer can read (expected UTF-8 CSV)"},
            status=400,
        )

    batch = Batch.objects.get(pk=summary.batch_id)
    return JsonResponse(
        {
            "batch": {"id": batch.pk, "label": batch.label},
            "files": [
                {
                    "name": file_summary.name,
                    "rows_read": file_summary.rows_read,
                    "rows_written": file_summary.rows_written,
                    "issues": file_summary.issues,
                }
                for file_summary in summary.files
            ],
            # Every logged problem, not a count. The claim is that nothing was
            # dropped, and the evidence for it is the list.
            "issues": [
                {
                    "source_file": issue.source_file,
                    "line_number": issue.line_number,
                    "field": issue.field,
                    "raw_value": issue.raw_value,
                    "problem": issue.problem,
                }
                for issue in ImportIssue.objects.filter(batch=batch)
            ],
        },
        status=201,
    )


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
