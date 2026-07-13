import json
import tempfile
from datetime import date, timedelta

from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import Area, CaptureToken, InboxItem, Note, RecurringTemplate, Tag, Task, TimeBlock
from core.tagging import extract_tags, sync_tags_from_text


class SmokeTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="sudipto", password="testpass123")

    def test_anonymous_redirected_to_login(self):
        response = self.client.get(reverse("today"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("login"), response.url)

    def test_login_then_base_renders(self):
        self.client.login(username="sudipto", password="testpass123")
        response = self.client.get(reverse("today"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "GTD")
        self.assertContains(response, "Today")


class TaskConstraintTests(TestCase):
    def test_project_cannot_have_a_parent(self):
        parent = Task.objects.create(title="Parent project", is_project=True)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Task.objects.create(title="Invalid", is_project=True, parent=parent)

    def test_non_project_subtask_is_allowed(self):
        parent = Task.objects.create(title="Parent project", is_project=True)
        child = Task.objects.create(title="Subtask", is_project=False, parent=parent)
        self.assertEqual(child.parent, parent)


class NextActionsTests(TestCase):
    def setUp(self):
        self.project = Task.objects.create(title="Ship v1.2", is_project=True)

    def test_flagged_subtask_wins(self):
        Task.objects.create(title="A", parent=self.project, sort_order=100)
        flagged = Task.objects.create(
            title="B", parent=self.project, sort_order=200, is_next_action=True
        )
        state, tasks = self.project.next_actions()
        self.assertEqual(state, "flagged")
        self.assertEqual(tasks, [flagged])

    def test_no_flagged_falls_back_to_first_incomplete_by_sort_order(self):
        second = Task.objects.create(title="B", parent=self.project, sort_order=200)
        first = Task.objects.create(title="A", parent=self.project, sort_order=100)
        state, tasks = self.project.next_actions()
        self.assertEqual(state, "implicit")
        self.assertEqual(tasks, [first])

    def test_no_incomplete_subtasks_needs_attention(self):
        Task.objects.create(
            title="Done", parent=self.project, completed_at=timezone.now()
        )
        state, tasks = self.project.next_actions()
        self.assertEqual(state, Task.NEEDS_ATTENTION)
        self.assertEqual(tasks, [])

    def test_project_with_no_subtasks_needs_attention(self):
        state, tasks = self.project.next_actions()
        self.assertEqual(state, Task.NEEDS_ATTENTION)
        self.assertEqual(tasks, [])

    def test_complete_blocked_without_force_when_subtasks_incomplete(self):
        Task.objects.create(title="A", parent=self.project)
        self.assertFalse(self.project.complete())
        self.assertIsNone(self.project.completed_at)

    def test_complete_with_force_completes_subtasks_too(self):
        sub = Task.objects.create(title="A", parent=self.project)
        self.assertTrue(self.project.complete(force=True))
        self.project.refresh_from_db()
        sub.refresh_from_db()
        self.assertIsNotNone(self.project.completed_at)
        self.assertIsNotNone(sub.completed_at)


class TrashPurgeTests(TestCase):
    def test_purgeable_returns_only_old_trashed_tasks(self):
        now = timezone.now()
        old = Task.objects.create(
            title="Old trash", list=Task.List.TRASH, trashed_at=now - timedelta(days=31)
        )
        recent = Task.objects.create(
            title="Recent trash", list=Task.List.TRASH, trashed_at=now - timedelta(days=5)
        )
        Task.objects.create(title="Not trashed")

        purgeable = Task.objects.purgeable(as_of=now)
        self.assertIn(old, purgeable)
        self.assertNotIn(recent, purgeable)


class CaptureApiTests(TestCase):
    def setUp(self):
        cache.clear()
        self.token = CaptureToken.objects.create(token="tok_abc123", label="iPhone")

    def test_missing_token_rejected(self):
        response = self.client.post(
            reverse("api_capture"),
            data=json.dumps({"title": "Buy milk"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 401)

    def test_invalid_token_rejected(self):
        response = self.client.post(
            reverse("api_capture"),
            data=json.dumps({"title": "Buy milk"}),
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer not-a-real-token",
        )
        self.assertEqual(response.status_code, 401)

    def test_valid_token_creates_inbox_item(self):
        response = self.client.post(
            reverse("api_capture"),
            data=json.dumps({"title": "Buy milk", "description": "2%"}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.token.token}",
        )
        self.assertEqual(response.status_code, 201)
        item_id = response.json()["id"]
        item = InboxItem.objects.get(pk=item_id)
        self.assertEqual(item.title, "Buy milk")
        self.assertEqual(item.description, "2%")
        self.assertEqual(item.source, "shortcut")
        self.token.refresh_from_db()
        self.assertIsNotNone(self.token.last_used_at)

    def test_missing_title_rejected(self):
        response = self.client.post(
            reverse("api_capture"),
            data=json.dumps({}),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.token.token}",
        )
        self.assertEqual(response.status_code, 400)

    def test_rate_limit_enforced(self):
        headers = {"HTTP_AUTHORIZATION": f"Bearer {self.token.token}"}
        for _ in range(60):
            response = self.client.post(
                reverse("api_capture"),
                data=json.dumps({"title": "x"}),
                content_type="application/json",
                **headers,
            )
            self.assertEqual(response.status_code, 201)
        response = self.client.post(
            reverse("api_capture"),
            data=json.dumps({"title": "one too many"}),
            content_type="application/json",
            **headers,
        )
        self.assertEqual(response.status_code, 429)

    def test_endpoint_is_login_exempt(self):
        # No client.login() call anywhere in this class - if the endpoint required
        # login, every test above would 302 instead of returning its real status.
        response = self.client.post(reverse("api_capture"))
        self.assertNotEqual(response.status_code, 302)


class TwoMinuteRuleTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="sudipto", password="testpass123")
        self.client.login(username="sudipto", password="testpass123")

    def test_done_directly_never_becomes_a_task(self):
        item = InboxItem.objects.create(title="Reply to Anika")
        response = self.client.post(reverse("inbox_item_done", args=[item.id]))
        self.assertEqual(response.status_code, 200)
        item.refresh_from_db()
        self.assertTrue(item.done_directly)
        self.assertIsNotNone(item.processed_at)
        self.assertEqual(Task.objects.count(), 0)

    def test_done_item_drops_out_of_inbox_list(self):
        item = InboxItem.objects.create(title="Reply to Anika")
        self.client.post(reverse("inbox_item_done", args=[item.id]))
        response = self.client.get(reverse("inbox"))
        self.assertNotContains(response, "Reply to Anika")


class TagParserTests(TestCase):
    def test_context_and_plain_tag(self):
        tags = list(extract_tags("Call mom @phone #family"))
        self.assertIn(("phone", True), tags)
        self.assertIn(("family", False), tags)

    def test_case_folded(self):
        tags = list(extract_tags("@Errand"))
        self.assertEqual(tags, [("errand", True)])

    def test_no_match_mid_word_email_or_url_fragment(self):
        # @/# only tag at the start of text or after whitespace, so an email
        # local part or a URL fragment doesn't get misread as a tag token.
        self.assertEqual(list(extract_tags("john@example.com")), [])
        self.assertEqual(list(extract_tags("see docs.com/page#comment")), [])

    def test_empty_text_yields_nothing(self):
        self.assertEqual(list(extract_tags("")), [])
        self.assertEqual(list(extract_tags(None)), [])

    def test_sync_creates_and_reuses_tags(self):
        task = Task.objects.create(title="Call mom @phone")
        sync_tags_from_text(task, task.title)
        self.assertEqual(Tag.objects.filter(name="phone", is_context=True).count(), 1)
        self.assertIn("phone", task.tags.values_list("name", flat=True))

        other = Task.objects.create(title="Call dad @phone")
        sync_tags_from_text(other, other.title)
        self.assertEqual(Tag.objects.filter(name="phone").count(), 1)

    def test_sync_is_additive_never_removes_existing_tags(self):
        task = Task.objects.create(title="Something #keep")
        sync_tags_from_text(task, task.title)
        kept_tag = Tag.objects.get(name="keep")
        sync_tags_from_text(task, "no tags here at all")
        self.assertIn(kept_tag, task.tags.all())

    def test_sync_across_multiple_texts_no_duplicate_tags(self):
        task = Task.objects.create(title="Title @same", description="Body @same")
        sync_tags_from_text(task, task.title, task.description)
        self.assertEqual(task.tags.filter(name="same").count(), 1)


class ClarifyWizardTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="sudipto", password="testpass123")
        self.client.login(username="sudipto", password="testpass123")

    def test_process_start_redirects_to_oldest_unprocessed_item(self):
        older = InboxItem.objects.create(title="Older")
        InboxItem.objects.create(title="Newer")
        response = self.client.get(reverse("inbox_process"))
        self.assertRedirects(response, reverse("clarify_actionable", args=[older.id]))

    def test_process_start_shows_finished_screen_when_empty(self):
        response = self.client.get(reverse("inbox_process"))
        self.assertTemplateUsed(response, "core/clarify/finished.html")
        self.assertContains(response, "Inbox zero")

    def test_no_cherry_picking_always_returns_oldest_regardless_of_pk(self):
        older = InboxItem.objects.create(title="Older")
        newer = InboxItem.objects.create(title="Newer")
        # Even asking for the actionable screen of the newer item directly
        # doesn't change which item process_start/inbox_process hands back.
        self.client.get(reverse("clarify_actionable", args=[newer.id]))
        response = self.client.get(reverse("inbox_process"))
        self.assertRedirects(response, reverse("clarify_actionable", args=[older.id]))

    def test_trash_path_creates_trashed_task_not_raw_discard(self):
        item = InboxItem.objects.create(title="Junk mail", description="spam")
        self.client.post(reverse("clarify_trash", args=[item.id]))
        item.refresh_from_db()
        self.assertIsNotNone(item.processed_at)
        task = Task.objects.get(title="Junk mail")
        self.assertEqual(task.list, Task.List.TRASH)
        self.assertIsNotNone(task.trashed_at)

    def test_done_path_marks_done_directly_never_creates_task(self):
        item = InboxItem.objects.create(title="Quick reply")
        self.client.post(reverse("clarify_done", args=[item.id]))
        item.refresh_from_db()
        self.assertTrue(item.done_directly)
        self.assertIsNotNone(item.processed_at)
        self.assertEqual(Task.objects.count(), 0)

    def test_someday_path_creates_someday_task_and_tags(self):
        item = InboxItem.objects.create(title="Learn pottery")
        response = self.client.post(
            reverse("clarify_someday", args=[item.id]),
            {"title": "Learn pottery @hobby", "description": ""},
        )
        self.assertEqual(response.status_code, 302)
        task = Task.objects.get(title="Learn pottery @hobby")
        self.assertEqual(task.list, Task.List.SOMEDAY)
        self.assertIn("hobby", task.tags.values_list("name", flat=True))
        item.refresh_from_db()
        self.assertIsNotNone(item.processed_at)

    def test_reference_path_creates_note(self):
        item = InboxItem.objects.create(title="Article link", description="https://example.com")
        response = self.client.post(
            reverse("clarify_reference", args=[item.id]),
            {"title": "Article link", "body": "https://example.com #reading"},
        )
        self.assertEqual(response.status_code, 302)
        note = Note.objects.get(title="Article link")
        self.assertIn("reading", note.tags.values_list("name", flat=True))
        item.refresh_from_db()
        self.assertIsNotNone(item.processed_at)

    def test_single_action_path_creates_next_task(self):
        item = InboxItem.objects.create(title="Email Bob")
        response = self.client.post(
            reverse("clarify_single", args=[item.id]),
            {"title": "Email Bob @email", "description": "", "horizon": Task.Horizon.ANYTIME},
        )
        self.assertEqual(response.status_code, 302)
        task = Task.objects.get(title="Email Bob @email")
        self.assertEqual(task.list, Task.List.NEXT)
        self.assertFalse(task.is_project)
        self.assertIn("email", task.tags.values_list("name", flat=True))

    def test_project_path_requires_at_least_one_subtask(self):
        item = InboxItem.objects.create(title="Plan trip")
        response = self.client.post(
            reverse("clarify_project", args=[item.id]),
            {"title": "Plan trip", "description": ""},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "next action")
        self.assertFalse(Task.objects.filter(title="Plan trip").exists())
        item.refresh_from_db()
        self.assertIsNone(item.processed_at)

    def test_project_path_creates_project_with_flagged_first_subtask(self):
        item = InboxItem.objects.create(title="Plan trip")
        response = self.client.post(
            reverse("clarify_project", args=[item.id]),
            {
                "title": "Plan trip",
                "description": "",
                "subtask_title": ["Book flights", "Book hotel"],
            },
        )
        self.assertEqual(response.status_code, 302)
        project = Task.objects.get(title="Plan trip")
        self.assertTrue(project.is_project)
        subtasks = list(project.subtasks.order_by("sort_order"))
        self.assertEqual([s.title for s in subtasks], ["Book flights", "Book hotel"])
        self.assertTrue(subtasks[0].is_next_action)
        self.assertFalse(subtasks[1].is_next_action)

    def test_delegate_path_creates_waiting_task(self):
        item = InboxItem.objects.create(title="Get contract signed")
        response = self.client.post(
            reverse("clarify_delegate", args=[item.id]),
            {
                "title": "Get contract signed",
                "description": "",
                "waiting_on": "Legal team",
                "follow_up_after_days": 5,
            },
        )
        self.assertEqual(response.status_code, 302)
        task = Task.objects.get(title="Get contract signed")
        self.assertEqual(task.list, Task.List.WAITING)
        self.assertEqual(task.waiting_on, "Legal team")
        self.assertEqual(task.waiting_since, timezone.now().date())

    def test_form_screens_render_on_get_with_tag_typeahead_wired(self):
        # Regression check for the field_tagged.html partial (Alpine
        # tagTypeahead) added alongside the plain form fields - a broken
        # include there would 500 every GET to these screens.
        item = InboxItem.objects.create(title="Something")
        for name in (
            "clarify_someday",
            "clarify_reference",
            "clarify_single",
            "clarify_project",
            "clarify_delegate",
        ):
            response = self.client.get(reverse(name, args=[item.id]))
            self.assertEqual(response.status_code, 200, name)
            self.assertContains(response, "tagTypeahead(")

    def test_progress_counter_advances_across_the_session(self):
        first = InboxItem.objects.create(title="First")
        second = InboxItem.objects.create(title="Second")
        response = self.client.get(reverse("clarify_actionable", args=[first.id]))
        self.assertContains(response, "1 / 2")
        self.client.post(reverse("clarify_trash", args=[first.id]))
        response = self.client.get(reverse("clarify_actionable", args=[second.id]))
        self.assertContains(response, "2 / 2")


class TodayViewCompositionTests(TestCase):
    """The four inclusion rules from solution-plan.md Step 5."""

    def setUp(self):
        self.user = User.objects.create_user(username="sudipto", password="testpass123")
        self.client.login(username="sudipto", password="testpass123")
        self.today = timezone.localtime().date()

    def test_horizon_today_included(self):
        t = Task.objects.create(title="Horizon today", horizon=Task.Horizon.TODAY)
        response = self.client.get(reverse("today"))
        self.assertContains(response, t.title)

    def test_task_with_timeblock_today_included(self):
        t = Task.objects.create(title="Blocked today", horizon=Task.Horizon.ANYTIME)
        TimeBlock.objects.create(
            task=t,
            start=timezone.now().replace(hour=14, minute=0),
            end=timezone.now().replace(hour=15, minute=0),
        )
        response = self.client.get(reverse("today"))
        self.assertContains(response, t.title)

    def test_due_today_and_overdue_included(self):
        due_today = Task.objects.create(title="Due today", horizon=Task.Horizon.ANYTIME, due_date=self.today)
        overdue = Task.objects.create(
            title="Overdue task", horizon=Task.Horizon.ANYTIME, due_date=self.today - timedelta(days=3)
        )
        response = self.client.get(reverse("today"))
        self.assertContains(response, due_today.title)
        self.assertContains(response, overdue.title)

    def test_overdue_recurring_instance_included(self):
        template = RecurringTemplate.objects.create(title="Weekly thing", rrule="FREQ=WEEKLY")
        instance = Task.objects.create(
            title="Recurring instance",
            horizon=Task.Horizon.ANYTIME,
            recurring_template=template,
            occurrence_date=self.today - timedelta(days=1),
        )
        response = self.client.get(reverse("today"))
        self.assertContains(response, instance.title)

    def test_anytime_task_not_in_curated_but_in_anytime_section(self):
        t = Task.objects.create(title="Plain anytime task", horizon=Task.Horizon.ANYTIME)
        response = self.client.get(reverse("today"))
        self.assertContains(response, t.title)
        self.assertNotIn(t.id, [c.id for c in response.context["curated"]])
        self.assertIn(t.id, [a.id for a in response.context["anytime"]])

    def test_project_shells_excluded_from_today(self):
        Task.objects.create(title="A project", is_project=True, horizon=Task.Horizon.TODAY)
        response = self.client.get(reverse("today"))
        self.assertEqual(len(response.context["curated"]), 0)


class ReorderPersistenceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="sudipto", password="testpass123")
        self.client.login(username="sudipto", password="testpass123")
        self.a = Task.objects.create(title="A", sort_order=100)
        self.b = Task.objects.create(title="B", sort_order=200)
        self.c = Task.objects.create(title="C", sort_order=300)

    def test_reorder_moves_task_after_specified_sibling(self):
        # Drag C to sit right after A (i.e. new order A, C, B).
        self.client.post(reverse("task_reorder", args=[self.c.id]), {"after": self.a.id})
        self.a.refresh_from_db()
        self.b.refresh_from_db()
        self.c.refresh_from_db()
        self.assertTrue(self.a.sort_order < self.c.sort_order < self.b.sort_order)

    def test_reorder_to_front_when_no_after_given(self):
        self.client.post(reverse("task_reorder", args=[self.c.id]), {})
        self.a.refresh_from_db()
        self.c.refresh_from_db()
        self.assertTrue(self.c.sort_order < self.a.sort_order)

    def test_reorder_scoped_to_same_parent_and_list(self):
        project = Task.objects.create(title="Project", is_project=True)
        sub = Task.objects.create(title="Sub", parent=project, sort_order=100)
        # Reordering a top-level task must never touch a subtask's sort_order.
        self.client.post(reverse("task_reorder", args=[self.c.id]), {"after": self.a.id})
        sub.refresh_from_db()
        self.assertEqual(sub.sort_order, 100)


