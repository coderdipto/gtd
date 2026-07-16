from datetime import datetime, time as _time, timedelta

from django.contrib.auth.decorators import login_required
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .google_calendar import GoogleCalendarClient, get_credential
from .models import Area, InboxItem, ReviewConfig, ReviewSession, Task, TimeBlock

WEEKLY_PHASES = ["get_clear", "projects", "carryover", "waiting", "calendar", "eisenhower", "creative"]
MONTHLY_PHASES = ["areas", "someday", "carryover"]
SIMPLE_PHASES = {"quarterly": ["checklist"], "yearly": ["checklist"]}

PHASES_BY_CADENCE = {
    "weekly": WEEKLY_PHASES,
    "monthly": MONTHLY_PHASES,
    "quarterly": SIMPLE_PHASES["quarterly"],
    "yearly": SIMPLE_PHASES["yearly"],
}

CADENCE_WEEKDAY_RRULE = {
    ReviewConfig.Cadence.WEEKLY: lambda cfg: f"FREQ=WEEKLY;BYDAY={_WEEKDAY_CODES[cfg.weekday]}",
    ReviewConfig.Cadence.MONTHLY: lambda cfg: f"FREQ=MONTHLY;BYDAY=1{_WEEKDAY_CODES[cfg.weekday]}",
    ReviewConfig.Cadence.QUARTERLY: lambda cfg: f"FREQ=MONTHLY;INTERVAL=3;BYDAY=1{_WEEKDAY_CODES[cfg.weekday]}",
    ReviewConfig.Cadence.YEARLY: lambda cfg: f"FREQ=YEARLY;BYDAY=1{_WEEKDAY_CODES[cfg.weekday]}",
}
_WEEKDAY_CODES = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]

QUARTERLY_YEARLY_PROMPTS = {
    "quarterly": [
        "What are your 1-2 year goals? Are you still moving toward them?",
        "What's working in your system? What's not?",
        "Anything to start, stop, or change this quarter?",
    ],
    "yearly": [
        "Revisit your vision and principles - still true?",
        "What horizon-level roles (Areas) need attention this year?",
        "What would make next year a clear success?",
    ],
}


# --- Setup / dashboard -----------------------------------------------------


