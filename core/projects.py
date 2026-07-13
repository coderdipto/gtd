from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from .models import Task
from .tagging import sync_tags_from_text


def _project_state_badge(project):
    state, _tasks = project.next_actions()
    if state == Task.NEEDS_ATTENTION:
        return "stalled"
    if state == "implicit":
        return "no_next"
    return None


def _next_line(project):
    _state, tasks = project.next_actions()
    return f"Next: {tasks[0].title}" if tasks else "Mark done or add a next task."


@login_required
def projects_view(request):
    projects = list(
        Task.objects.filter(is_project=True, completed_at__isnull=True).order_by("sort_order", "id")
    )
    badges = {p.id: _project_state_badge(p) for p in projects}
    next_lines = {p.id: _next_line(p) for p in projects}
    return render(
        request,
        "core/projects.html",
        {"projects": projects, "badges": badges, "next_lines": next_lines},
    )


@login_required
def project_detail(request, pk):
    project = get_object_or_404(Task, pk=pk, is_project=True)
    subtasks = list(project.subtasks.order_by("sort_order", "id"))
    state, next_tasks = project.next_actions()
    next_ids = {t.id for t in next_tasks}

    def marker_for(t):
        if t.is_next_action:
            return "flagged"
        if t.id in next_ids:
            return "implicit"
        return None

    markers = {t.id: marker_for(t) for t in subtasks}
    flag_urls = {t.id: reverse("project_flag_next", args=[project.id, t.id]) for t in subtasks}
    return render(
        request,
        "core/project_detail.html",
        {
            "project": project,
            "subtasks": subtasks,
            "state": state,
            "markers": markers,
            "flag_urls": flag_urls,
            "badge": _project_state_badge(project),
        },
    )


@login_required
@require_POST
def project_add_subtask(request, pk):
    project = get_object_or_404(Task, pk=pk, is_project=True)
    title = request.POST.get("title", "").strip()
    if title:
        max_order = project.subtasks.order_by("-sort_order").values_list("sort_order", flat=True).first() or 0
        # First subtask ever on this project still needs one flagged next
        # action (solution-plan.md Step 2 domain rule) - later additions
        # don't auto-flag since the project already has a resolved next action.
        auto_flag = not project.subtasks.exists()
        subtask = Task.objects.create(
            title=title, parent=project, sort_order=max_order + 100, is_next_action=auto_flag
        )
        sync_tags_from_text(subtask, subtask.title)
    return redirect("project_detail", pk=project.id)


@login_required
@require_POST
def project_flag_next(request, pk, subtask_pk):
    subtask = get_object_or_404(Task, pk=subtask_pk, parent_id=pk)
    subtask.is_next_action = not subtask.is_next_action
    subtask.save(update_fields=["is_next_action"])
    project = subtask.parent
    _state, next_tasks = project.next_actions()
    next_ids = {t.id for t in next_tasks}
    marker = "flagged" if subtask.is_next_action else ("implicit" if subtask.id in next_ids else None)
    return render(
        request,
        "components/task_row.html",
        {
            "task": subtask,
            "subtask_marker": marker,
            "flag_url": reverse("project_flag_next", args=[pk, subtask_pk]),
        },
    )
