from datetime import time, timedelta

from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.db import models
from django.db.models import Q
from django.utils import timezone


class Tag(models.Model):
    name = models.SlugField(max_length=40, unique=True)  # stored lowercase
    is_context = models.BooleanField(default=False)  # @word vs #word
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"@{self.name}" if self.is_context else f"#{self.name}"


class Area(models.Model):  # Horizon 2: roles
    name = models.CharField(max_length=80, unique=True)
    description = models.TextField(blank=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "name"]

    def __str__(self):
        return self.name


class InboxItem(models.Model):
    title = models.CharField(max_length=300)
    description = models.TextField(blank=True)
    source = models.CharField(max_length=20, default="web")  # web|shortcut|desktop|review
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    done_directly = models.BooleanField(default=False)  # 2-minute rule
    processed_at = models.DateTimeField(null=True, blank=True)  # set on clarify

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title


class TaskQuerySet(models.QuerySet):
    def trash(self):
        return self.filter(list=Task.List.TRASH)

    def purgeable(self, as_of=None, days=30):
        as_of = as_of or timezone.now()
        return self.trash().filter(trashed_at__lte=as_of - timedelta(days=days))

    def incomplete(self):
        return self.filter(completed_at__isnull=True)


class Task(models.Model):
    class List(models.TextChoices):
        NEXT = "next"
        WAITING = "waiting"
        SOMEDAY = "someday"
        TRASH = "trash"

    class Horizon(models.TextChoices):
        TODAY = "today"
        WEEK = "this_week"
        MONTH = "this_month"
        ANYTIME = "anytime"

    title = models.CharField(max_length=300)
    description = models.TextField(blank=True)  # markdown
    list = models.CharField(max_length=10, choices=List.choices, default=List.NEXT)
    is_project = models.BooleanField(default=False)
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.CASCADE, related_name="subtasks"
    )
    is_next_action = models.BooleanField(default=False)  # explicit flag, subtasks only
    horizon = models.CharField(
        max_length=12, choices=Horizon.choices, default=Horizon.ANYTIME
    )  # Decision #1
    sort_order = models.PositiveIntegerField(default=0)  # manual priority
    big3 = models.BooleanField(default=False)  # weekly star
    q2_week = models.DateField(null=True, blank=True)  # Monday of chip validity week
    area = models.ForeignKey(Area, null=True, blank=True, on_delete=models.SET_NULL)
    tags = models.ManyToManyField(Tag, blank=True)
    due_date = models.DateField(null=True, blank=True)  # open decision: included
    # Engage facets (task #16): optional so existing tasks stay untouched and
    # the Engage view treats "unset" as "always eligible" rather than excluded.
    energy = models.CharField(max_length=6, choices=[("low", "Low"), ("medium", "Medium"), ("high", "High")], blank=True)
    estimate_min = models.PositiveSmallIntegerField(null=True, blank=True)  # rough time-to-do
    # Waiting For (only when list == WAITING)
    waiting_on = models.CharField(max_length=120, blank=True)
    waiting_since = models.DateField(null=True, blank=True)
    follow_up_after_days = models.PositiveSmallIntegerField(default=5)
    last_follow_up_nag = models.DateField(null=True, blank=True)
    # lifecycle / counters
    carried_over_count = models.PositiveSmallIntegerField(default=0)
    missed_block_count = models.PositiveSmallIntegerField(default=0)
    recurring_template = models.ForeignKey(
        "RecurringTemplate",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="instances",
    )
    occurrence_date = models.DateField(null=True, blank=True)  # set on instances
    completed_at = models.DateTimeField(null=True, blank=True)
    trashed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = TaskQuerySet.as_manager()

    class Meta:
        constraints = [
            # subtasks are single-level: parent must be a project
            models.CheckConstraint(
                name="no_project_subtask",
                check=~Q(is_project=True) | Q(parent__isnull=True),
            ),
            # materialize_recurring idempotence (solution-plan.md Step 7): running
            # the command twice for the same template+date must not double-create.
            models.UniqueConstraint(
                fields=["recurring_template", "occurrence_date"],
                condition=Q(recurring_template__isnull=False),
                name="unique_recurring_occurrence",
            ),
        ]
        indexes = [
            models.Index(fields=["list", "horizon"]),
            models.Index(fields=["completed_at"]),
        ]

    def __str__(self):
        return self.title

    # --- Next action resolution (Decision #7) ---
    # A project's next action(s): explicitly flagged incomplete subtask(s) if any;
    # else the first incomplete subtask by sort_order, returned as implicit; else
    # the project has no incomplete subtasks at all -> NEEDS_ATTENTION.
    NEEDS_ATTENTION = "needs_attention"

    def next_actions(self):
        """Returns (state, [tasks]). state is one of:
        'flagged'          -> tasks is the list of explicitly flagged incomplete subtasks
        'implicit'         -> tasks is a single-item list, the first incomplete subtask
                               by sort_order (not explicitly flagged)
        NEEDS_ATTENTION     -> tasks is [] (no incomplete subtasks at all)
        Only meaningful when self.is_project is True.

        Filters/sorts in Python over self.subtasks.all() rather than chaining
        .filter()/.order_by() onto the related manager - a prefetch_related("subtasks")
        on the caller's queryset populates the instance-level cache that only a bare
        .all() can serve; any further queryset chaining bypasses that cache and issues
        a fresh query per project (the N+1 behind the old /projects/ query count).
        """
        subtasks = sorted(self.subtasks.all(), key=lambda t: (t.sort_order, t.id))
        incomplete = [t for t in subtasks if t.completed_at is None]
        flagged = [t for t in incomplete if t.is_next_action]
        if flagged:
            return "flagged", flagged
        if incomplete:
            return "implicit", [incomplete[0]]
        return self.NEEDS_ATTENTION, []

    @property
    def progress_label(self):
        """'3/7' style subtask completion count, for the project progress pill."""
        subtasks = list(self.subtasks.all())
        done = sum(1 for t in subtasks if t.completed_at is not None)
        return f"{done}/{len(subtasks)}"

    @property
    def progress_percent(self):
        subtasks = list(self.subtasks.all())
        if not subtasks:
            return 0
        done = sum(1 for t in subtasks if t.completed_at is not None)
        return round(100 * done / len(subtasks))

    @property
    def is_overdue_recurring(self):
        """Recurring instance whose occurrence_date has passed and is still
        incomplete (solution-plan.md Step 7, Decision #8: piles up, never
        replaces the prior instance)."""
        if not self.recurring_template_id or not self.occurrence_date or self.completed_at:
            return False
        return self.occurrence_date < timezone.localtime().date()

    @property
    def overdue_since_label(self):
        return f"overdue since {self.occurrence_date:%d %b}"

    @property
    def q2_active(self):
        """Whether the Q2 (important-not-urgent) chip is still valid this week -
        it expires the Monday after it was set (Decision: transient, never persisted
        as a stored priority - see CLAUDE.md 'Key domain rules')."""
        if not self.q2_week:
            return False
        today = timezone.localtime().date()
        current_monday = today - timedelta(days=today.weekday())
        return self.q2_week == current_monday

    def complete(self, force=False):
        """Mark complete. Projects with incomplete subtasks require force=True
        (UI must prompt "Complete anyway? Subtasks will be completed too.").
        Returns True if completed, False if blocked (project, incomplete subtasks, no force).
        """
        if self.is_project and not force and self.subtasks.incomplete().exists():
            return False
        now = timezone.now()
        completed_subtasks = list(self.subtasks.incomplete()) if self.is_project else []
        if self.is_project:
            self.subtasks.incomplete().update(completed_at=now)
        self.completed_at = now
        self.save(update_fields=["completed_at"])

        # Deferred import: core.timeblocks -> core.google_calendar -> core.models
        # would be circular at module load time, but is fine once everything's
        # already imported (i.e. by the time complete() actually runs).
        from .timeblocks import retitle_task_blocks

        retitle_task_blocks(self)
        for subtask in completed_subtasks:
            retitle_task_blocks(subtask)
        return True


