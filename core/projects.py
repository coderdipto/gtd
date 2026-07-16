from django.contrib.auth.decorators import login_required
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from .google_calendar import get_credential
from .lists import _toggle_url
from .models import ProjectTemplate, ProjectTemplateItem, Task
from .tagging import sync_tags_from_text
from .timeblocks import blocks_json


def _badge_and_next_line(project):
    # One next_actions() call feeds both the badge and the next-action line -
    # they used to be computed by two separate calls (each re-deriving the
    # same state), doubling the subtask work per project for no reason.
    state, tasks = project.next_actions()
    if state == Task.NEEDS_ATTENTION:
        badge = "stalled"
    elif state == "implicit":
        badge = "unflagged"
    else:
        badge = None
    next_line = f"Next: {tasks[0].title}" if tasks else "Mark done or add a next task."
    return badge, next_line


def _project_state_badge(project):
    badge, _next_line = _badge_and_next_line(project)
    return badge


def _next_line(project):
    _badge, next_line = _badge_and_next_line(project)
    return next_line


@login_required
def projects_view(request):
    show_done = request.GET.get("show_done") == "1"
    projects = list(
        Task.objects.filter(is_project=True, completed_at__isnull=True)
        .prefetch_related(Prefetch("subtasks", queryset=Task.objects.order_by("sort_order", "id")))
        .order_by("sort_order", "id")
    )
    badges = {}
    next_lines = {}
    for p in projects:
        badges[p.id], next_lines[p.id] = _badge_and_next_line(p)
    done_projects = []
    if show_done:
        done_projects = list(
            Task.objects.filter(is_project=True, completed_at__isnull=False).order_by("-completed_at")[:50]
        )
    chips = [
        {
            "label": "show done",
            "variant": "plain",
            "active": show_done,
            "url": _toggle_url(request, "show_done", "1"),
        }
    ]
    return render(
        request,
        "core/projects.html",
        {
            "projects": projects,
            "badges": badges,
            "next_lines": next_lines,
            "chips": chips,
            "show_done": show_done,
            "done_projects": done_projects,
            "templates": ProjectTemplate.objects.prefetch_related("items"),
        },
    )


# --- Project templates (task #19) ---


@login_required
def project_templates(request):
    return render(
        request,
        "core/project_templates.html",
        {"templates": ProjectTemplate.objects.prefetch_related("items")},
    )


@login_required
@require_POST
def project_from_template(request, pk):
    """Instantiate a real project (+ subtasks) from a template's checklist."""
    template = get_object_or_404(ProjectTemplate, pk=pk)
    project = Task.objects.create(
        title=template.name, description=template.description, is_project=True
    )
    for i, item in enumerate(template.items.all()):
        # First item is the flagged next action, mirroring project_add_subtask
        # and the clarify Project screen's domain rule.
        Task.objects.create(
            title=item.title, parent=project, sort_order=(i + 1) * 100, is_next_action=(i == 0)
        )
    return redirect("project_detail", pk=project.id)


@login_required
@require_POST
def template_from_project(request, pk):
    """Save an existing project's subtask list as a reusable template."""
    project = get_object_or_404(Task, pk=pk, is_project=True)
    template = ProjectTemplate.objects.create(name=project.title, description=project.description)
    for i, sub in enumerate(project.subtasks.order_by("sort_order", "id")):
        ProjectTemplateItem.objects.create(template=template, title=sub.title, sort_order=(i + 1) * 100)
    return redirect("project_templates")


@login_required
@require_POST
def template_delete(request, pk):
    ProjectTemplate.objects.filter(pk=pk).delete()
    return redirect("project_templates")


@login_required
def project_detail(request, pk):
    # Prefetch once so next_actions()'s self.subtasks.all() (called below,
    # and again inside _badge_and_next_line) hits the cache instead of
    # issuing its own query each time - see the comment on next_actions().
    project = get_object_or_404(
        Task.objects.prefetch_related(Prefetch("subtasks", queryset=Task.objects.order_by("sort_order", "id"))),
        pk=pk,
        is_project=True,
    )
    subtasks = list(project.subtasks.all())
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
    badge, _next_line = _badge_and_next_line(project)
    blocks = list(project.blocks.order_by("start"))
    return render(
        request,
        "core/project_detail.html",
        {
            "project": project,
            "subtasks": subtasks,
            "state": state,
            "markers": markers,
            "flag_urls": flag_urls,
            "badge": badge,
            "blocks": blocks,
            "blocks_json": blocks_json(blocks, project.title),
            "gcal_connected": get_credential() is not None,
            "linked_notes": project.linked_notes.filter(trashed_at__isnull=True),
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
