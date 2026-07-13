import json

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import DelegateForm, NoteForm, ProjectForm, SingleActionForm, SomedayForm
from .models import InboxItem, Tag, Task
from .tagging import sync_tags_from_text

# The clarify wizard processes InboxItems oldest-first, one at a time (no
# cherry-picking - solution-plan.md Step 4's cardinal rule). It has no DB-backed
# session model of its own; "step N of M" progress is tracked in the Django
# session for the duration of a clarify pass, and recomputed against whatever
# is still unprocessed so newly captured items extend the total mid-session
# rather than breaking the count.


def _next_item_or_none():
    return InboxItem.objects.filter(processed_at__isnull=True).order_by("created_at", "id").first()


def _get_item_or_none(pk):
    return InboxItem.objects.filter(pk=pk, processed_at__isnull=True).first()


def _progress(request):
    remaining = InboxItem.objects.filter(processed_at__isnull=True).count()
    processed = request.session.get("clarify_processed", 0)
    return processed, processed + remaining


def _mark_processed(item, extra_fields=()):
    item.processed_at = timezone.now()
    item.save(update_fields=["processed_at", *extra_fields])


def _advance(request):
    request.session["clarify_processed"] = request.session.get("clarify_processed", 0) + 1
    return redirect("inbox_process")


@login_required
def process_start(request):
    item = _next_item_or_none()
    if not item:
        request.session.pop("clarify_processed", None)
        return render(request, "core/clarify/finished.html")
    return redirect("clarify_actionable", pk=item.id)


@login_required
def clarify_actionable(request, pk):
    item = _get_item_or_none(pk)
    if not item:
        return redirect("inbox_process")
    processed, total = _progress(request)
    return render(
        request,
        "core/clarify/actionable.html",
        {"item": item, "step": processed + 1, "total": total},
    )


@login_required
def clarify_not_actionable(request, pk):
    item = _get_item_or_none(pk)
    if not item:
        return redirect("inbox_process")
    processed, total = _progress(request)
    return render(
        request,
        "core/clarify/not_actionable.html",
        {"item": item, "step": processed + 1, "total": total},
    )


@login_required
@require_POST
def clarify_trash(request, pk):
    # Uses the same graceful "already processed -> back to the wizard" redirect
    # as every other clarify view, instead of a hard 404, so a double-click or
    # a stale duplicate POST doesn't surface a raw error page mid-wizard.
    item = _get_item_or_none(pk)
    if not item:
        return redirect("inbox_process")
    Task.objects.create(
        title=item.title,
        description=item.description,
        list=Task.List.TRASH,
        trashed_at=timezone.now(),
    )
    _mark_processed(item)
    return _advance(request)


@login_required
@require_POST
def clarify_done(request, pk):
    item = _get_item_or_none(pk)
    if not item:
        return redirect("inbox_process")
    item.done_directly = True
    _mark_processed(item, extra_fields=["done_directly"])
    return _advance(request)


@login_required
def clarify_actionable_type(request, pk):
    item = _get_item_or_none(pk)
    if not item:
        return redirect("inbox_process")
    processed, total = _progress(request)
    return render(
        request,
        "core/clarify/actionable_type.html",
        {"item": item, "step": processed + 1, "total": total},
    )


# --- Shared skeleton for the five "turn this item into a Task/Note" screens ---
#
# Each of clarify_someday/clarify_reference/clarify_single/clarify_project/
# clarify_delegate is: fetch the still-unprocessed item (or bounce back into
# the wizard); on POST, validate the form and hand it to a screen-specific
# on_valid(form, item, request) that saves the target object and returns True,
# or adds a form error and returns False; on GET, build a form pre-filled from
# the inbox item. on_valid returning False re-renders the same screen with the
# invalid/erroring form instead of advancing.


def _all_tags_json():
    # Feeds the Alpine typeahead (static/js/tag-typeahead.js) on free-text
    # description/body fields - just existing tag names to suggest from, the
    # actual @/# parsing on save is core/tagging.py, this is UI sugar only.
    tags = [{"name": t.name, "is_context": t.is_context} for t in Tag.objects.all()]
    return json.dumps(tags)


