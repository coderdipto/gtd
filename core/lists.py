import calendar as calendar_module
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.db.models import OuterRef, Q, Subquery
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import Area, Tag, Task, TimeBlock

# --- shared helpers -----------------------------------------------------


def _today_local():
    return timezone.localtime().date()


def _current_monday(today):
    return today - timedelta(days=today.weekday())


def _task_meta(task, today):
    """Mono meta string for a row: due date, flagged overdue/today."""
    if not task.due_date:
        return ""
    if task.due_date < today:
        return f"overdue {task.due_date:%d %b}"
    if task.due_date == today:
        return "due today"
    return task.due_date.strftime("%d %b")


def _toggle_url(request, param, value):
    # Preserves every other active filter's query param while flipping just
    # this one - so filter chips compose (context + tag + horizon + area at
    # once) instead of resetting each other.
    params = request.GET.copy()
    if params.get(param) == str(value):
        params.pop(param, None)
    else:
        params[param] = value
    qs = params.urlencode()
    return f"{request.path}?{qs}" if qs else request.path


def _engage_base_qs():
    return Task.objects.filter(is_project=False, list=Task.List.NEXT, completed_at__isnull=True)


def _menu_moves(task):
    # "Move to ..." options for task_row.html's ⋮ menu - only offered on
    # NEXT-list tasks (Waiting/Someday/Trash rows carry their own dedicated
    # primary actions instead, see _waiting_actions and the someday/trash views).
    options = [
        ("someday", "Move to Someday"),
        ("waiting", "Move to Waiting For"),
        ("trash", "Move to Trash"),
    ]
    moves = [
        {"label": label, "url": reverse("task_move", args=[task.id, target])}
        for target, label in options
    ]
    moves.append({"label": "Convert to note", "url": reverse("task_convert_to_note", args=[task.id])})
    return moves


def _context_chips(request, param="context"):
    active = request.GET.get(param)
    return [
        {
            "label": str(t),
            "variant": "context",
            "active": active == t.name,
            "url": _toggle_url(request, param, t.name),
        }
        for t in Tag.objects.filter(is_context=True).order_by("name")
    ]


# --- Today / Week / Month -----------------------------------------------


@login_required
def today_view(request):
    today = _today_local()

    base = _engage_base_qs()
    block_start_sq = (
        TimeBlock.objects.filter(task=OuterRef("pk"), start__date=today).order_by("start").values("start")[:1]
    )
    curated = (
        base.filter(
            Q(horizon=Task.Horizon.TODAY)
            | Q(blocks__start__date=today)
            | Q(due_date__lte=today)
            | Q(recurring_template__isnull=False, occurrence_date__lte=today)
        )
        .distinct()
        .annotate(today_block_start=Subquery(block_start_sq))
        .order_by("-big3", "today_block_start", "sort_order", "id")
    )
    curated = list(curated)

    context_filter = request.GET.get("context")
    anytime_qs = base.filter(horizon=Task.Horizon.ANYTIME).exclude(id__in=[t.id for t in curated])
    if context_filter:
        anytime_qs = anytime_qs.filter(tags__name=context_filter, tags__is_context=True)
    anytime = list(anytime_qs.order_by("sort_order", "id").distinct())

    missed_blocks = TimeBlock.objects.filter(
        status=TimeBlock.Status.MISSED, task__completed_at__isnull=True
    ).select_related("task")

    return render(
        request,
        "core/today.html",
        {
            "curated": curated,
            "anytime": anytime,
            "missed_blocks": missed_blocks,
            "chips": _context_chips(request),
            "clear_url": request.path if context_filter else None,
            "meta": {t.id: _task_meta(t, today) for t in curated + anytime},
            "menu_moves": {t.id: _menu_moves(t) for t in curated + anytime},
        },
    )