class RolloverCommandTests(TestCase):
    def test_today_horizon_always_carried_over(self):
        t = Task.objects.create(title="T", horizon=Task.Horizon.TODAY)
        call_command("rollover", "--as-of", "2026-07-15")  # a Wednesday
        t.refresh_from_db()
        self.assertEqual(t.carried_over_count, 1)

    def test_week_horizon_only_carried_over_on_monday(self):
        t = Task.objects.create(title="W", horizon=Task.Horizon.WEEK)
        call_command("rollover", "--as-of", "2026-07-15")  # Wednesday - not Monday
        t.refresh_from_db()
        self.assertEqual(t.carried_over_count, 0)

        call_command("rollover", "--as-of", "2026-07-13")  # a Monday
        t.refresh_from_db()
        self.assertEqual(t.carried_over_count, 1)

    def test_month_horizon_only_carried_over_on_first(self):
        t = Task.objects.create(title="M", horizon=Task.Horizon.MONTH)
        call_command("rollover", "--as-of", "2026-07-15")
        t.refresh_from_db()
        self.assertEqual(t.carried_over_count, 0)

        call_command("rollover", "--as-of", "2026-08-01")
        t.refresh_from_db()
        self.assertEqual(t.carried_over_count, 1)

    def test_completed_tasks_never_carried_over(self):
        t = Task.objects.create(title="Done", horizon=Task.Horizon.TODAY, completed_at=timezone.now())
        call_command("rollover", "--as-of", "2026-07-15")
        t.refresh_from_db()
        self.assertEqual(t.carried_over_count, 0)


class TagMergeTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="sudipto", password="testpass123")
        self.client.login(username="sudipto", password="testpass123")
        self.source = Tag.objects.create(name="errand")
        self.target = Tag.objects.create(name="errands")
        self.task = Task.objects.create(title="Buy milk")
        self.task.tags.add(self.source)
        self.note = Note.objects.create(title="Shop list")
        self.note.tags.add(self.source)

    def test_merge_repoints_tasks_and_notes_and_deletes_source(self):
        self.client.post(reverse("tag_merge", args=[self.source.id]), {"target": self.target.id})
        self.assertFalse(Tag.objects.filter(id=self.source.id).exists())
        self.assertIn(self.target, self.task.tags.all())
        self.assertIn(self.target, self.note.tags.all())

    def test_merge_into_self_is_a_no_op_and_keeps_the_tag(self):
        self.client.post(reverse("tag_merge", args=[self.source.id]), {"target": self.source.id})
        self.assertTrue(Tag.objects.filter(id=self.source.id).exists())


class ProjectViewTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="sudipto", password="testpass123")
        self.client.login(username="sudipto", password="testpass123")

    def test_project_with_no_subtasks_shows_stalled_badge(self):
        project = Task.objects.create(title="Empty project", is_project=True)
        response = self.client.get(reverse("projects"))
        self.assertContains(response, "stalled?")
        response = self.client.get(reverse("project_detail", args=[project.id]))
        self.assertContains(response, "No next action")

    def test_project_with_unflagged_subtasks_shows_no_next_badge(self):
        project = Task.objects.create(title="Project", is_project=True)
        Task.objects.create(title="Sub", parent=project)
        response = self.client.get(reverse("projects"))
        self.assertContains(response, "no next")

    def test_project_with_flagged_subtask_shows_no_stall_badge(self):
        project = Task.objects.create(title="Healthy project", is_project=True)
        Task.objects.create(title="Sub", parent=project, is_next_action=True)
        response = self.client.get(reverse("projects"))
        self.assertNotContains(response, "stalled?")
        self.assertNotContains(response, "no next")

    def test_add_subtask_auto_flags_first_one_only(self):
        project = Task.objects.create(title="Project", is_project=True)
        self.client.post(reverse("project_add_subtask", args=[project.id]), {"title": "First"})
        self.client.post(reverse("project_add_subtask", args=[project.id]), {"title": "Second"})
        subs = list(project.subtasks.order_by("sort_order"))
        self.assertTrue(subs[0].is_next_action)
        self.assertFalse(subs[1].is_next_action)

    def test_flag_next_toggle(self):
        project = Task.objects.create(title="Project", is_project=True)
        sub = Task.objects.create(title="Sub", parent=project)
        self.client.post(reverse("project_flag_next", args=[project.id, sub.id]))
        sub.refresh_from_db()
        self.assertTrue(sub.is_next_action)
        self.client.post(reverse("project_flag_next", args=[project.id, sub.id]))
        sub.refresh_from_db()
        self.assertFalse(sub.is_next_action)


class WaitingSomedayTrashTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="sudipto", password="testpass123")
        self.client.login(username="sudipto", password="testpass123")

    def test_waiting_got_it_moves_to_next(self):
        t = Task.objects.create(title="Waiting task", list=Task.List.WAITING, waiting_since=date.today())
        self.client.post(reverse("waiting_got_it", args=[t.id]))
        t.refresh_from_db()
        self.assertEqual(t.list, Task.List.NEXT)
        self.assertIsNone(t.waiting_since)

    def test_waiting_nudge_resets_waiting_since(self):
        t = Task.objects.create(
            title="Waiting task", list=Task.List.WAITING, waiting_since=date.today() - timedelta(days=10)
        )
        self.client.post(reverse("waiting_nudge", args=[t.id]))
        t.refresh_from_db()
        self.assertEqual(t.waiting_since, date.today())

    def test_someday_activate_moves_to_next(self):
        t = Task.objects.create(title="Someday task", list=Task.List.SOMEDAY)
        self.client.post(reverse("someday_activate", args=[t.id]))
        t.refresh_from_db()
        self.assertEqual(t.list, Task.List.NEXT)

    def test_trash_restore(self):
        t = Task.objects.create(title="Trashed", list=Task.List.TRASH, trashed_at=timezone.now())
        self.client.post(reverse("task_restore", args=[t.id]))
        t.refresh_from_db()
        self.assertEqual(t.list, Task.List.NEXT)
        self.assertIsNone(t.trashed_at)

    def test_trash_row_hides_complete_circle(self):
        # Regression: task_row.html used `show_complete|default:True`, and
        # Django's `default` filter treats False as "unset" and substitutes
        # the default - silently turning an explicit show_complete=False
        # back into True. Trash rows must not render a complete button.
        Task.objects.create(title="Trashed", list=Task.List.TRASH, trashed_at=timezone.now())
        response = self.client.get(reverse("trash"))
        self.assertNotContains(response, 'aria-label="Complete"')

    def test_trash_purge_deletes_permanently(self):
        t = Task.objects.create(title="Trashed", list=Task.List.TRASH, trashed_at=timezone.now())
        self.client.post(reverse("task_purge", args=[t.id]))
        self.assertFalse(Task.objects.filter(id=t.id).exists())

    def test_task_move_to_trash_sets_trashed_at(self):
        t = Task.objects.create(title="Task")
        self.client.post(reverse("task_move", args=[t.id, "trash"]))
        t.refresh_from_db()
        self.assertEqual(t.list, Task.List.TRASH)
        self.assertIsNotNone(t.trashed_at)

    def test_task_complete_and_reopen(self):
        t = Task.objects.create(title="Task")
        self.client.post(reverse("task_complete", args=[t.id]))
        t.refresh_from_db()
        self.assertIsNotNone(t.completed_at)
        self.client.post(reverse("task_reopen", args=[t.id]))
        t.refresh_from_db()
        self.assertIsNone(t.completed_at)

    def test_project_complete_blocked_without_force(self):
        project = Task.objects.create(title="Project", is_project=True)
        Task.objects.create(title="Sub", parent=project)
        response = self.client.post(reverse("task_complete", args=[project.id]))
        self.assertEqual(response.status_code, 409)
        project.refresh_from_db()
        self.assertIsNone(project.completed_at)


