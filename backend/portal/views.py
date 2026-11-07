import json
from datetime import timedelta

from django.contrib.auth import authenticate, login, logout
from django.db.models import Sum
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_GET, require_POST
from rest_framework import generics, permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from .models import Account, Conversation, LanguageModel, ModelUsage
from .serializers import (
    ConversationSerializer,
    MessageSerializer,
    ModelSerializer,
    SendSerializer,
)
from .services import send_message


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
            "is_staff": request.user.is_staff,
            "token_limit": account.token_limit,
            "tokens_used": account.tokens_used,
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
    queryset = LanguageModel.objects.filter(enabled=True).order_by("id")
    pagination_class = None


class Conversations(generics.ListCreateAPIView):
    serializer_class = ConversationSerializer

    def get_queryset(self):
        return Conversation.objects.filter(
            user=self.request.user, created_at__gte=timezone.now() - timedelta(days=30)
        )

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


@api_view(["GET", "POST", "DELETE"])
def conversation_detail(request, pk):
    conversation = get_object_or_404(
        Conversation,
        pk=pk,
        user=request.user,
        created_at__gte=timezone.now() - timedelta(days=30),
    )
    if request.method == "DELETE":
        conversation.delete()
        return Response(status=204)
    errors = []
    if request.method == "POST":
        serializer = SendSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        errors = send_message(request.user, conversation, **serializer.validated_data)
    return Response(
        {
            "id": conversation.id,
            "title": conversation.title,
            "messages": MessageSerializer(
                conversation.messages.select_related("model"), many=True
            ).data,
            "errors": errors,
        }
    )


@api_view(["GET"])
@permission_classes([permissions.IsAdminUser])
def usage(request):
    return Response(
        {
            "accounts": list(
                Account.objects.values("user__username", "token_limit", "tokens_used")
            ),
            "models": list(
                ModelUsage.objects.values("model__name").annotate(
                    input_tokens=Sum("input_tokens"), output_tokens=Sum("output_tokens")
                )
            ),
        }
    )