def _horizon_view(request, template_name, horizon, window_end_fn):
    today = _today_local()
    window_end = window_end_fn(today)
    qs = (
        _engage_base_qs()
        .filter(Q(horizon=horizon) | Q(due_date__gte=today, due_date__lte=window_end))
        .distinct()
        .order_by("sort_order", "id")
    )
    tasks = list(qs)
    return render(
        request,
        template_name,
        {"tasks": tasks, "meta": {t.id: _task_meta(t, today) for t in tasks}},
    )


@login_required
def week_view(request):
    return _horizon_view(
        request, "core/week.html", Task.Horizon.WEEK, lambda today: today + timedelta(days=6 - today.weekday())
    )


@login_required
def month_view(request):
    def month_end(today):
        last_day = calendar_module.monthrange(today.year, today.month)[1]
        return today.replace(day=last_day)

    return _horizon_view(request, "core/month.html", Task.Horizon.MONTH, month_end)


# --- Next Actions (/tasks) -----------------------------------------------


@login_required
def tasks_view(request):
    today = _today_local()
    qs = Task.objects.filter(list=Task.List.NEXT, is_project=False, completed_at__isnull=True)

    context_filter = request.GET.get("context")
    tag_filter = request.GET.get("tag")
    horizon_filter = request.GET.get("horizon")
    area_filter = request.GET.get("area")
    next_only = request.GET.get("next_only") == "1"
    show_done = request.GET.get("show_done") == "1"

    if context_filter:
        qs = qs.filter(tags__name=context_filter, tags__is_context=True)
    if tag_filter:
        qs = qs.filter(tags__name=tag_filter, tags__is_context=False)
    if horizon_filter:
        qs = qs.filter(horizon=horizon_filter)
    if area_filter:
        qs = qs.filter(area_id=area_filter)

    qs = qs.select_related("parent", "area").order_by("sort_order", "id").distinct()
    all_tasks = list(qs)

    implicit_ids = set()
    project_ids = {t.parent_id for t in all_tasks if t.parent_id}
    if project_ids:
        for project in Task.objects.filter(id__in=project_ids):
            state, ts = project.next_actions()
            if state == "implicit":
                implicit_ids.add(ts[0].id)

    def marker_for(t):
        if not t.parent_id:
            return None
        if t.is_next_action:
            return "flagged"
        if t.id in implicit_ids:
            return "implicit"
        return None

    if next_only:
        tasks = [t for t in all_tasks if not t.parent_id or marker_for(t)]
    else:
        tasks = all_tasks

    done_tasks = []
    done_meta = {}
    done_actions = {}
    if show_done:
        done_tasks = list(
            Task.objects.filter(list=Task.List.NEXT, is_project=False, completed_at__isnull=False)
            .select_related("parent", "area")
            .order_by("-completed_at")[:50]
        )
        done_meta = {t.id: f"done {timezone.localtime(t.completed_at):%d %b}" for t in done_tasks}
        done_actions = {
            t.id: [{"label": "Reopen", "url": reverse("task_reopen", args=[t.id])}] for t in done_tasks
        }

    chips = _context_chips(request)
    chips += [
        {
            "label": str(t),
            "variant": "tag",
            "active": tag_filter == t.name,
            "url": _toggle_url(request, "tag", t.name),
        }
        for t in Tag.objects.filter(is_context=False).order_by("name")
    ]
    chips += [
        {
            "label": label,
            "variant": "plain",
            "active": horizon_filter == value,
            "url": _toggle_url(request, "horizon", value),
        }
        for value, label in Task.Horizon.choices
    ]
    chips += [
        {
            "label": a.name,
            "variant": "plain",
            "active": area_filter == str(a.id),
            "url": _toggle_url(request, "area", a.id),
        }
        for a in Area.objects.all()
    ]
    chips.append(
        {
            "label": "next actions only",
            "variant": "plain",
            "active": next_only,
            "url": _toggle_url(request, "next_only", "1"),
        }
    )
    chips.append(
        {
            "label": "show done",
            "variant": "plain",
            "active": show_done,
            "url": _toggle_url(request, "show_done", "1"),
        }
    )
    any_active = any(
        [context_filter, tag_filter, horizon_filter, area_filter, next_only, show_done]
    )

    return render(
        request,
        "core/tasks.html",
        {
            "tasks": tasks,
            "markers": {t.id: marker_for(t) for t in tasks},
            "meta": {t.id: _task_meta(t, today) for t in tasks},
            "chips": chips,
            "clear_url": request.path if any_active else None,
            "show_done": show_done,
            "done_tasks": done_tasks,
            "done_meta": done_meta,
            "done_actions": done_actions,
        },
    )