class ScreenRenderSmokeTests(TestCase):
    """Every new Epic 5 screen renders without error, empty or populated."""

    def setUp(self):
        self.user = User.objects.create_user(username="sudipto", password="testpass123")
        self.client.login(username="sudipto", password="testpass123")

    def test_all_screens_render_empty(self):
        for name in ("today", "week", "month", "tasks", "projects", "waiting", "someday", "trash", "tags"):
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 200, name)

    def test_all_screens_render_populated(self):
        area = Area.objects.create(name="Home")
        tag = Tag.objects.create(name="errand", is_context=True)
        task = Task.objects.create(title="A next action", area=area, due_date=date.today())
        task.tags.add(tag)
        Task.objects.create(title="Waiting on someone", list=Task.List.WAITING, waiting_since=date.today())
        Task.objects.create(title="Someday maybe", list=Task.List.SOMEDAY)
        Task.objects.create(title="Trashed thing", list=Task.List.TRASH, trashed_at=timezone.now())
        project = Task.objects.create(title="A project", is_project=True)
        Task.objects.create(title="A subtask", parent=project, is_next_action=True)

        for name in ("today", "week", "month", "tasks", "projects", "waiting", "someday", "trash", "tags"):
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 200, name)

        response = self.client.get(reverse("project_detail", args=[project.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "A subtask")


class NoteSearchTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="sudipto", password="testpass123")
        self.client.login(username="sudipto", password="testpass123")

    def test_search_matches_body_text(self):
        Note.objects.create(title="Recipe", body="A great sourdough starter guide.")
        Note.objects.create(title="Unrelated", body="Something else entirely.")
        response = self.client.get(reverse("notes"), {"q": "sourdough"})
        self.assertContains(response, "Recipe")
        self.assertNotContains(response, "Unrelated")

    def test_search_matches_title_text(self):
        Note.objects.create(title="Sourdough starter guide", body="")
        response = self.client.get(reverse("notes"), {"q": "starter"})
        self.assertContains(response, "Sourdough starter guide")

    def test_trashed_notes_excluded_from_list_and_search(self):
        Note.objects.create(title="Gone", body="findme", trashed_at=timezone.now())
        response = self.client.get(reverse("notes"))
        self.assertNotContains(response, "Gone")
        response = self.client.get(reverse("notes"), {"q": "findme"})
        self.assertNotContains(response, "Gone")

    def test_note_create_and_tag_parsing(self):
        self.client.post(reverse("note_create"), {"title": "Shopping", "body": "Milk @errand #home"})
        note = Note.objects.get(title="Shopping")
        names = set(note.tags.values_list("name", flat=True))
        self.assertEqual(names, {"errand", "home"})

    def test_note_update_renders_markdown(self):
        note = Note.objects.create(title="Doc", body="plain")
        self.client.post(reverse("note_update", args=[note.id]), {"title": "Doc", "body": "# Heading\n\nSome *text*"})
        response = self.client.get(reverse("note_detail", args=[note.id]))
        self.assertContains(response, "<h1>Heading</h1>")

    def test_note_delete_is_soft(self):
        note = Note.objects.create(title="To trash", body="")
        self.client.post(reverse("note_delete", args=[note.id]))
        note.refresh_from_db()
        self.assertIsNotNone(note.trashed_at)
        self.assertTrue(Note.objects.filter(id=note.id).exists())


class TaskToNoteConversionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="sudipto", password="testpass123")
        self.client.login(username="sudipto", password="testpass123")

    def test_conversion_copies_fields_tags_and_trashes_task(self):
        tag = Tag.objects.create(name="reading")
        task = Task.objects.create(title="Interesting article", description="Some notes about it")
        task.tags.add(tag)

        self.client.post(reverse("task_convert_to_note", args=[task.id]))

        note = Note.objects.get(title="Interesting article")
        self.assertEqual(note.body, "Some notes about it")
        self.assertIn(tag, note.tags.all())

        task.refresh_from_db()
        self.assertEqual(task.list, Task.List.TRASH)
        self.assertIsNotNone(task.trashed_at)


