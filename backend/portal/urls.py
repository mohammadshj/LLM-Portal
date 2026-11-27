from django.urls import path

from . import views
from . import billing_reports

urlpatterns = [
    path("auth/csrf/", views.csrf),
    path("auth/login/", views.sign_in),
    path("auth/logout/", views.sign_out),
    path("auth/me/", views.me),
    path("health/", views.health),
    path("models/", views.Models.as_view()),
    path("credits/<str:view>/report/", billing_reports.personal_report),
    path("admin/billing/<str:view>/", billing_reports.admin_report),
    path("credits/estimate/", views.estimate),
    path("conversations/<int:pk>/estimate/", views.estimate),
    path("conversations/", views.Conversations.as_view()),
    path("conversations/<int:pk>/", views.conversation_detail),
    path("conversations/<int:pk>/stream/", views.ConversationStream.as_view()),
    path(
        "conversations/<int:pk>/requests/<uuid:request_id>/cancel/",
        views.cancel_generation,
    ),
    path(
        "conversations/<int:pk>/messages/<int:message_id>/versions/",
        views.message_versions,
    ),
    path("usage/", views.usage),
]
