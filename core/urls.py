from functools import partial

from django.urls import path

from . import views

# Named routes referenced by base.html nav. Real implementations land in
# their own epics (see docs/task-breakdown.md); until then each renders
# a plain stub so nothing 404s while the shell is being built.
urlpatterns = [
    path("inbox/", views.inbox_page, name="inbox"),
    path("inbox/process/", partial(views.stub, title="Process inbox"), name="inbox_process"),
    path("inbox/items/", views.inbox_item_create, name="inbox_item_create"),
    path("inbox/items/<int:pk>/done/", views.inbox_item_done, name="inbox_item_done"),
    path("capture/", views.capture_page, name="capture"),
    path("capture/modal/", views.capture_modal, name="capture_modal"),
    path("today/", partial(views.stub, title="Today"), name="today"),
    path("week/", partial(views.stub, title="This Week"), name="week"),
    path("month/", partial(views.stub, title="This Month"), name="month"),
    path("tasks/", partial(views.stub, title="Next Actions"), name="tasks"),
    path("projects/", partial(views.stub, title="Projects"), name="projects"),
    path("waiting/", partial(views.stub, title="Waiting For"), name="waiting"),
    path("someday/", partial(views.stub, title="Someday"), name="someday"),
    path("notes/", partial(views.stub, title="Notes"), name="notes"),
    path("recurring/", partial(views.stub, title="Recurring"), name="recurring"),
    path("tags/", partial(views.stub, title="Tags"), name="tags"),
    path("review/", partial(views.stub, title="Review"), name="review"),
    path("stats/", partial(views.stub, title="Stats"), name="stats"),
    path("settings/", views.settings_page, name="settings"),
    path("settings/tokens/", views.capture_token_create, name="capture_token_create"),
    path("settings/tokens/<int:pk>/revoke/", views.capture_token_revoke, name="capture_token_revoke"),
    path("trash/", partial(views.stub, title="Trash"), name="trash"),
    path("calendar/", partial(views.stub, title="Calendar"), name="calendar_page"),
    path("service-worker.js", views.service_worker, name="service_worker"),
    path("", partial(views.stub, title="Today"), name="home"),
]
