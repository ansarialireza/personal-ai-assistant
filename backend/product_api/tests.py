import socket
import uuid
import hashlib
from unittest.mock import patch
from types import SimpleNamespace

import httpx
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase, override_settings
from rest_framework.response import Response
from rest_framework.test import APIClient

from product_api import crawler
from product_api.extractors import ExtractionError, extract
from product_api.integrations import AiBackendClient, RagCoreClient
from product_api.integrations import IntegrationError
from product_api.models import Assistant, ChannelConnection, ChannelEvent, Conversation, CrawlJob, Message, Source
from product_api.telegram import encrypt_token

User = get_user_model()


def make_assistant(owner, **overrides):
    values = {
        "owner": owner,
        "remote_assistant_id": uuid.uuid4(),
        "remote_knowledge_base_id": 41,
        "name": "Research assistant",
        "widget_enabled": True,
    }
    values.update(overrides)
    return Assistant.objects.create(**values)


class AuthenticationAndOwnershipTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.owner = User.objects.create_user(username="owner@example.test", email="owner@example.test", password="Strong-Pass-456!")
        self.other = User.objects.create_user(username="other@example.test", email="other@example.test", password="Strong-Pass-789!")
        self.assistant = make_assistant(self.owner)
        self.source = Source.objects.create(assistant=self.assistant, kind="text", title="Notes", content="Private source.")
        self.conversation = Conversation.objects.create(assistant=self.assistant, channel="playground")

    def test_registration_and_token_login(self):
        response = self.client.post("/api/v1/auth/register/", {
            "email": "new@example.test",
            "password": "A-very-strong-password-867!",
        })
        self.assertEqual(response.status_code, 201)
        self.assertIn("access", response.data)
        self.assertTrue(User.objects.filter(email="new@example.test").exists())
        login = self.client.post("/api/v1/auth/token/", {
            "username": "new@example.test",
            "password": "A-very-strong-password-867!",
        })
        self.assertEqual(login.status_code, 200)

    def test_owner_resources_are_not_visible_to_another_user(self):
        self.client.force_authenticate(self.other)
        self.assertEqual(self.client.get(f"/api/v1/assistants/{self.assistant.pk}/").status_code, 404)
        self.assertEqual(self.client.get(f"/api/v1/assistants/{self.assistant.pk}/sources/").data, [])
        self.assertEqual(self.client.get(f"/api/v1/conversations/{self.conversation.pk}/").status_code, 404)

    def test_another_user_cannot_modify_or_delete_assistant(self):
        self.client.force_authenticate(self.other)
        response = self.client.patch(
            f"/api/v1/assistants/{self.assistant.pk}/",
            {"name": "Stolen"},
            format="json",
        )
        self.assertEqual(response.status_code, 404)
        response = self.client.delete(f"/api/v1/assistants/{self.assistant.pk}/")
        self.assertEqual(response.status_code, 404)
        self.assistant.refresh_from_db()
        self.assertEqual(self.assistant.name, "Research assistant")

    def test_another_user_cannot_read_or_delete_source(self):
        self.client.force_authenticate(self.other)
        self.assertEqual(
            self.client.get(f"/api/v1/assistants/{self.assistant.pk}/sources/{self.source.pk}/").status_code,
            404,
        )
        self.assertEqual(
            self.client.delete(f"/api/v1/assistants/{self.assistant.pk}/sources/{self.source.pk}/").status_code,
            404,
        )
        self.assertTrue(Source.objects.filter(pk=self.source.pk).exists())

    def test_profile_requires_authentication(self):
        self.assertEqual(self.client.get("/api/v1/auth/me/").status_code, 401)


class ProductFlowTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="person@example.test", email="person@example.test", password="Strong-Pass-456!")
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.assistant = make_assistant(self.user)

    @override_settings(AI_DEFAULT_MODEL="configured-model", AI_BACKEND_API_KEY="ai-key", RAG_CORE_API_KEY="rag-key")
    @patch("product_api.views.AiBackendClient.create_assistant")
    @patch("product_api.views.RagCoreClient.create_knowledge_base")
    def test_assistant_provisioning_uses_external_contracts(self, mock_kb, mock_ai):
        mock_kb.return_value = {"id": 982, "name": "Support"}
        remote_id = uuid.uuid4()
        mock_ai.return_value = {"id": str(remote_id)}
        response = self.client.post("/api/v1/assistants/", {
            "name": "Support",
            "description": "Help customers.",
            "instructions": "Be precise.",
            "language": "English",
            "tone": "Professional",
            "retrieval_top_k": 4,
        }, format="json")
        self.assertEqual(response.status_code, 201, response.data)
        assistant = Assistant.objects.get(pk=response.data["id"])
        self.assertEqual(assistant.remote_knowledge_base_id, 982)
        self.assertEqual(assistant.remote_assistant_id, remote_id)
        mock_ai.assert_called_once()
        self.assertEqual(mock_ai.call_args.kwargs["knowledge_base_id"], 982)
        self.assertIn("untrusted evidence", mock_ai.call_args.kwargs["instructions"])

    def test_manual_text_is_queued_for_worker_and_reports_confirmed_indexing(self):
        response = self.client.post(
            f"/api/v1/assistants/{self.assistant.pk}/sources/",
            {"kind": "text", "title": "Product notes", "content": "The product is available in three plans."},
            format="json",
        )
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.data["status"], "pending")
        with patch.object(RagCoreClient, "upload", return_value={"id": 72, "status": "completed"}):
            call_command("runworker", once=True)
        source = Source.objects.get(pk=response.data["id"])
        self.assertEqual(source.status, Source.Status.INDEXED)
        self.assertEqual(source.remote_document_id, 72)

    def test_failed_ingestion_retry_reuses_saved_extraction(self):
        source = Source.objects.create(
            assistant=self.assistant,
            kind=Source.Kind.WEBSITE,
            title="Page",
            url="https://public.example/page",
        )
        with patch(
            "product_api.management.commands.runworker.extract",
            return_value={
                "markdown": "Persisted page content",
                "title": "Page title",
                "final_url": source.url,
            },
        ) as extraction, patch.object(
            RagCoreClient,
            "upload",
            side_effect=[IntegrationError("Core unavailable"), {"id": 91, "status": "completed"}],
        ):
            call_command("runworker", once=True)
            source.refresh_from_db()
            self.assertEqual(source.status, Source.Status.FAILED)
            self.assertEqual(source.content, "Persisted page content")
            retry = self.client.post(
                f"/api/v1/assistants/{self.assistant.pk}/sources/{source.pk}/retry/",
                format="json",
            )
            self.assertEqual(retry.status_code, 202)
            call_command("runworker", once=True)
        source.refresh_from_db()
        self.assertEqual(source.status, Source.Status.INDEXED)
        self.assertEqual(source.remote_document_id, 91)
        extraction.assert_called_once()

    @override_settings(CRAWLER_RESPECT_ROBOTS=False, CRAWLER_MAX_DEPTH=1, CRAWLER_MAX_PAGES=10)
    @patch("product_api.crawler.time.sleep")
    @patch("product_api.crawler._request")
    @patch("product_api.crawler.socket.getaddrinfo")
    def test_manual_crawl_discovery_waits_for_page_selection(self, dns, fetch, _sleep):
        dns.return_value = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 0))]
        base = "https://docs.example.test/"

        def get_page(url):
            if url.endswith("/sitemap.xml"):
                return url, "application/xml", b"<urlset><url><loc>https://docs.example.test/from-map</loc></url></urlset>"
            if url == base:
                return url, "text/html", b"<html><title>Home</title><a href='/guide'>Guide</a><a href='https://elsewhere.example/x'>Outside</a></html>"
            return url, "text/html", b"<html><title>Guide</title><main>Useful information.</main></html>"

        fetch.side_effect = get_page
        create = self.client.post(
            f"/api/v1/assistants/{self.assistant.pk}/crawls/",
            {"url": base, "mode": "manual"},
            format="json",
        )
        self.assertEqual(create.status_code, 202, create.data)
        call_command("runworker", once=True)
        job = CrawlJob.objects.get(pk=create.data["id"])
        self.assertEqual(job.status, CrawlJob.Status.DISCOVERED)
        self.assertGreaterEqual(len(job.discovered_pages), 2)
        self.assertFalse(Source.objects.filter(assistant=self.assistant).exists())
        self.assertTrue(all(page["selected"] is False for page in job.discovered_pages))
        allowed = [job.discovered_pages[0]["url"]]
        selected = self.client.post(
            f"/api/v1/assistants/{self.assistant.pk}/crawls/{job.pk}/process/",
            {"selected_urls": allowed},
            format="json",
        )
        self.assertEqual(selected.status_code, 202, selected.data)

    @override_settings(CRAWLER_RESPECT_ROBOTS=False)
    @patch("product_api.management.commands.runworker.extract")
    @patch.object(RagCoreClient, "upload", return_value={"id": 93, "status": "completed"})
    @patch("product_api.management.commands.runworker.discover")
    @patch("product_api.crawler.socket.getaddrinfo")
    def test_automatic_crawl_processes_eligible_discovered_pages(self, dns, discover_pages, _upload, extraction):
        dns.return_value = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 0))]
        discover_pages.return_value = [{
            "url": "https://public.example/guide",
            "title": "Guide",
            "depth": 1,
            "discovery_source": "link",
            "selected": False,
        }]
        extraction.return_value = {
            "url": "https://public.example/guide",
            "final_url": "https://public.example/guide",
            "title": "Guide",
            "markdown": "Helpful content",
            "extractor": "local",
        }
        response = self.client.post(
            f"/api/v1/assistants/{self.assistant.pk}/crawls/",
            {"url": "https://public.example", "mode": "automatic"},
            format="json",
        )
        self.assertEqual(response.status_code, 202)
        call_command("runworker", once=True)
        job = CrawlJob.objects.get(pk=response.data["id"])
        self.assertEqual(job.status, CrawlJob.Status.COMPLETED)
        self.assertTrue(job.discovered_pages[0]["selected"])
        self.assertEqual(job.discovered_pages[0]["status"], Source.Status.INDEXED)
        self.assertEqual(Source.objects.filter(assistant=self.assistant).count(), 1)

    def test_widget_uses_shared_conversation_service_and_persists_turns(self):
        with patch.object(AiBackendClient, "create_conversation", return_value=str(uuid.uuid4())), patch.object(
            AiBackendClient, "send_message", return_value={"answer": "Grounded answer.", "sources": [], "usage": {}}
        ):
            init = self.client.post("/api/v1/widget/init/", {"assistant_id": str(self.assistant.public_id)}, format="json")
            self.assertEqual(init.status_code, 201)
            response = self.client.post("/api/v1/widget/messages/", {
                "assistant_id": str(self.assistant.public_id),
                "conversation_id": init.data["conversation_id"],
                "question": "How does it work?",
            }, format="json")
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["answer"], "Grounded answer.")
        self.assertEqual(Message.objects.filter(conversation_id=init.data["conversation_id"]).count(), 2)

    @override_settings(WIDGET_ALLOWED_ORIGINS=["https://trusted.example"])
    def test_widget_origin_restriction_and_inactive_assistant(self):
        response = self.client.post(
            "/api/v1/widget/init/",
            {"assistant_id": str(self.assistant.public_id)},
            format="json",
            HTTP_ORIGIN="https://untrusted.example",
        )
        self.assertEqual(response.status_code, 403)
        self.assistant.is_active = False
        self.assistant.save(update_fields=["is_active"])
        response = self.client.post("/api/v1/widget/init/", {"assistant_id": str(self.assistant.public_id)}, format="json")
        self.assertEqual(response.status_code, 404)

    @patch("product_api.views.telegram_request")
    def test_telegram_token_is_encrypted_and_never_returned(self, telegram_call):
        telegram_call.return_value = {"username": "example_bot"}
        response = self.client.post(
            f"/api/v1/assistants/{self.assistant.pk}/telegram/",
            {"bot_token": "123456:secret-token"},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)
        connection = ChannelConnection.objects.get(assistant=self.assistant)
        self.assertNotIn("secret-token", connection.encrypted_bot_token)
        self.assertNotIn("secret-token", str(response.data))
        self.assertEqual(connection.bot_username, "example_bot")

    @patch("product_api.views.telegram_request")
    @patch("product_api.views._dispatch_message")
    def test_telegram_webhook_secret_and_duplicate_update_handling(self, dispatch, telegram_call):
        raw_secret = "private-webhook-secret"
        connection = ChannelConnection.objects.create(
            assistant=self.assistant,
            encrypted_bot_token=encrypt_token("123456:secret-token"),
            webhook_secret_hash=hashlib.sha256(raw_secret.encode()).hexdigest(),
            bot_username="example_bot",
        )
        dispatch.return_value = Response({"answer": "Reply"})
        endpoint = f"/api/v1/webhooks/telegram/{self.assistant.pk}/"
        body = {"update_id": 381, "message": {"text": "Hello", "chat": {"id": 99}}}
        rejected = APIClient().post(endpoint, body, format="json", HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN="wrong")
        self.assertEqual(rejected.status_code, 403)
        first = APIClient().post(
            endpoint, body, format="json",
            HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN=raw_secret,
        )
        second = APIClient().post(
            endpoint, body, format="json",
            HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN=raw_secret,
        )
        self.assertEqual(first.status_code, 200, first.data)
        self.assertEqual(second.data, {"ok": True, "duplicate": True})
        self.assertEqual(ChannelEvent.objects.filter(connection=connection, update_id=381).count(), 1)
        dispatch.assert_called_once()
        self.assertEqual(telegram_call.call_count, 1)


