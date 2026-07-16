from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from core.models import InboxItem, Note, Task
from core.tagging import sync_tags_from_text


class Command(BaseCommand):
    help = (
        "Populate a fresh install with a demo login and sample GTD content so "
        "the app has something to show on first run. Idempotent: safe to re-run "
        "(rows are matched by title). This is a single-user app, so the sample "
        "tasks/notes are global — the created user just gives you a way to log in."
    )

    def add_arguments(self, parser):
        parser.add_argument("--username", default="demo")
        parser.add_argument("--password", default="demo")

    def handle(self, *args, **opts):
        User = get_user_model()
        user, created = User.objects.get_or_create(
            username=opts["username"],
            defaults={"is_staff": True, "is_superuser": True},
        )
        user.set_password(opts["password"])
        user.is_staff = user.is_superuser = True
        user.save()

        def task(title, **kw):
            obj, _ = Task.objects.get_or_create(title=title, defaults=kw)
            sync_tags_from_text(obj, obj.title)
            return obj

        # Standalone next actions (with a couple of Engage facets set).
        task("Reply to Alex about the proposal @office #urgent", horizon=Task.Horizon.TODAY, estimate_min=10, energy="low")
        task("Book dentist appointment @calls", horizon=Task.Horizon.WEEK, estimate_min=15, energy="low")
        task("Draft Q3 planning doc @office", horizon=Task.Horizon.WEEK, estimate_min=90, energy="high")
        task("Fix leaky kitchen tap @home", horizon=Task.Horizon.ANYTIME)

        # A project with subtasks (first is the flagged next action).
        project, _ = Task.objects.get_or_create(
            title="Launch personal blog", defaults={"is_project": True}
        )
        for i, sub in enumerate(["Pick a domain name", "Choose a static-site generator", "Write the first post", "Deploy"]):
            Task.objects.get_or_create(
                title=sub, parent=project, defaults={"sort_order": (i + 1) * 100, "is_next_action": i == 0}
            )

        # Someday / Waiting.
        task("Learn to sail", list=Task.List.SOMEDAY)
        w = task("Refund from airline", list=Task.List.WAITING)
        if not w.waiting_since:
            w.waiting_on = "Airline support"
            w.waiting_since = timezone.now().date()
            w.save(update_fields=["waiting_on", "waiting_since"])

        # An unprocessed inbox item + a reference note linked to the project.
        InboxItem.objects.get_or_create(title="Idea: weekend photography project")
        note, _ = Note.objects.get_or_create(
            title="Blog hosting options",
            defaults={"body": "Comparing options #reference\n\n- GitHub Pages\n- Netlify\n- self-host", "linked_project": project},
        )
        sync_tags_from_text(note, note.title, note.body)

        self.stdout.write(self.style.SUCCESS(
            f"Seeded demo data. Log in as '{opts['username']}' / '{opts['password']}'."
        ))
