from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.http import url_has_allowed_host_and_scheme

from .forms import SingleActionForm
from .google_calendar import get_credential
from .lists import _menu_moves
from .models import Task
from .tagging import all_tags_json, sync_tags_from_text
from .timeblocks import blocks_json


def _safe_next(request, candidate):
    # task_row.html links here with ?next=<wherever the list screen was>,
    # round-tripped through a hidden form field on POST so Save returns the
    # user to that list instead of stranding them on the detail page.
    # url_has_allowed_host_and_scheme guards against an open redirect via a
    # crafted next= pointing off-site.
    if candidate and url_has_allowed_host_and_scheme(candidate, allowed_hosts={request.get_host()}):
        return candidate
    return None


@login_required
def task_detail(request, pk):
    # is_project=False: Projects have their own richer detail screen
    # (core/projects.py::project_detail) - subtasks and plain tasks land
    # here regardless of which list/horizon screen linked to them.
    task = get_object_or_404(Task, pk=pk, is_project=False)
    if request.method == "POST":
        next_url = _safe_next(request, request.POST.get("next"))
        form = SingleActionForm(request.POST, instance=task)
        if form.is_valid():
            task = form.save()
            sync_tags_from_text(task, task.title, task.description)
            if next_url:
                return redirect(next_url)
            return redirect("task_detail", pk=task.id)
    else:
        form = SingleActionForm(instance=task)
    next_url = _safe_next(request, request.GET.get("next") or request.POST.get("next"))
    blocks = list(task.blocks.order_by("start"))
    return render(
        request,
        "core/task_detail.html",
        {
            "task": task,
            "form": form,
            "all_tags": all_tags_json(),
            "menu_moves": _menu_moves(task),
            "next_url": next_url,
            "blocks": blocks,
            "blocks_json": blocks_json(blocks, task.title),
            "gcal_connected": get_credential() is not None,
        },
    )
