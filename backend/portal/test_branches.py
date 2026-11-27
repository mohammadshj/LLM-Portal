import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.db import connection, connections
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase, skipUnlessDBFeature
from rest_framework.test import APIClient

from .branches import BranchState, RequestConflict
from .models import Account, Conversation, LanguageModel, Message, ModelConnection
from .services import finish_reply, reserve_turn
from .test_connections import success, upstream


class RevisionTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user("author")
        self.client = APIClient()
        self.client.force_authenticate(self.owner)
        self.chat = Conversation.objects.create(user=self.owner, title="tree")
        self.url = f"/api/conversations/{self.chat.pk}/"
        conn = ModelConnection.objects.create(
            name="test", base_url="https://models.example/v1", api_key_env=""
        )
        self.models = [
            LanguageModel.objects.create(
                input_price_per_million_rial=0,
                output_price_per_million_rial=0,
                name=n,
                model_id=n,
                provider="openai",
                connection=conn,
                thinking_contract="native_effort",
                thinking_levels=["low", "high"],
            )
            for n in ("A", "B", "C")
        ]
        self.ids = [m.pk for m in self.models]
        self.calls = []

        def handle(req):
            wire = json.loads(req.content)
            self.calls.append(wire)
            return success(wire["model"] + " / " + wire["messages"][-1]["content"])

        with_mock = upstream(handle)
        with_mock.__enter__()
        self.addCleanup(with_mock.__exit__, None, None, None)

    def send(self, text, **fields):
        if "edit_of" not in fields:
            fields.setdefault("model_ids", self.ids)
        result = self.client.post(self.url, {"content": text, **fields}, format="json")
        self.assertEqual(result.status_code, 200, result.data)
        return result.data

    def switch(self, anchor, target, **fields):
        return self.client.post(
            f"{self.url}messages/{anchor}/versions/",
            {"version_id": target, **fields},
            format="json",
        )

    def test_middle_edit_is_an_isolated_fork_with_independent_model_context(self):
        from .billing import change_credit

        change_credit(self.owner.pk, "grant", 10000, "branch-test", "test")
        LanguageModel.objects.filter(pk__in=self.ids).update(
            input_price_per_million_rial=1000000, output_price_per_million_rial=1000000
        )
        first = self.send("first")["active_leaf"]
        old = self.send(
            "original", reasoning={str(m): {"effort": "high"} for m in self.ids}
        )["active_leaf"]
        last = self.send("old continuation")["active_leaf"]
        previous = self.client.get(self.url).data["messages"]
        edited = self.send("edited", edit_of=old, expected_leaf=last)
        new = edited["active_leaf"]
        self.assertEqual(edited["versions"][new], [new, old])
        for wire in self.calls[-3:]:
            self.assertEqual(wire["reasoning_effort"], "high")
            self.assertEqual(
                [m["content"] for m in wire["messages"]],
                ["first", wire["model"] + " / first", "edited"],
            )
        new_leaf = self.send("new continuation")["active_leaf"]
        for wire in self.calls[-3:]:
            self.assertEqual(
                [m["content"] for m in wire["messages"]],
                [
                    "first",
                    wire["model"] + " / first",
                    "edited",
                    wire["model"] + " / edited",
                    "new continuation",
                ],
            )
        total = Account.objects.get(user=self.owner).tokens_used
        self.assertEqual(total, 450)
        self.assertEqual(
            self.client.get(f"{self.url}messages/{new}/versions/").data["version_ids"],
            [new, old],
        )
        restored = self.switch(new, old, expected_leaf=new_leaf)
        self.assertEqual(restored.data["active_leaf"], last)
        self.assertEqual(restored.data["messages"], previous)
        self.assertEqual(self.client.get(self.url).data["active_leaf"], last)
        self.assertEqual(self.switch(old, new).data["active_leaf"], new_leaf)
        self.assertEqual(len(self.calls), 15)
        self.assertEqual(Account.objects.get(user=self.owner).tokens_used, total)
        self.assertEqual(BranchState(self.chat).path, [first, new, new_leaf])
        self.assertEqual(self.owner.credit_entries.filter(kind="usage").count(), 15)
        self.assertEqual(Account.objects.get(user=self.owner).credit_used_rial, 450)

    def test_original_and_nine_edits_have_ten_versions(self):
        ids = [self.send("zero", model_ids=self.ids[:1])["active_leaf"]]
        for n in range(1, 10):
            data = self.send(str(n), edit_of=ids[-1])
            ids.append(data["active_leaf"])
        self.assertEqual(data["versions"][ids[-1]], ids[::-1])
        self.assertEqual(
            self.switch(ids[-1], ids[0]).data["messages"][0]["content"], "zero"
        )
        data = self.send(
            "from original",
            edit_of=ids[0],
            model_ids=self.ids[1:],
            reasoning={str(self.ids[1]): {"effort": "low"}},
        )
        self.assertEqual(len(data["messages"]), 3)
        self.assertEqual(len(data["versions"][data["active_leaf"]]), 11)
        self.assertEqual(len(self.calls), 12)

    def test_busy_stale_uuid_and_failed_admission_leave_existing_branch_intact(self):
        old = self.send("initial")["active_leaf"]
        key = uuid4()
        new, jobs = reserve_turn(
            self.owner,
            self.chat,
            "streaming",
            edit_of=old,
            request_id=key,
            expected_leaf=old,
        )
        self.assertEqual(self.switch(new.pk, old).status_code, 409)
        self.assertEqual(
            self.client.post(
                self.url, {"content": "busy", "edit_of": new.pk}, format="json"
            ).status_code,
            409,
        )
        for job in jobs:
            finish_reply(job.reply.pk, "cancelled", "partial")
        snapshot = self.client.get(self.url).data
        self.assertEqual(snapshot["messages"][-1]["status"], "cancelled")
        for fields, code in [
            ({"request_id": str(key)}, 409),
            ({"expected_leaf": old}, 409),
            ({"reasoning": {str(self.ids[0]): {"effort": "invented"}}}, 400),
        ]:
            self.assertEqual(
                self.client.post(
                    self.url,
                    {"content": "retry", "edit_of": new.pk, **fields},
                    format="json",
                ).status_code,
                code,
            )
        self.assertEqual(self.client.get(self.url).data, snapshot)
        self.assertEqual(self.switch(new.pk, old, expected_leaf=old).status_code, 409)
        self.assertEqual(self.switch(new.pk, old).status_code, 200)
        self.assertEqual(
            self.client.post(
                self.url, {"content": "inactive", "edit_of": new.pk}, format="json"
            ).status_code,
            409,
        )

    def test_versions_owner_scope_csrf_and_wrong_slot(self):
        a = self.send("a")["active_leaf"]
        b = self.send("b")["active_leaf"]
        self.assertEqual(self.switch(a, b).status_code, 404)
        csrf = APIClient(enforce_csrf_checks=True)
        csrf.force_login(self.owner)
        path = f"{self.url}messages/{a}/versions/"
        self.assertEqual(
            csrf.post(path, {"version_id": a}, format="json").status_code, 403
        )
        self.client.force_authenticate(get_user_model().objects.create_user("other"))
        self.assertEqual(self.client.get(path).status_code, 404)
        self.assertEqual(self.switch(a, a).status_code, 404)
        self.assertEqual(
            self.client.post(
                self.url, {"content": "q", "edit_of": a}, format="json"
            ).status_code,
            404,
        )


