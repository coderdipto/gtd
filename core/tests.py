import json
from datetime import timedelta

from django.contrib.auth.models import User
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import CaptureToken, InboxItem, Note, Tag, Task
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