class IntegrationContractTests(TestCase):
    @override_settings(AI_BACKEND_BASE_URL="http://ai:8000", AI_BACKEND_API_KEY="aib_test", AI_TIMEOUT_SECONDS=9, AI_DEFAULT_MODEL="model-x")
    @patch("product_api.integrations.httpx.request")
    def test_ai_assistant_payload_and_auth_match_backend_api(self, request):
        request.return_value = httpx.Response(201, json={"id": str(uuid.uuid4())})
        result = AiBackendClient().create_assistant(
            name="Helper",
            description="",
            instructions="Use evidence.",
            knowledge_base_id=23,
            top_k=4,
            threshold=0.2,
        )
        self.assertEqual(result["id"], request.return_value.json()["id"])
        kwargs = request.call_args.kwargs
        self.assertEqual(kwargs["headers"]["Authorization"], "Api-Key aib_test")
        self.assertEqual(kwargs["json"]["core_knowledge_base_id"], 23)
        self.assertEqual(kwargs["json"]["model"], "model-x")

    @override_settings(RAG_CORE_BASE_URL="http://rag:8000", RAG_CORE_API_KEY="rag_test", RAG_TIMEOUT_SECONDS=11)
    @patch("product_api.integrations.httpx.post")
    def test_rag_upload_requires_completed_state(self, post):
        post.return_value = httpx.Response(201, json={"id": 9, "status": "completed"})
        result = RagCoreClient().upload(23, "notes.txt", b"hello", "text/plain")
        self.assertEqual(result["id"], 9)
        kwargs = post.call_args.kwargs
        self.assertEqual(kwargs["headers"]["Authorization"], "Api-Key rag_test")
        self.assertEqual(kwargs["data"], {"knowledge_base_id": "23"})

    @override_settings(CRAWLER_EXTRACTOR="jina", CRAWLER_FALLBACK="local")
    @patch("product_api.extractors.local_extract", return_value={"url": "https://public.example", "markdown": "content"})
    @patch("product_api.extractors._jina", side_effect=ExtractionError("temporary", retryable=True))
    def test_only_transient_extractor_failure_uses_configured_fallback(self, primary, fallback):
        result = extract("https://public.example")
        self.assertEqual(result["markdown"], "content")
        fallback.assert_called_once()

    @override_settings(CRAWLER_EXTRACTOR="jina", CRAWLER_FALLBACK="local")
    @patch("product_api.extractors.local_extract")
    @patch("product_api.extractors._jina", side_effect=ExtractionError("bad key", retryable=False))
    def test_invalid_extractor_credential_does_not_trigger_fallback(self, _primary, fallback):
        with self.assertRaises(ExtractionError):
            extract("https://public.example")
        fallback.assert_not_called()