class InboxReferenceConversionTests(TestCase):
    """Re-confirms Epic 4's Reference path lands in the real Notes module now
    that it exists (task-breakdown.md Epic 6: 'verify here')."""

    def setUp(self):
        self.user = User.objects.create_user(username="sudipto", password="testpass123")
        self.client.login(username="sudipto", password="testpass123")

    def test_reference_path_note_is_searchable(self):
        item = InboxItem.objects.create(title="Article", description="Long read about gardening")
        self.client.post(
            reverse("clarify_reference", args=[item.id]),
            {"title": "Article", "body": "Long read about gardening #reading"},
        )
        response = self.client.get(reverse("notes"), {"q": "gardening"})
        self.assertContains(response, "Article")


_MEDIA_TMPDIR = tempfile.mkdtemp(prefix="gtd_test_media_")


@override_settings(MEDIA_ROOT=_MEDIA_TMPDIR)
class NoteScreenSmokeTests(TestCase):
    # Attachment uploads hit real FileSystemStorage (not transactional like
    # the DB), so MEDIA_ROOT is redirected to a throwaway temp dir for this
    # class - otherwise test runs leave files behind in the real media/.
    def setUp(self):
        self.user = User.objects.create_user(username="sudipto", password="testpass123")
        self.client.login(username="sudipto", password="testpass123")

    def test_notes_and_create_render_empty(self):
        for name in ("notes", "note_create"):
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 200, name)

    def test_note_detail_renders_with_attachment(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        note = Note.objects.create(title="Doc", body="body text")
        self.client.post(
            reverse("note_attachment_upload", args=[note.id]),
            {"file": SimpleUploadedFile("notes.txt", b"hello")},
        )
        response = self.client.get(reverse("note_detail", args=[note.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "notes.txt")

    def test_oversized_attachment_rejected(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        note = Note.objects.create(title="Doc", body="")
        big_file = SimpleUploadedFile("big.bin", b"x" * (21 * 1024 * 1024))
        self.client.post(reverse("note_attachment_upload", args=[note.id]), {"file": big_file})
        self.assertEqual(note.attachments.count(), 0)
