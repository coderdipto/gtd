from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import Area, GoogleCredential, RecurringTemplate, Task

FREQUENCIES = ["DAILY", "WEEKLY", "MONTHLY", "YEARLY"]
WEEKDAYS = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]
WEEKDAY_LABELS = {"MO": "Mon", "TU": "Tue", "WE": "Wed", "TH": "Thu", "FR": "Fri", "SA": "Sat", "SU": "Sun"}


def build_rrule(freq, byday=None, interval=1):
    """Rule builder (frequency/weekday/interval) -> RFC5545 RRULE string
    (solution-plan.md Step 7). byday only applies to WEEKLY."""
    parts = [f"FREQ={freq}"]
    if freq == "WEEKLY" and byday:
        parts.append(f"BYDAY={','.join(byday)}")
    try:
        interval = int(interval)
    except (TypeError, ValueError):
        interval = 1
    if interval > 1:
        parts.append(f"INTERVAL={interval}")
    return ";".join(parts)


def parse_rrule(rrule_str):
    """Inverse of build_rrule, to pre-fill the edit form (RRULE round-trip)."""
    fields = dict(part.split("=", 1) for part in rrule_str.split(";") if "=" in part)
    return {
        "freq": fields.get("FREQ", "WEEKLY"),
        "byday": fields.get("BYDAY", "").split(",") if fields.get("BYDAY") else [],
        "interval": int(fields.get("INTERVAL", 1)),
    }


def _sync_gcal_event(template):
    # Calendar linkage (solution-plan.md Step 7) needs Epic 8's GoogleCredential
    # + Calendar API client, which don't exist yet - every GCal call is gated
    # on a connected credential (see task-breakdown.md Epic 8's rollback note),
    # so this is a deliberate no-op until then.
    if not GoogleCredential.objects.exists():
        return
    raise NotImplementedError("Google Calendar sync lands in Epic 8")


@login_required
def recurring_view(request):
    templates = RecurringTemplate.objects.order_by("title")
    return render(request, "core/recurring.html", {"templates": templates})


def _template_form_context(request, template=None):
    initial = parse_rrule(template.rrule) if template else {"freq": "WEEKLY", "byday": [], "interval": 1}
    return {
        "template": template,
        "areas": Area.objects.all(),
        "frequencies": FREQUENCIES,
        "weekdays": WEEKDAYS,
        "weekday_labels": WEEKDAY_LABELS,
        "initial": initial,
    }


@login_required
def recurring_create(request):
    if request.method == "POST":
        return _save_template(request)
    return render(request, "core/recurring_form.html", _template_form_context(request))


@login_required
def recurring_edit(request, pk):
    template = get_object_or_404(RecurringTemplate, pk=pk)
    if request.method == "POST":
        return _save_template(request, template)
    return render(request, "core/recurring_form.html", _template_form_context(request, template))


def _save_template(request, template=None):
    title = request.POST.get("title", "").strip()
    if not title:
        context = _template_form_context(request, template)
        context["error"] = "Title is required."
        return render(request, "core/recurring_form.html", context)

    freq = request.POST.get("freq", "WEEKLY")
    byday = request.POST.getlist("byday")
    interval = request.POST.get("interval") or 1
    rrule_str = build_rrule(freq, byday, interval)

    area_id = request.POST.get("area") or None
    block_start_time = request.POST.get("block_start_time") or None
    block_duration_min = request.POST.get("block_duration_min") or None

    if template is None:
        template = RecurringTemplate()
    template.title = title
    template.description = request.POST.get("description", "")
    template.rrule = rrule_str
    template.area_id = area_id
    template.block_start_time = block_start_time
    template.block_duration_min = block_duration_min or None
    template.save()
    _sync_gcal_event(template)
    return redirect("recurring_detail", pk=template.id)


@login_required
def recurring_detail(request, pk):
    template = get_object_or_404(RecurringTemplate, pk=pk)
    today = timezone.localtime().date()
    instances = list(
        Task.objects.filter(recurring_template=template).order_by("-occurrence_date")
    )
    overdue_count = Task.objects.filter(
        recurring_template=template, occurrence_date__lt=today, completed_at__isnull=True
    ).count()
    return render(
        request,
        "core/recurring_detail.html",
        {"template": template, "instances": instances, "overdue_count": overdue_count},
    )


@login_required
@require_POST
def recurring_deactivate(request, pk):
    template = get_object_or_404(RecurringTemplate, pk=pk)
    template.active = False
    template.save(update_fields=["active"])
    _sync_gcal_event(template)  # no-op until Epic 8; will delete the GCal event then
    return redirect("recurring_detail", pk=template.id)


@login_required
@require_POST
def recurring_activate(request, pk):
    template = get_object_or_404(RecurringTemplate, pk=pk)
    template.active = True
    template.save(update_fields=["active"])
    return redirect("recurring_detail", pk=template.id)


@login_required
@require_POST
def recurring_complete_overdue(request, pk):
    today = timezone.localtime().date()
    Task.objects.filter(recurring_template_id=pk, occurrence_date__lt=today, completed_at__isnull=True).update(
        completed_at=timezone.now()
    )
    return redirect("recurring_detail", pk=pk)


@login_required
@require_POST
def recurring_trash_overdue(request, pk):
    today = timezone.localtime().date()
    Task.objects.filter(recurring_template_id=pk, occurrence_date__lt=today, completed_at__isnull=True).update(
        list=Task.List.TRASH, trashed_at=timezone.now()
    )
    return redirect("recurring_detail", pk=pk)
