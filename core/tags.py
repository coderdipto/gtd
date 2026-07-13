from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.template.defaultfilters import slugify
from django.views.decorators.http import require_POST

from .models import Note, Tag, Task

CONTEXT_NAG_THRESHOLD = 7


@login_required
def tags_view(request):
    tags = Tag.objects.annotate(
        task_count=Count("task", distinct=True), note_count=Count("note", distinct=True)
    ).order_by("-is_context", "name")
    context_count = Tag.objects.filter(is_context=True).count()
    return render(
        request,
        "core/tags.html",
        {"tags": tags, "show_nag": context_count > CONTEXT_NAG_THRESHOLD},
    )


@login_required
@require_POST
def tag_toggle_context(request, pk):
    tag = get_object_or_404(Tag, pk=pk)
    tag.is_context = not tag.is_context
    tag.save(update_fields=["is_context"])
    return redirect("tags")


@login_required
@require_POST
def tag_rename(request, pk):
    tag = get_object_or_404(Tag, pk=pk)
    new_name = slugify(request.POST.get("name", "").strip())
    if new_name and not Tag.objects.exclude(pk=tag.pk).filter(name=new_name).exists():
        tag.name = new_name
        tag.save(update_fields=["name"])
    return redirect("tags")


@login_required
@require_POST
def tag_merge(request, pk):
    """Re-points every Task/Note using this tag onto the target tag, then
    deletes this one - the target absorbs its usage entirely."""
    source = get_object_or_404(Tag, pk=pk)
    target_id = request.POST.get("target")
    target = get_object_or_404(Tag, pk=target_id)
    if target.pk != source.pk:
        for task in Task.objects.filter(tags=source):
            task.tags.add(target)
        for note in Note.objects.filter(tags=source):
            note.tags.add(target)
        source.delete()
    return redirect("tags")


@login_required
@require_POST
def tag_delete(request, pk):
    Tag.objects.filter(pk=pk).delete()
    return redirect("tags")