class Note(models.Model):  # Reference (Decision #5)
    title = models.CharField(max_length=300)
    body = models.TextField(blank=True)  # markdown; links live here
    tags = models.ManyToManyField(Tag, blank=True)
    # Optional link to the project (or any task) this reference material
    # supports (task #19), so notes live with the work rather than only
    # sharing tags. related_name lets a project list its notes cheaply.
    linked_project = models.ForeignKey(
        "Task", null=True, blank=True, on_delete=models.SET_NULL, related_name="linked_notes"
    )
    trashed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    search = SearchVectorField(null=True)  # Postgres FTS, GIN index (Step 6)

    class Meta:
        indexes = [
            models.Index(fields=["trashed_at"]),
            GinIndex(fields=["search"]),
        ]

    def __str__(self):
        return self.title


class NoteAttachment(models.Model):
    note = models.ForeignKey(Note, on_delete=models.CASCADE, related_name="attachments")
    file = models.FileField(upload_to="attachments/%Y/%m/")
    original_name = models.CharField(max_length=255)

    def __str__(self):
        return self.original_name


class RecurringTemplate(models.Model):
    title = models.CharField(max_length=300)
    description = models.TextField(blank=True)
    rrule = models.CharField(max_length=200)  # RFC 5545, e.g. FREQ=WEEKLY;BYDAY=TH
    tags = models.ManyToManyField(Tag, blank=True)
    area = models.ForeignKey(Area, null=True, blank=True, on_delete=models.SET_NULL)
    # optional standing time block
    block_start_time = models.TimeField(null=True, blank=True)
    block_duration_min = models.PositiveSmallIntegerField(null=True, blank=True)
    gcal_event_id = models.CharField(max_length=120, blank=True)  # recurring event
    active = models.BooleanField(default=True)
    last_materialized_until = models.DateField(null=True, blank=True)

    def __str__(self):
        return self.title