@login_required
def review_dashboard(request):
    configs = {c.cadence: c for c in ReviewConfig.objects.all()}
    onboarding_incomplete = len(configs) < len(ReviewConfig.Cadence.choices)
    last_sessions = {}
    for cadence, _label in ReviewConfig.Cadence.choices:
        last = (
            ReviewSession.objects.filter(cadence=cadence, completed_at__isnull=False)
            .order_by("-completed_at")
            .first()
        )
        last_sessions[cadence] = last
    in_progress = {
        s.cadence: s for s in ReviewSession.objects.filter(completed_at__isnull=True)
    }
    return render(
        request,
        "core/review_dashboard.html",
        {
            "configs": configs,
            "onboarding_incomplete": onboarding_incomplete,
            "cadences": ReviewConfig.Cadence.choices,
            "last_sessions": last_sessions,
            "in_progress": in_progress,
            "weekday_choices": list(enumerate(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"])),
        },
    )


@login_required
@require_POST
def review_config_save(request, cadence):
    config, _created = ReviewConfig.objects.get_or_create(cadence=cadence)
    weekday = request.POST.get("weekday")
    time_str = request.POST.get("time")
    duration = request.POST.get("duration_min")
    if weekday:
        config.weekday = int(weekday)
    if time_str:
        # Parsed now, not left as a raw string - _sync_review_gcal_event below
        # calls datetime.combine() on this same in-memory instance, and
        # Django's TimeField only coerces str->time on the way out of the DB.
        config.time = _time.fromisoformat(time_str)
    if duration:
        config.duration_min = int(duration)
    config.save()
    _sync_review_gcal_event(config)
    return redirect("review_dashboard")


def _sync_review_gcal_event(config):
    credential = get_credential()
    if not credential:
        return
    client = GoogleCalendarClient(credential)
    today = timezone.localtime().date()
    rrule = CADENCE_WEEKDAY_RRULE[config.cadence](config)
    start_date = today + timedelta(days=(config.weekday - today.weekday()) % 7)
    start = datetime.combine(start_date, config.time)
    if timezone.is_naive(start):
        start = timezone.make_aware(start)
    end = start + timedelta(minutes=config.duration_min)
    body = {
        "summary": f"🔁 GTD {config.get_cadence_display()} Review",
        "start": {"dateTime": start.isoformat()},
        "end": {"dateTime": end.isoformat()},
        "recurrence": [f"RRULE:{rrule}"],
    }
    if config.gcal_event_id:
        client.patch_event(credential.gtd_calendar_id, config.gcal_event_id, body)
    else:
        result = client.insert_event(credential.gtd_calendar_id, body)
        config.gcal_event_id = result.get("id", "")
        config.save(update_fields=["gcal_event_id"])


@login_required
@require_POST
def review_config_delete(request, cadence):
    config = ReviewConfig.objects.filter(cadence=cadence).first()
    if config:
        credential = get_credential()
        if credential and config.gcal_event_id:
            GoogleCalendarClient(credential).delete_event(credential.gtd_calendar_id, config.gcal_event_id)
        config.delete()
    return redirect("review_dashboard")


# --- Session helpers --------------------------------------------------------


def _get_or_create_session(cadence):
    session = (
        ReviewSession.objects.filter(cadence=cadence, completed_at__isnull=True)
        .order_by("-started_at")
        .first()
    )
    if not session:
        phases = PHASES_BY_CADENCE[cadence]
        session = ReviewSession.objects.create(cadence=cadence, phase_state={"phase": phases[0]})
    return session


def _advance(session, phases, current_phase):
    idx = phases.index(current_phase)
    if idx + 1 < len(phases):
        session.phase_state["phase"] = phases[idx + 1]
        session.save(update_fields=["phase_state"])
        return phases[idx + 1]
    return None  # last phase - caller finishes the session


def _streak(cadence):
    """Consecutive completed sessions for this cadence, most-recent-first,
    with no gaps in ReviewSession history (a simple, honest streak - not
    calendar-period-aware)."""
    sessions = list(
        ReviewSession.objects.filter(cadence=cadence, completed_at__isnull=False).order_by("-completed_at")
    )
    return len(sessions)


# --- Weekly wizard -----------------------------------------------------------


@login_required
def review_weekly_start(request):
    session = _get_or_create_session("weekly")
    return redirect("review_weekly_phase", phase=session.phase_state.get("phase", WEEKLY_PHASES[0]))


@login_required
def review_weekly_phase(request, phase):
    session = _get_or_create_session("weekly")
    current = session.phase_state.get("phase", WEEKLY_PHASES[0])
    if phase != current:
        return redirect("review_weekly_phase", phase=current)

    handler = _WEEKLY_HANDLERS[phase]
    return handler(request, session)


def _phase_index(phase):
    return WEEKLY_PHASES.index(phase) + 1


def _render_phase(request, session, phase, template, context):
    context.update(
        {
            "session": session,
            "phase": phase,
            "step": _phase_index(phase),
            "total": len(WEEKLY_PHASES),
        }
    )
    return render(request, template, context)


def _weekly_get_clear(request, session):
    if request.method == "POST":
        if "mind_sweep" in request.POST:
            for line in request.POST.get("mind_sweep", "").splitlines():
                line = line.strip()
                if line:
                    InboxItem.objects.create(title=line, source="review")
            return redirect("review_weekly_phase", phase="get_clear")
        if "next" in request.POST:
            next_phase = _advance(session, WEEKLY_PHASES, "get_clear")
            return redirect("review_weekly_phase", phase=next_phase)

    inbox_count = InboxItem.objects.filter(processed_at__isnull=True).count()
    return _render_phase(request, session, "get_clear", "core/review/get_clear.html", {"inbox_count": inbox_count})


def _weekly_projects(request, session):
    if request.method == "POST" and "next" in request.POST:
        next_phase = _advance(session, WEEKLY_PHASES, "projects")
        return redirect("review_weekly_phase", phase=next_phase)

    from .projects import _project_state_badge

    projects = list(
        Task.objects.filter(is_project=True, completed_at__isnull=True)
        .prefetch_related(Prefetch("subtasks", queryset=Task.objects.order_by("sort_order", "id")))
        .order_by("title")
    )
    rows = [{"project": p, "badge": _project_state_badge(p)} for p in projects]
    return _render_phase(request, session, "projects", "core/review/projects.html", {"rows": rows})


def _weekly_carryover(request, session):
    task = Task.objects.filter(carried_over_count__gt=0, completed_at__isnull=True).order_by("id").first()
    if request.method == "POST" and "next" in request.POST and not task:
        next_phase = _advance(session, WEEKLY_PHASES, "carryover")
        return redirect("review_weekly_phase", phase=next_phase)
    return _render_phase(request, session, "carryover", "core/review/carryover.html", {"task": task})


@login_required
@require_POST
def review_carryover_resolve(request, pk, action):
    task = get_object_or_404(Task, pk=pk)
    if action == "keep":
        task.carried_over_count = 0
        task.save(update_fields=["carried_over_count"])
    elif action == "demote":
        task.horizon = Task.Horizon.ANYTIME
        task.carried_over_count = 0
        task.save(update_fields=["horizon", "carried_over_count"])
    elif action == "someday":
        task.list = Task.List.SOMEDAY
        task.carried_over_count = 0
        task.save(update_fields=["list", "carried_over_count"])
    elif action == "trash":
        task.list = Task.List.TRASH
        task.trashed_at = timezone.now()
        task.carried_over_count = 0
        task.save(update_fields=["list", "trashed_at", "carried_over_count"])
    return redirect("review_weekly_phase", phase="carryover")


def _weekly_waiting(request, session):
    if request.method == "POST" and "next" in request.POST:
        next_phase = _advance(session, WEEKLY_PHASES, "waiting")
        return redirect("review_weekly_phase", phase=next_phase)

    today = timezone.localtime().date()
    tasks = list(Task.objects.filter(list=Task.List.WAITING, completed_at__isnull=True))
    overdue = [t for t in tasks if t.waiting_since and (today - t.waiting_since).days >= t.follow_up_after_days]
    return _render_phase(request, session, "waiting", "core/review/waiting.html", {"overdue": overdue})


def _weekly_calendar(request, session):
    if request.method == "POST":
        if "capture" in request.POST:
            for line in request.POST.get("capture", "").splitlines():
                line = line.strip()
                if line:
                    InboxItem.objects.create(title=line, source="review")
            return redirect("review_weekly_phase", phase="calendar")
        if "next" in request.POST:
            next_phase = _advance(session, WEEKLY_PHASES, "calendar")
            return redirect("review_weekly_phase", phase=next_phase)

    today = timezone.localtime().date()
    upcoming = TimeBlock.objects.filter(
        start__date__gte=today, start__date__lte=today + timedelta(days=14)
    ).order_by("start")
    return _render_phase(request, session, "calendar", "core/review/calendar.html", {"upcoming": upcoming})


def _weekly_eisenhower(request, session):
    if request.method == "POST" and "next" in request.POST:
        next_phase = _advance(session, WEEKLY_PHASES, "eisenhower")
        return redirect("review_weekly_phase", phase=next_phase)

    from .projects import _next_line

    projects = list(
        Task.objects.filter(is_project=True, completed_at__isnull=True)
        .prefetch_related(Prefetch("subtasks", queryset=Task.objects.order_by("sort_order", "id")))
        .order_by("title")
    )
    next_lines = {p.id: _next_line(p) for p in projects}
    return _render_phase(
        request, session, "eisenhower", "core/review/eisenhower.html", {"projects": projects, "next_lines": next_lines}
    )


def _current_monday(today):
    return today - timedelta(days=today.weekday())


@login_required
@require_POST
def review_eisenhower_drop(request, pk, quadrant):
    """Per-quadrant drop action (solution-plan.md Step 9, Decision #3). Acts
    on the project's current resolved next action, not the project record
    itself (except Q3/Q4's 'whole project' options). Nothing about the board
    layout is ever persisted - only these resulting mutations are."""
    project = get_object_or_404(Task, pk=pk, is_project=True)
    today = timezone.localtime().date()
    _state, next_tasks = project.next_actions()
    next_task = next_tasks[0] if next_tasks else None

    if quadrant == "q1":
        has_commitment = next_task and (
            next_task.due_date and next_task.due_date <= today + timedelta(days=7)
            or next_task.blocks.filter(start__date__lte=today + timedelta(days=7)).exists()
        )
        return render(
            request,
            "core/partials/eisenhower_card_result.html",
            {"project": project, "quadrant": "q1", "has_commitment": has_commitment},
        )

    if quadrant == "q2":
        if next_task and request.POST.get("slot_start"):
            start = datetime.fromisoformat(request.POST["slot_start"])
            if timezone.is_naive(start):
                start = timezone.make_aware(start)
            TimeBlock.objects.create(task=next_task, start=start, end=start + timedelta(hours=1))
            next_task.q2_week = _current_monday(today) + timedelta(days=7)
            next_task.save(update_fields=["q2_week"])
            return render(
                request, "core/partials/eisenhower_card_result.html", {"project": project, "quadrant": "q2", "done": True}
            )
        return render(
            request, "core/partials/eisenhower_slot_picker.html", {"project": project}
        )

    if quadrant == "q3":
        action = request.POST.get("action")
        if not action:
            return render(request, "core/partials/eisenhower_choice.html", {"project": project, "quadrant": "q3"})
        if action == "waiting" and next_task:
            next_task.list = Task.List.WAITING
            next_task.waiting_since = today
            next_task.waiting_on = request.POST.get("waiting_on", "")
            next_task.save(update_fields=["list", "waiting_since", "waiting_on"])
        elif action == "someday":
            project.list = Task.List.SOMEDAY
            project.save(update_fields=["list"])
        return render(
            request, "core/partials/eisenhower_card_result.html", {"project": project, "quadrant": "q3", "done": True}
        )

    if quadrant == "q4":
        action = request.POST.get("action")
        if not action:
            return render(request, "core/partials/eisenhower_choice.html", {"project": project, "quadrant": "q4"})
        if action == "someday":
            project.list = Task.List.SOMEDAY
            project.save(update_fields=["list"])
        elif action == "trash":
            project.list = Task.List.TRASH
            project.trashed_at = timezone.now()
            project.save(update_fields=["list", "trashed_at"])
        return render(
            request, "core/partials/eisenhower_card_result.html", {"project": project, "quadrant": "q4", "done": True}
        )

    return redirect("review_weekly_phase", phase="eisenhower")


def _weekly_creative(request, session):
    if request.method == "POST":
        if "capture" in request.POST:
            for line in request.POST.get("capture", "").splitlines():
                line = line.strip()
                if line:
                    InboxItem.objects.create(title=line, source="review")
            return redirect("review_weekly_phase", phase="creative")
        if "big3" in request.POST or "set_big3" in request.POST:
            Task.objects.filter(big3=True).update(big3=False)
            ids = request.POST.getlist("big3")[:3]
            if ids:
                Task.objects.filter(id__in=ids).update(big3=True)
            return redirect("review_weekly_phase", phase="creative")
        if "finish" in request.POST:
            return _finish_session(request, session)

    someday_tasks = Task.objects.filter(list=Task.List.SOMEDAY, completed_at__isnull=True).order_by("title")
    candidates = Task.objects.filter(completed_at__isnull=True).exclude(list=Task.List.TRASH).order_by("title")
    return _render_phase(
        request,
        session,
        "creative",
        "core/review/creative.html",
        {"someday_tasks": someday_tasks, "candidates": candidates},
    )


def _finish_session(request, session):
    now = timezone.now()
    session.completed_at = now
    streak = _streak("weekly") + 1
    session.stats_snapshot = {
        "completed_at": now.isoformat(),
        "big3_count": Task.objects.filter(big3=True).count(),
        "streak": streak,
    }
    session.save(update_fields=["completed_at", "stats_snapshot"])
    return render(request, "core/review/finish.html", {"session": session, "streak": streak})


_WEEKLY_HANDLERS = {
    "get_clear": _weekly_get_clear,
    "projects": _weekly_projects,
    "carryover": _weekly_carryover,
    "waiting": _weekly_waiting,
    "calendar": _weekly_calendar,
    "eisenhower": _weekly_eisenhower,
    "creative": _weekly_creative,
}


# --- Monthly wizard ----------------------------------------------------------


@login_required
def review_monthly_start(request):
    session = _get_or_create_session("monthly")
    return redirect("review_monthly_phase", phase=session.phase_state.get("phase", MONTHLY_PHASES[0]))


@login_required
def review_monthly_phase(request, phase):
    session = _get_or_create_session("monthly")
    current = session.phase_state.get("phase", MONTHLY_PHASES[0])
    if phase != current:
        return redirect("review_monthly_phase", phase=current)
    return _MONTHLY_HANDLERS[phase](request, session)


def _monthly_render(request, session, phase, template, context):
    context.update({"session": session, "phase": phase, "step": MONTHLY_PHASES.index(phase) + 1, "total": len(MONTHLY_PHASES)})
    return render(request, template, context)


def _monthly_areas(request, session):
    if request.method == "POST":
        if "capture" in request.POST:
            for line in request.POST.get("capture", "").splitlines():
                line = line.strip()
                if line:
                    InboxItem.objects.create(title=line, source="review")
            return redirect("review_monthly_phase", phase="areas")
        if "next" in request.POST:
            next_phase = _advance(session, MONTHLY_PHASES, "areas")
            return redirect("review_monthly_phase", phase=next_phase)
    areas = Area.objects.all()
    return _monthly_render(request, session, "areas", "core/review/monthly_areas.html", {"areas": areas})


def _monthly_someday(request, session):
    if request.method == "POST" and "next" in request.POST:
        next_phase = _advance(session, MONTHLY_PHASES, "someday")
        return redirect("review_monthly_phase", phase=next_phase)
    someday_tasks = Task.objects.filter(list=Task.List.SOMEDAY, completed_at__isnull=True).order_by("title")
    return _monthly_render(request, session, "someday", "core/review/monthly_someday.html", {"someday_tasks": someday_tasks})


def _monthly_carryover(request, session):
    if request.method == "POST" and "finish" in request.POST:
        return _finish_session_generic(request, session, "monthly")
    tasks = Task.objects.filter(
        horizon=Task.Horizon.MONTH, carried_over_count__gt=0, completed_at__isnull=True
    ).order_by("id")
    return _monthly_render(request, session, "carryover", "core/review/monthly_carryover.html", {"tasks": tasks})


_MONTHLY_HANDLERS = {"areas": _monthly_areas, "someday": _monthly_someday, "carryover": _monthly_carryover}


def _finish_session_generic(request, session, cadence):
    now = timezone.now()
    session.completed_at = now
    streak = _streak(cadence) + 1
    session.stats_snapshot = {"completed_at": now.isoformat(), "streak": streak}
    session.save(update_fields=["completed_at", "stats_snapshot"])
    return render(request, "core/review/finish.html", {"session": session, "streak": streak})


# --- Quarterly / Yearly (static checklist + capture box) --------------------


@login_required
def review_simple_start(request, cadence):
    session = _get_or_create_session(cadence)
    return redirect("review_simple_phase", cadence=cadence, phase="checklist")


@login_required
def review_simple_phase(request, cadence, phase):
    session = _get_or_create_session(cadence)
    if request.method == "POST":
        if "capture" in request.POST:
            for line in request.POST.get("capture", "").splitlines():
                line = line.strip()
                if line:
                    InboxItem.objects.create(title=line, source="review")
            return redirect("review_simple_phase", cadence=cadence, phase="checklist")
        if "finish" in request.POST:
            return _finish_session_generic(request, session, cadence)
    return render(
        request,
        "core/review/simple_checklist.html",
        {"session": session, "cadence": cadence, "prompts": QUARTERLY_YEARLY_PROMPTS[cadence], "step": 1, "total": 1},
    )
