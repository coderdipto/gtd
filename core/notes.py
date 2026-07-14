import mimetypes

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.postgres.search import SearchQuery
from django.http import FileResponse, Http404, HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import Note, NoteAttachment, Tag, Task
from .tagging import sync_tags_from_text

MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024  # 20MB cap (task-breakdown.md Epic 6)


@login_required
def notes_view(request):
    q = request.GET.get("q", "").strip()
    tag_filter = request.GET.get("tag")

    notes = Note.objects.filter(trashed_at__isnull=True)
    if q:
        notes = notes.filter(search=SearchQuery(q))
    if tag_filter:
        notes = notes.filter(tags__name=tag_filter)
    notes = notes.order_by("-updated_at").distinct()

    tags = Tag.objects.filter(is_context=False).order_by("name")
    chips = [
        {
            "label": str(t),
            "variant": "tag",
            "active": tag_filter == t.name,
            "url": _tag_toggle_url(request, t.name),
        }
        for t in tags
    ]
    return render(
        request,
        "core/notes.html",
        {"notes": notes, "q": q, "chips": chips, "clear_url": request.path if (q or tag_filter) else None},
    )


def _tag_toggle_url(request, name):
    params = request.GET.copy()
    if params.get("tag") == name:
        params.pop("tag", None)
    else:
        params["tag"] = name
    qs = params.urlencode()
    return f"{request.path}?{qs}" if qs else request.path


@login_required
def note_detail(request, pk):
    note = get_object_or_404(Note, pk=pk, trashed_at__isnull=True)
    return render(request, "core/note_detail.html", {"note": note})


@login_required
def note_create(request):
    if request.method == "POST":
        title = request.POST.get("title", "").strip()
        body = request.POST.get("body", "")
        if not title:
            return HttpResponseBadRequest("Title is required.")
        note = Note.objects.create(title=title, body=body)
        sync_tags_from_text(note, note.title, note.body)
        return redirect("note_detail", pk=note.id)
    return render(request, "core/note_create.html")


@login_required
@require_POST
def note_update(request, pk):
    note = get_object_or_404(Note, pk=pk, trashed_at__isnull=True)
    note.title = request.POST.get("title", note.title).strip() or note.title
    note.body = request.POST.get("body", note.body)
    note.save(update_fields=["title", "body", "updated_at"])
    sync_tags_from_text(note, note.title, note.body)
    return redirect("note_detail", pk=note.id)


@login_required
@require_POST
def note_delete(request, pk):
    note = get_object_or_404(Note, pk=pk)
    note.trashed_at = timezone.now()
    note.save(update_fields=["trashed_at"])
    return redirect("notes")


@login_required
@require_POST
def note_attachment_upload(request, pk):
    note = get_object_or_404(Note, pk=pk, trashed_at__isnull=True)
    file = request.FILES.get("file")
    if file and file.size <= MAX_ATTACHMENT_BYTES:
        note.attachments.create(file=file, original_name=file.name)
    return redirect("note_detail", pk=note.id)


@login_required
def note_attachment_download(request, pk, attachment_pk):
    """Private attachment serving (task-breakdown.md Epic 12). In production
    (DEBUG=False), nginx never serves /media/ directly (see deploy/nginx-gtd.conf) -
    this view is the only path to a file, and it hands off to nginx's internal-only
    `/protected-media/` location via X-Accel-Redirect after checking login. In
    dev, DEBUG's own static() media serving isn't behind nginx, so this streams
    the file directly instead."""
    attachment = get_object_or_404(NoteAttachment, pk=attachment_pk, note_id=pk)
    if not attachment.file or not attachment.file.storage.exists(attachment.file.name):
        raise Http404
    content_type = mimetypes.guess_type(attachment.original_name)[0] or "application/octet-stream"

    if settings.DEBUG:
        response = FileResponse(attachment.file.open("rb"), content_type=content_type)
    else:
        response = HttpResponse(content_type=content_type)
        relative_path = attachment.file.name  # relative to MEDIA_ROOT, e.g. "attachments/2026/07/x.pdf"
        response["X-Accel-Redirect"] = f"/protected-media/{relative_path}"
    response["Content-Disposition"] = f'attachment; filename="{attachment.original_name}"'
    return response


@login_required
@require_POST
def note_attachment_delete(request, pk, attachment_pk):
    note = get_object_or_404(Note, pk=pk)
    note.attachments.filter(pk=attachment_pk).delete()
    return redirect("note_detail", pk=note.id)


@login_required
@require_POST
def task_convert_to_note(request, pk):
    """'This turned out to be reference' - task-breakdown.md Epic 6:
    copies title/description to a new Note, trashes the source task."""
    task = get_object_or_404(Task, pk=pk)
    note = Note.objects.create(title=task.title, body=task.description)
    note.tags.set(task.tags.all())
    task.list = Task.List.TRASH
    task.trashed_at = timezone.now()
    task.save(update_fields=["list", "trashed_at"])
    return render(
        request,
        "core/partials/task_row_moved.html",
        {"task": task, "moved_to": "a Note", "undo_target": "trash"},
    )
