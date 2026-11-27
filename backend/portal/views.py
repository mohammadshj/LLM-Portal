import json
from datetime import timedelta

from django.contrib.auth import authenticate, login, logout
from django.db import transaction
from django.db.models import Q, Exists, OuterRef, Sum
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_GET, require_POST
from rest_framework import generics, permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.views import APIView

from .billing import balance
from .branches import BranchState, UNSPECIFIED
from .models import Account, Conversation, LanguageModel, Message, ModelUsage
from .permissions import IsPortalAdmin, is_portal_admin
from .serializers import (
    BranchSelectionSerializer,
    ConversationSerializer,
    MessageSerializer,
    ModelSerializer,
    SendSerializer,
)
from .services import delete_conversation, request_cancel, reserve_turn, select_version
from .streaming import EventStreamResponse, TurnStream, send_message


@require_GET
def csrf(request):
    return JsonResponse({"csrfToken": get_token(request)})


@require_POST
@csrf_protect
def sign_in(request):
    try:
        data = json.loads(request.body)
        if not isinstance(data, dict):
            raise ValueError
        username, password = data.get("username", ""), data.get("password", "")
        if (
            not isinstance(username, str)
            or not isinstance(password, str)
            or len(username) > 150
            or len(password) > 1024
        ):
            raise ValueError
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"detail": "درخواست نامعتبر است."}, status=400)
    user = authenticate(request, username=username, password=password)
    if user is None:
        return JsonResponse({"detail": "نام کاربری یا رمز عبور صحیح نیست."}, status=400)
    login(request, user)
    return JsonResponse({"username": user.username})


@api_view(["POST"])
def sign_out(request):
    logout(request)
    return Response(status=204)


@api_view(["GET"])
def me(request):
    account, _ = Account.objects.get_or_create(user=request.user)
    return Response(
        {
            "username": request.user.username,
            "is_staff": is_portal_admin(request.user),
            "token_limit": account.token_limit,
            "tokens_used": account.tokens_used,
            **balance(account),
        }
    )


@api_view(["GET"])
@permission_classes([permissions.AllowAny])
def health(request):
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
    return Response({"status": "ok"})


class Models(generics.ListAPIView):
    serializer_class = ModelSerializer
    queryset = (
        LanguageModel.objects.filter(enabled=True)
        .select_related("connection")
        .order_by("id")
    )
    pagination_class = None


class Conversations(generics.ListCreateAPIView):
    serializer_class = ConversationSerializer

    def get_queryset(self):
        running = Message.objects.filter(
            conversation_id=OuterRef("pk"), role="user", status="running"
        )
        return (
            Conversation.objects.filter(
                title__icontains=self.request.query_params.get("q", "").strip()[:100],
                user=self.request.user,
                created_at__gte=timezone.now() - timedelta(days=30),
            )
            .annotate(is_processing=Exists(running))
            .order_by("-created_at", "-pk")
        )

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


def owned_conversation(request, pk):
    return get_object_or_404(
        Conversation,
        pk=pk,
        user=request.user,
        created_at__gte=timezone.now() - timedelta(days=30),
    )


class ConversationStream(APIView):
    # The successful response is SSE. DRF validation/auth errors are JSON
    # even when the caller explicitly requested text/event-stream.
    def perform_content_negotiation(self, request, force=False):
        return JSONRenderer(), "application/json"

    def post(self, request, pk):
        conversation = owned_conversation(request, pk)
        serializer = SendSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        turn, jobs = reserve_turn(
            request.user, conversation, **serializer.validated_data
        )
        return EventStreamResponse(TurnStream(turn, jobs))


@api_view(["POST"])
def cancel_generation(request, pk, request_id):
    conversation = owned_conversation(request, pk)
    cancelling = request_cancel(request.user, conversation, request_id)
    return Response({"status": "cancelling" if cancelling else "finished"})


@api_view(["GET", "POST", "PATCH", "DELETE"])
def conversation_detail(request, pk):
    conversation = owned_conversation(request, pk)
    if request.method == "PATCH":
        serializer = ConversationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        title = serializer.validated_data["title"]
        # Update only the title, even if retention removed the row concurrently.
        updated = Conversation.objects.filter(
            pk=conversation.pk, user=request.user
        ).update(title=title)
        if not updated:
            return Response(status=404)
        conversation.title = title
        return Response(ConversationSerializer(conversation).data)
    if request.method == "DELETE":
        delete_conversation(request.user, conversation)
        return Response(status=204)
    errors = []
    if request.method == "POST":
        serializer = SendSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        errors = send_message(request.user, conversation, **serializer.validated_data)
    return branch_detail(conversation, errors)


@transaction.atomic
def branch_detail(conversation, errors=()):
    # One consistent selection even when another tab switches branches mid-read.
    chat = get_object_or_404(
        Conversation.objects.select_for_update(),
        pk=conversation.pk,
        user_id=conversation.user_id,
    )
    branch = BranchState(chat)
    messages = list(
        chat.messages.filter(
            Q(pk__in=branch.path)
            | Q(parent_id__in=branch.path)
            | Q(role="assistant", parent__isnull=True)
        ).select_related("model")
    )
    active_request_id = next(
        (
            m.request_id
            for m in reversed(messages)
            if m.role == "user" and m.status == "running"
        ),
        None,
    )
    return Response(
        {
            "id": conversation.id,
            "active_request_id": active_request_id,
            "title": chat.title,
            "active_leaf": branch.leaf,
            "versions": {pk: branch.versions(pk) for pk in branch.path},
            "messages": MessageSerializer(messages, many=True).data,
            "errors": errors,
        }
    )


@api_view(["GET", "POST"])
def message_versions(request, pk, message_id):
    chat = owned_conversation(request, pk)
    if request.method == "GET":
        return Response({"version_ids": BranchState(chat).versions(message_id)})
    serializer = BranchSelectionSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    with transaction.atomic():
        select_version(
            request.user,
            chat,
            message_id,
            data["version_id"],
            data.get("expected_leaf", UNSPECIFIED),
        )
        return branch_detail(chat)


@api_view(["GET"])
@permission_classes([IsPortalAdmin])
def usage(request):
    return Response(
        {
            "accounts": list(
                Account.objects.values("user__username", "token_limit", "tokens_used")
            ),
            "models": list(
                ModelUsage.objects.values("model_id", "model__name").annotate(
                    input_tokens=Sum("input_tokens"),
                    output_tokens=Sum("output_tokens"),
                    unsplit_tokens=Sum("unsplit_tokens"),
                )
            ),
        }
    )


@api_view(["POST"])
def estimate(request, pk=None):
    chat = owned_conversation(request, pk) if pk is not None else None
    data = SendSerializer(data=request.data)
    data.is_valid(raise_exception=True)
    return Response(
        reserve_turn(request.user, chat, estimate=True, **data.validated_data)
    )
