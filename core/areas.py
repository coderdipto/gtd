from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import AreaForm
from .models import Area


def _areas_qs():
    return Area.objects.annotate(task_count=Count("task", distinct=True)).order_by("sort_order", "name")


@login_required
def areas_view(request):
    return render(request, "core/areas.html", {"areas": _areas_qs(), "form": AreaForm()})


@login_required
@require_POST
def area_create(request):
    form = AreaForm(request.POST)
    if form.is_valid():
        form.save()
        return redirect("areas")
    # On failure, re-render with the bound form/errors instead of redirecting
    # (Epic 4 convention - see core/clarify.py) so the user's in-progress
    # input isn't silently dropped.
    return render(request, "core/areas.html", {"areas": _areas_qs(), "form": form})


@login_required
@require_POST
def area_edit(request, pk):
    area = get_object_or_404(Area, pk=pk)
    form = AreaForm(request.POST, instance=area)
    if form.is_valid():
        area = form.save(commit=False)
        try:
            area.sort_order = int(request.POST.get("sort_order", area.sort_order))
        except (TypeError, ValueError):
            pass
        area.save()
    return redirect("areas")


@login_required
@require_POST
def area_delete(request, pk):
    Area.objects.filter(pk=pk).delete()
    return redirect("areas")
