from functools import partial

from django.urls import path

from . import clarify, views

# Named routes referenced by base.html nav. Real implementations land in
# their own epics (see docs/task-breakdown.md); until then each renders
# a plain stub so nothing 404s while the shell is being built.
urlpatterns = [
    path("inbox/", views.inbox_page, name="inbox"),
    path("inbox/process/", clarify.process_start, name="inbox_process"),
    path("inbox/process/<int:pk>/", clarify.clarify_actionable, name="clarify_actionable"),
    path("inbox/process/<int:pk>/no/", clarify.clarify_not_actionable, name="clarify_not_actionable"),
    path("inbox/process/<int:pk>/trash/", clarify.clarify_trash, name="clarify_trash"),
    path("inbox/process/<int:pk>/someday/", clarify.clarify_someday, name="clarify_someday"),
    path("inbox/process/<int:pk>/reference/", clarify.clarify_reference, name="clarify_reference"),
    path("inbox/process/<int:pk>/yes/", clarify.clarify_actionable_type, name="clarify_actionable_type"),
    path("inbox/process/<int:pk>/done/", clarify.clarify_done, name="clarify_done"),
    path("inbox/process/<int:pk>/single/", clarify.clarify_single, name="clarify_single"),
    path("inbox/process/<int:pk>/project/", clarify.clarify_project, name="clarify_project"),
    path("inbox/process/<int:pk>/delegate/", clarify.clarify_delegate, name="clarify_delegate"),
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