def _clarify_form_screen(request, pk, form_class, template_name, initial_fn, on_valid, extra_context_fn=None):
    item = _get_item_or_none(pk)
    if not item:
        return redirect("inbox_process")
    if request.method == "POST":
        form = form_class(request.POST)
        if form.is_valid() and on_valid(form, item, request):
            _mark_processed(item)
            return _advance(request)
    else:
        form = form_class(initial=initial_fn(item))
    processed, total = _progress(request)
    context = {
        "item": item,
        "form": form,
        "step": processed + 1,
        "total": total,
        "all_tags": _all_tags_json(),
    }
    if extra_context_fn:
        context.update(extra_context_fn(request))
    return render(request, template_name, context)


def _someday_initial(item):
    return {"title": item.title, "description": item.description}


def _someday_on_valid(form, item, request):
    task = form.save(commit=False)
    task.list = Task.List.SOMEDAY
    task.save()
    sync_tags_from_text(task, task.title, task.description)
    return True


@login_required
def clarify_someday(request, pk):
    return _clarify_form_screen(
        request, pk, SomedayForm, "core/clarify/someday.html", _someday_initial, _someday_on_valid
    )


def _reference_initial(item):
    return {"title": item.title, "body": item.description}


def _reference_on_valid(form, item, request):
    note = form.save()
    sync_tags_from_text(note, note.title, note.body)
    return True


@login_required
def clarify_reference(request, pk):
    return _clarify_form_screen(
        request, pk, NoteForm, "core/clarify/reference.html", _reference_initial, _reference_on_valid
    )


def _single_initial(item):
    return {"title": item.title, "description": item.description}


def _single_on_valid(form, item, request):
    task = form.save(commit=False)
    task.list = Task.List.NEXT
    task.save()
    sync_tags_from_text(task, task.title, task.description)
    return True


@login_required
def clarify_single(request, pk):
    return _clarify_form_screen(
        request, pk, SingleActionForm, "core/clarify/single.html", _single_initial, _single_on_valid
    )


def _project_initial(item):
    return {"title": item.title, "description": item.description}


def _project_on_valid(form, item, request):
    subtask_titles = [t.strip() for t in request.POST.getlist("subtask_title") if t.strip()]
    if not subtask_titles:
        # Every project needs a next action - refuse to save a project with no
        # subtasks rather than silently creating a dead-end NEEDS_ATTENTION one.
        form.add_error(None, "Add at least one subtask — every project needs a next action.")
        return False
    project = form.save(commit=False)
    project.is_project = True
    project.save()
    sync_tags_from_text(project, project.title, project.description)
    for i, title in enumerate(subtask_titles):
        subtask = Task.objects.create(
            title=title,
            parent=project,
            sort_order=(i + 1) * 100,
            is_next_action=(i == 0),
        )
        sync_tags_from_text(subtask, subtask.title)
    return True


def _project_extra_context(request):
    # Reflect whatever subtask rows the user typed back into the Alpine-managed
    # repeater so a validation failure (e.g. no subtasks, or a title error)
    # doesn't silently wipe out what they'd already entered.
    if request.method == "POST":
        titles = request.POST.getlist("subtask_title") or [""]
    else:
        titles = [""]
    return {"subtask_titles": titles}


@login_required
def clarify_project(request, pk):
    return _clarify_form_screen(
        request,
        pk,
        ProjectForm,
        "core/clarify/project.html",
        _project_initial,
        _project_on_valid,
        extra_context_fn=_project_extra_context,
    )


def _delegate_initial(item):
    return {"title": item.title, "description": item.description}


def _delegate_on_valid(form, item, request):
    task = form.save(commit=False)
    task.list = Task.List.WAITING
    task.waiting_since = timezone.now().date()
    task.save()
    sync_tags_from_text(task, task.title, task.description)
    return True


@login_required
def clarify_delegate(request, pk):
    return _clarify_form_screen(
        request, pk, DelegateForm, "core/clarify/delegate.html", _delegate_initial, _delegate_on_valid
    )