class CrawlerSafetyTests(TestCase):
    def test_private_and_local_destinations_are_rejected(self):
        for address in ("http://127.0.0.1/admin", "http://169.254.169.254/latest/meta-data", "file:///etc/passwd"):
            with self.subTest(address=address), self.assertRaises(Exception):
                crawler.validate_public_url(address)

    @patch("product_api.crawler.socket.getaddrinfo")
    def test_every_dns_answer_must_be_public(self, dns):
        dns.return_value = [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 0)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.1.2.3", 0)),
        ]
        with self.assertRaises(Exception):
            crawler.validate_public_url("https://rebinding.example/")

    def test_local_extractor_removes_script_and_navigation_text(self):
        html = b"<html><title>Guide</title><nav>Menu</nav><main><h1>Useful</h1><p>Answer text</p><script>secret()</script></main></html>"
        with patch("product_api.crawler._request", return_value=("https://public.example/", "text/html", html)):
            result = crawler.local_extract("https://public.example/")
        self.assertIn("Answer text", result["markdown"])
        self.assertNotIn("secret", result["markdown"])
        self.assertNotIn("Menu", result["markdown"])

    @override_settings(CRAWLER_TIMEOUT_SECONDS=5, CRAWLER_MAX_CONTENT_BYTES=1024)
    @patch("product_api.crawler.http.client.HTTPConnection")
    @patch("product_api.crawler.socket.create_connection")
    @patch("product_api.crawler.socket.getaddrinfo")
    def test_http_request_connects_to_the_validated_ip_address(self, dns, connect, connection_class):
        dns.return_value = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 0))]
        connect.return_value = object()
        response = SimpleNamespace(
            status=200,
            getheaders=lambda: [("Content-Type", "text/html")],
            read=lambda _limit: b"<html>safe</html>",
        )
        connection = connection_class.return_value
        connection.getresponse.return_value = response
        final_url, content_type, body = crawler._request("http://public-pin.example/")
        self.assertEqual(final_url, "http://public-pin.example/")
        self.assertEqual(content_type, "text/html")
        self.assertEqual(body, b"<html>safe</html>")
        connect.assert_called_once_with(("8.8.8.8", 80), timeout=5)

    @patch("product_api.crawler.http.client.HTTPConnection")
    @patch("product_api.crawler.socket.create_connection")
    @patch("product_api.crawler.socket.getaddrinfo")
    def test_redirect_to_private_address_is_rejected_before_connect(self, dns, connect, connection_class):
        dns.return_value = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 0))]
        connect.return_value = object()
        connection_class.return_value.getresponse.return_value = SimpleNamespace(
            status=302,
            getheaders=lambda: [("Location", "http://127.0.0.1/admin")],
        )
        with self.assertRaises(Exception):
            crawler._request("http://public-redirect.example/")
        connect.assert_called_once()
