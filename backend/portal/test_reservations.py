from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.db import connections
from django.test import TransactionTestCase, skipUnlessDBFeature
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from .models import Account, Conversation, LanguageModel, Message, ModelUsage
from .services import (
    RequestConflict,
    finish_reply,
    recover_reservations,
    reserve_turn,
)


class ReservationTests(TransactionTestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("reservation")
        self.account = Account.objects.create(user=self.user, token_limit=500)
        self.model = LanguageModel.objects.create(
            name="Model", provider="demo", model_id="m", max_output_tokens=100
        )
        self.chats = [
            Conversation.objects.create(user=self.user, title=str(i)) for i in range(2)
        ]

    def reserve(self, chat, key=None):
        return reserve_turn(self.user, chat, "q", [self.model.pk], key or uuid4())

    def test_expiry_fences_late_writer_and_restores_admission(self):
        turn, jobs = self.reserve(self.chats[0])
        Message.objects.filter(pk=turn.pk).update(
            lease_until=timezone.now() - timedelta(seconds=1)
        )
        self.assertEqual(recover_reservations(), 1)
        self.assertEqual(
            finish_reply(jobs[0].reply_id, "completed", "late", (100, 100)), "failed"
        )
        self.assertEqual(Message.objects.get(pk=jobs[0].reply_id).reserved_tokens, 0)
        self.assertFalse(ModelUsage.objects.exists())
        self.assertEqual(recover_reservations(), 0)
        self.reserve(self.chats[0])

    def test_overreported_usage_preserves_other_reservations_and_exact_ledger(self):
        _, first = self.reserve(self.chats[0])
        _, second = self.reserve(self.chats[1])
        hold = Message.objects.get(pk=first[0].reply_id).reserved_tokens
        finish_reply(first[0].reply_id, "completed", "answer", (100, 900))
        finish_reply(first[0].reply_id, "completed", "duplicate", (100, 900))
        self.account.refresh_from_db()
        self.assertEqual(self.account.tokens_used, hold)
        self.assertEqual(
            Message.objects.get(pk=second[0].reply_id).reserved_tokens, hold
        )
        self.assertEqual(ModelUsage.objects.get(model=self.model).output_tokens, 900)

    def test_replaying_uuid_never_repeats_a_finished_request(self):
        key = uuid4()
        _, jobs = self.reserve(self.chats[0], key)
        finish_reply(jobs[0].reply_id, "completed", "answer", (1, 1))
        with self.assertRaises(RequestConflict):
            self.reserve(self.chats[0], key)
        self.assertEqual(Message.objects.count(), 2)

    @skipUnlessDBFeature("has_select_for_update")
    def test_different_chats_cannot_claim_same_credit(self):
        self.account.token_limit = 200  # One hold fits, two do not.
        self.account.save()
        barrier = Barrier(2)

        def worker(chat):
            try:
                barrier.wait(timeout=10)
                self.reserve(chat)
                return "reserved"
            except RequestConflict:
                raise
            except ValidationError:
                return "quota"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertCountEqual(pool.map(worker, self.chats), ["reserved", "quota"])

    def test_second_send_in_active_chat_conflicts_even_with_available_credit(self):
        self.reserve(self.chats[0])
        with self.assertRaises(RequestConflict):
            self.reserve(self.chats[0])
        self.reserve(self.chats[1])