# --- Waiting For ----------------------------------------------------------


@login_required
def waiting_view(request):
    today = _today_local()
    tasks = list(Task.objects.filter(list=Task.List.WAITING, completed_at__isnull=True).order_by("waiting_since", "id"))

    def overdue(t):
        if not t.waiting_since:
            return False
        return (today - t.waiting_since).days >= t.follow_up_after_days

    rows = [
        {
            "task": t,
            "waiting_days": (today - t.waiting_since).days if t.waiting_since else 0,
            "waiting_overdue": overdue(t),
            "primary_actions": _waiting_actions(t),
        }
        for t in tasks
    ]
    return render(request, "core/waiting.html", {"tasks": tasks, "rows": rows})


@login_required
@require_POST
def waiting_got_it(request, pk):
    task = get_object_or_404(Task, pk=pk, list=Task.List.WAITING)
    task.list = Task.List.NEXT
    task.waiting_on = ""
    task.waiting_since = None
    task.save(update_fields=["list", "waiting_on", "waiting_since"])
    return render(
        request,
        "core/partials/task_row_moved.html",
        {"task": task, "moved_to": "Next Actions", "undo_target": "waiting"},
    )


@login_required
@require_POST
def waiting_nudge(request, pk):
    task = get_object_or_404(Task, pk=pk, list=Task.List.WAITING)
    task.waiting_since = _today_local()
    task.last_follow_up_nag = None
    task.save(update_fields=["waiting_since", "last_follow_up_nag"])
    return render(
        request,
        "components/task_row.html",
        {
            "task": task,
            "waiting_days": 0,
            "waiting_overdue": False,
            "primary_actions": _waiting_actions(task),
        },
    )


def _waiting_actions(task):
    return [
        {"label": "Got it", "url": reverse("waiting_got_it", args=[task.id])},
        {"label": "Nudge sent", "url": reverse("waiting_nudge", args=[task.id])},
    ]


# --- Someday ---------------------------------------------------------------


@login_required
def someday_view(request):
    tasks = list(Task.objects.filter(list=Task.List.SOMEDAY, completed_at__isnull=True).order_by("sort_order", "id"))
    actions = {t.id: [{"label": "Activate", "url": reverse("someday_activate", args=[t.id])}] for t in tasks}
    return render(request, "core/someday.html", {"tasks": tasks, "actions": actions})


@login_required
@require_POST
def someday_activate(request, pk):
    task = get_object_or_404(Task, pk=pk, list=Task.List.SOMEDAY)
    task.list = Task.List.NEXT
    task.save(update_fields=["list"])
    return render(
        request,
        "core/partials/task_row_moved.html",
        {"task": task, "moved_to": "Next Actions", "undo_target": "someday"},
    )


# --- Trash -------------------------------------------------------------


@login_required
def trash_view(request):
    tasks = list(Task.objects.trash().order_by("-trashed_at"))
    actions = {
        t.id: [
            {"label": "Restore", "url": reverse("task_restore", args=[t.id])},
            {
                "label": "Purge now",
                "url": reverse("task_purge", args=[t.id]),
                "confirm": "Permanently delete this? This can't be undone.",
            },
        ]
        for t in tasks
    }
    return render(request, "core/trash.html", {"tasks": tasks, "actions": actions})


