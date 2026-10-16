from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    AssistantViewSet,
    CrawlJobViewSet,
    ConversationViewSet,
    SourceViewSet,
    TelegramConnectView,
    TelegramWebhookView,
    WidgetInitView,
    WidgetMessageView,
)

router = DefaultRouter()
router.register("assistants", AssistantViewSet, basename="assistant")
router.register("conversations", ConversationViewSet, basename="conversation")

urlpatterns = [
    path("assistants/<uuid:assistant_pk>/sources/", SourceViewSet.as_view({"get": "list", "post": "create"}), name="sources"),
    path("assistants/<uuid:assistant_pk>/sources/<uuid:pk>/", SourceViewSet.as_view({"get": "retrieve", "delete": "destroy"}), name="source-detail"),
    path("assistants/<uuid:assistant_pk>/sources/<uuid:pk>/retry/", SourceViewSet.as_view({"post": "retry"}), name="source-retry"),
    path("assistants/<uuid:assistant_pk>/crawls/", CrawlJobViewSet.as_view({"get": "list", "post": "create"}), name="crawls"),
    path("assistants/<uuid:assistant_pk>/crawls/<uuid:pk>/", CrawlJobViewSet.as_view({"get": "retrieve"}), name="crawl-detail"),
    path("assistants/<uuid:assistant_pk>/crawls/<uuid:pk>/process/", CrawlJobViewSet.as_view({"post": "process"}), name="crawl-process"),
    path("assistants/<uuid:assistant_pk>/crawls/<uuid:pk>/cancel/", CrawlJobViewSet.as_view({"post": "cancel"}), name="crawl-cancel"),
    path("assistants/<uuid:assistant_pk>/telegram/", TelegramConnectView.as_view(), name="telegram"),
    path("webhooks/telegram/<uuid:assistant_id>/", TelegramWebhookView.as_view(), name="telegram-webhook"),
    path("widget/init/", WidgetInitView.as_view(), name="widget-init"),
    path("widget/messages/", WidgetMessageView.as_view(), name="widget-message"),
    path("", include(router.urls)),
]