class TimeBlock(models.Model):
    class Status(models.TextChoices):
        SCHEDULED = "scheduled"
        MISSED = "missed"
        COMPLETED = "completed"

    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="blocks")
    start = models.DateTimeField()
    end = models.DateTimeField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.SCHEDULED)
    gcal_event_id = models.CharField(max_length=120, blank=True)
    gcal_etag = models.CharField(max_length=120, blank=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.task_id}: {self.start} - {self.end}"


class GoogleCredential(models.Model):  # singleton row
    refresh_token = models.BinaryField()  # Fernet-encrypted
    gtd_calendar_id = models.CharField(max_length=120, blank=True)
    primary_calendar_id = models.CharField(max_length=120, default="primary")
    connected_at = models.DateTimeField(auto_now_add=True)


class SyncChannel(models.Model):
    calendar_id = models.CharField(max_length=120)
    channel_id = models.UUIDField()
    resource_id = models.CharField(max_length=120)
    expiration = models.DateTimeField()
    sync_token = models.CharField(max_length=255, blank=True)


class ReviewConfig(models.Model):
    class Cadence(models.TextChoices):
        WEEKLY = "weekly"
        MONTHLY = "monthly"
        QUARTERLY = "quarterly"
        YEARLY = "yearly"

    cadence = models.CharField(max_length=10, choices=Cadence.choices, unique=True)
    weekday = models.PositiveSmallIntegerField(default=4)  # Fri
    time = models.TimeField(default=time(16, 0))
    duration_min = models.PositiveSmallIntegerField(default=60)
    gcal_event_id = models.CharField(max_length=120, blank=True)

    def __str__(self):
        return self.cadence


class ReviewSession(models.Model):
    cadence = models.CharField(max_length=10, choices=ReviewConfig.Cadence.choices)
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    phase_state = models.JSONField(default=dict, blank=True)  # wizard progress, resumable
    stats_snapshot = models.JSONField(default=dict, blank=True)

    def __str__(self):
        return f"{self.cadence} review started {self.started_at:%Y-%m-%d}"


class CaptureToken(models.Model):  # iOS Shortcut auth
    token = models.CharField(max_length=64, unique=True)  # secrets.token_urlsafe(32)
    label = models.CharField(max_length=60, default="iPhone")
    last_used_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.label


class NotificationLog(models.Model):
    kind = models.CharField(max_length=30)  # missed_block|follow_up|review_due|...
    ref_id = models.PositiveIntegerField(null=True, blank=True)
    sent_at = models.DateTimeField(auto_now_add=True)  # dedupe key: kind+ref_id+date

    class Meta:
        indexes = [
            models.Index(fields=["kind", "ref_id", "sent_at"]),
        ]


class NotificationSetting(models.Model):
    # Per-kind on/off toggle (Step 10's Settings page) - not in the original
    # Step 2 model list, added because this step's own spec explicitly calls
    # for the toggle UI and there's nowhere else to persist that state.
    # A kind with no row here defaults to enabled (see core/notifications.py).
    kind = models.CharField(max_length=30, unique=True)
    enabled = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.kind}: {'on' if self.enabled else 'off'}"


class ProjectTemplate(models.Model):
    """A reusable checklist of subtask titles (task #19). Instantiating one
    creates a real project Task plus its subtasks; the template itself is never
    a Task and holds no state beyond its ordered items."""
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class ProjectTemplateItem(models.Model):
    template = models.ForeignKey(ProjectTemplate, on_delete=models.CASCADE, related_name="items")
    title = models.CharField(max_length=300)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "id"]

    def __str__(self):
        return self.title
