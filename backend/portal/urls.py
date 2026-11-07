from django.urls import path

from . import views

urlpatterns = [
    path("auth/csrf/", views.csrf),
    path("auth/login/", views.sign_in),
    path("auth/logout/", views.sign_out),
    path("auth/me/", views.me),
    path("health/", views.health),
    path("models/", views.Models.as_view()),
    path("conversations/", views.Conversations.as_view()),
    path("conversations/<int:pk>/", views.conversation_detail),
    path("usage/", views.usage),
]