class ConcurrentEditTests(TransactionTestCase):
    @skipUnlessDBFeature("has_select_for_update")
    def test_two_tabs_editing_the_same_leaf_admit_only_one_revision(self):
        owner = get_user_model().objects.create_user("two-tabs")
        chat = Conversation.objects.create(user=owner, title="race")
        model = LanguageModel.objects.create(
            input_price_per_million_rial=0,
            output_price_per_million_rial=0,
            provider="demo",
            model_id="demo",
            name="Demo",
        )
        original, jobs = reserve_turn(owner, chat, "original", [model.pk])
        finish_reply(jobs[0].reply.pk, "completed", "answer", usage=(10, 4))
        ready = Barrier(2)

        def edit(content):
            try:
                ready.wait(timeout=5)
                turn, _ = reserve_turn(
                    owner, chat, content, edit_of=original.pk, expected_leaf=original.pk
                )
                return turn.pk
            except RequestConflict:
                return None
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(edit, ["one", "two"]))
        self.assertEqual(outcomes.count(None), 1)
        winner = next(pk for pk in outcomes if pk is not None)
        state = BranchState(chat)
        self.assertEqual(state.path, [winner])
        self.assertEqual(state.versions(winner), [winner, original.pk])
        self.assertEqual(chat.messages.filter(reserved_tokens__gt=0).count(), 1)
        self.assertEqual(Account.objects.get(user=owner).tokens_used, 14)


class BranchMigrationTests(TransactionTestCase):
    def test_linear_history_survives_and_conversation_can_still_be_purged(self):
        executor = MigrationExecutor(connection)
        before = [("portal", "0011_reasoning_profiles")]
        executor.migrate(before)
        try:
            apps = executor.loader.project_state(before).apps
            user = apps.get_model("auth", "User").objects.create(username="legacy")
            chat = apps.get_model("portal", "Conversation").objects.create(
                user=user, title="old"
            )
            rows = apps.get_model("portal", "Message").objects
            a = rows.create(conversation=chat, role="user", content="original")
            reply = rows.create(
                conversation=chat,
                role="assistant",
                parent=a,
                content="answer",
                response_duration_ms=2,
                total_tokens=5,
            )
            b = rows.create(conversation=chat, role="user", content="later")
        finally:
            executor = MigrationExecutor(connection)
            executor.migrate(executor.loader.graph.leaf_nodes())
        chat = Conversation.objects.get(pk=chat.pk)
        state = BranchState(chat)
        self.assertEqual(state.path, [a.pk, b.pk])
        self.assertEqual(state.versions(b.pk), [b.pk])
        self.assertEqual(
            Message.objects.values_list(
                "parent_id", "content", "response_duration_ms", "total_tokens"
            ).get(pk=reply.pk),
            (a.pk, "answer", 2, 5),
        )
        chat.delete()
        self.assertFalse(Message.objects.filter(pk=reply.pk).exists())
