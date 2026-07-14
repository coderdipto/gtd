from datetime import datetime, time, timedelta

from dateutil.rrule import rrulestr
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .google_calendar import GoogleCalendarClient, get_credential
from .models import Area, RecurringTemplate, Task

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


_FREQ_LABELS = {"DAILY": "Daily", "WEEKLY": "Weekly", "MONTHLY": "Monthly", "YEARLY": "Yearly"}
_FREQ_UNITS = {"DAILY": "day", "WEEKLY": "week", "MONTHLY": "month", "YEARLY": "year"}


def humanize_rrule(rrule_str):
    """'FREQ=WEEKLY;BYDAY=MO' -> 'Weekly on Mon' - the raw RFC5545 string is
    exactly correct but not something a user should have to read (recurring.html
    and recurring_detail.html were showing it verbatim). Falls back to the raw
    string for anything build_rrule() wouldn't itself produce, rather than
    raising, since a template filter shouldn't 500 a page over a display nicety."""
    try:
        fields = parse_rrule(rrule_str)
        freq, interval, byday = fields["freq"], fields["interval"], fields["byday"]
        label = f"Every {interval} {_FREQ_UNITS[freq]}s" if interval > 1 else _FREQ_LABELS[freq]
    except KeyError:
        return rrule_str
    if freq == "WEEKLY" and byday:
        label += " on " + ", ".join(WEEKDAY_LABELS.get(d, d) for d in byday)
    return label


def _next_occurrence_date(template, today):
    """First date on/after today matching the template's RRULE - used as the
    seed occurrence for its one recurring GCal event (solution-plan.md Step 7:
    'one recurring GCal event ... mirroring the RRULE')."""
    rule = rrulestr(f"RRULE:{template.rrule}", dtstart=datetime.combine(today, time.min))
    next_dt = rule.after(datetime.combine(today, time.min), inc=True)
    return next_dt.date() if next_dt else today


def _sync_gcal_event(template):
    """Calendar linkage (solution-plan.md Step 7/8): a standing-block template
    gets ONE recurring GCal event mirroring its RRULE (never per-instance
    TimeBlocks). No-op when Google Calendar isn't connected."""
    credential = get_credential()
    if not credential:
        return
    client = GoogleCalendarClient(credential)

    has_standing_block = template.active and template.block_start_time and template.block_duration_min
    if not has_standing_block:
        if template.gcal_event_id:
            client.delete_event(credential.gtd_calendar_id, template.gcal_event_id)
            template.gcal_event_id = ""
            template.save(update_fields=["gcal_event_id"])
        return

    today = timezone.localtime().date()
    start = datetime.combine(_next_occurrence_date(template, today), template.block_start_time)
    if timezone.is_naive(start):
        start = timezone.make_aware(start)
    end = start + timedelta(minutes=template.block_duration_min)
    body = {
        "summary": template.title,
        "start": {"dateTime": start.isoformat()},
        "end": {"dateTime": end.isoformat()},
        "recurrence": [f"RRULE:{template.rrule}"],
    }
    if template.gcal_event_id:
        client.patch_event(credential.gtd_calendar_id, template.gcal_event_id, body)
    else:
        result = client.insert_event(credential.gtd_calendar_id, body)
        template.gcal_event_id = result.get("id", "")
        template.save(update_fields=["gcal_event_id"])


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
    block_start_time_str = request.POST.get("block_start_time") or None
    # Parsed to a real time object rather than left as the raw "HH:MM" string -
    # Django's TimeField only coerces strings->time on the way out of the DB,
    # not on plain attribute assignment, and _sync_gcal_event below needs a
    # real time for datetime.combine() on this same in-memory instance.
    block_start_time = time.fromisoformat(block_start_time_str) if block_start_time_str else None
    block_duration_min_str = request.POST.get("block_duration_min") or None
    block_duration_min = int(block_duration_min_str) if block_duration_min_str else None

    if template is None:
        template = RecurringTemplate()
    template.title = title
    template.description = request.POST.get("description", "")
    template.rrule = rrule_str
    template.area_id = area_id
    template.block_start_time = block_start_time
    template.block_duration_min = block_duration_min
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
    _sync_gcal_event(template)  # deletes the GCal event if one exists
    return redirect("recurring_detail", pk=template.id)


@login_required
@require_POST
def recurring_activate(request, pk):
    template = get_object_or_404(RecurringTemplate, pk=pk)
    template.active = True
    template.save(update_fields=["active"])
    _sync_gcal_event(template)  # re-creates the GCal event if there's a standing block
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