@login_required
@require_POST
def task_restore(request, pk):
    task = get_object_or_404(Task, pk=pk, list=Task.List.TRASH)
    task.list = Task.List.NEXT
    task.trashed_at = None
    task.save(update_fields=["list", "trashed_at"])
    return render(
        request,
        "core/partials/task_row_moved.html",
        {"task": task, "moved_to": "Next Actions", "undo_target": "trash"},
    )


@login_required
@require_POST
def task_purge(request, pk):
    task = get_object_or_404(Task, pk=pk, list=Task.List.TRASH)
    task.delete()
    return HttpResponse("")


# --- Generic row actions used across every list -----------------------


@login_required
@require_POST
def task_complete(request, pk):
    task = get_object_or_404(Task, pk=pk)
    force = request.POST.get("force") == "1"
    if not task.complete(force=force):
        return HttpResponse(status=409)
    return render(request, "core/partials/task_row_removed.html", {"task": task})


@login_required
@require_POST
def task_reopen(request, pk):
    task = get_object_or_404(Task, pk=pk)
    task.completed_at = None
    task.save(update_fields=["completed_at"])
    return render(request, "core/partials/task_row_reopened.html", {"task": task})


_MOVE_TARGETS = {"someday": Task.List.SOMEDAY, "waiting": Task.List.WAITING, "trash": Task.List.TRASH, "next": Task.List.NEXT}
_MOVE_LABELS = {Task.List.SOMEDAY: "Someday", Task.List.WAITING: "Waiting For", Task.List.TRASH: "Trash", Task.List.NEXT: "Next Actions"}
_MOVE_TARGET_KEYWORDS = {v: k for k, v in _MOVE_TARGETS.items()}


@login_required
@require_POST
def task_move(request, pk, target):
    task = get_object_or_404(Task, pk=pk)
    new_list = _MOVE_TARGETS[target]
    undo_target = _MOVE_TARGET_KEYWORDS[task.list]
    if new_list == Task.List.TRASH:
        task.trashed_at = timezone.now()
    elif task.list == Task.List.TRASH:
        task.trashed_at = None
    if new_list == Task.List.WAITING and task.list != Task.List.WAITING:
        task.waiting_since = _today_local()
    task.list = new_list
    task.save()
    return render(
        request,
        "core/partials/task_row_moved.html",
        {"task": task, "moved_to": _MOVE_LABELS[new_list], "undo_target": undo_target},
    )


@login_required
@require_POST
def task_flag_next(request, pk):
    task = get_object_or_404(Task, pk=pk, parent__isnull=False)
    task.is_next_action = not task.is_next_action
    task.save(update_fields=["is_next_action"])
    return HttpResponse("")


@login_required
@require_POST
def task_set_horizon(request, pk, horizon):
    task = get_object_or_404(Task, pk=pk)
    task.horizon = horizon
    task.save(update_fields=["horizon"])
    if horizon == Task.Horizon.TODAY:
        return render(request, "core/partials/task_row_to_today.html", {"task": task})
    return HttpResponse("")


@login_required
@require_POST
def task_reorder(request, pk):
    """SortableJS drop handler: `after` = id of the task now immediately
    before this one in the list (blank/absent = moved to the front).
    Rewrites sort_order in gap-based steps of 100, renumbering the whole
    sibling group on any collision (docs/solution-plan.md Step 5, Decision #2).
    """
    task = get_object_or_404(Task, pk=pk)
    siblings = list(
        Task.objects.filter(parent=task.parent, is_project=task.is_project, list=task.list)
        .exclude(pk=task.pk)
        .order_by("sort_order", "id")
    )
    after_id = request.POST.get("after")
    insert_at = 0
    if after_id:
        for i, sib in enumerate(siblings):
            if str(sib.id) == str(after_id):
                insert_at = i + 1
                break
    siblings.insert(insert_at, task)

    for i, sib in enumerate(siblings):
        new_order = (i + 1) * 100
        if sib.sort_order != new_order:
            Task.objects.filter(pk=sib.pk).update(sort_order=new_order)
    return HttpResponse("")
