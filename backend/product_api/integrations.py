import logging
from io import BytesIO

import httpx
from django.conf import settings
from rest_framework.exceptions import APIException

logger = logging.getLogger(__name__)


class IntegrationError(APIException):
    status_code = 502
    default_detail = "An upstream service request failed."
    default_code = "upstream_error"


class IntegrationNotConfigured(IntegrationError):
    status_code = 503
    default_detail = "The required upstream integration is not configured."
    default_code = "integration_not_configured"


class ServiceClient:
    def __init__(self, base_url, api_key, timeout, auth_scheme="Api-Key"):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.auth_scheme = auth_scheme

    def request(self, method, path, allow_not_found=False, **kwargs):
        if not self.api_key:
            raise IntegrationNotConfigured()
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"{self.auth_scheme} {self.api_key}"
        try:
            response = httpx.request(
                method,
                f"{self.base_url}{path}",
                headers=headers,
                timeout=self.timeout,
                follow_redirects=False,
                **kwargs,
            )
        except httpx.TimeoutException as exc:
            logger.warning("Upstream request timed out; service=%s", self.base_url)
            raise IntegrationError("An upstream service timed out.") from exc
        except httpx.HTTPError as exc:
            logger.warning("Upstream request failed; service=%s", self.base_url)
            raise IntegrationError("An upstream service could not be reached.") from exc
        if response.is_error:
            if response.status_code == 404 and allow_not_found:
                return None
            logger.warning(
                "Upstream service returned an error; service=%s status=%s",
                self.base_url,
                response.status_code,
            )
            if response.status_code in (401, 403):
                raise IntegrationError("An upstream service rejected its configured credential.")
            if response.status_code == 404:
                raise IntegrationError("An upstream resource was not found.")
            raise IntegrationError(f"An upstream service returned HTTP {response.status_code}.")
        if response.status_code == 204 or not response.content:
            return None
        try:
            return response.json()
        except ValueError as exc:
            raise IntegrationError("An upstream service returned an invalid response.") from exc


class RagCoreClient:
    def __init__(self):
        self.client = ServiceClient(
            settings.RAG_CORE_BASE_URL,
            settings.RAG_CORE_API_KEY,
            settings.RAG_TIMEOUT_SECONDS,
        )

    def create_knowledge_base(self, name, description=""):
        data = self.client.request(
            "POST",
            "/api/v1/knowledge-bases/",
            json={"name": name, "description": description},
        )
        if not isinstance(data, dict) or not isinstance(data.get("id"), int):
            raise IntegrationError("RAG Core returned an invalid knowledge-base response.")
        return data

    def delete_knowledge_base(self, knowledge_base_id):
        self.client.request("DELETE", f"/api/v1/knowledge-bases/{knowledge_base_id}/", allow_not_found=True)

    def upload(self, knowledge_base_id, filename, content, mime_type="text/markdown"):
        if not settings.RAG_CORE_API_KEY:
            raise IntegrationNotConfigured()
        try:
            response = httpx.post(
                f"{settings.RAG_CORE_BASE_URL}/api/v1/documents/upload/",
                headers={"Authorization": f"Api-Key {settings.RAG_CORE_API_KEY}"},
                data={"knowledge_base_id": str(knowledge_base_id)},
                files={"file": (filename, BytesIO(content), mime_type)},
                timeout=settings.RAG_TIMEOUT_SECONDS,
                follow_redirects=False,
            )
        except httpx.TimeoutException as exc:
            raise IntegrationError("RAG Core document ingestion timed out.") from exc
        except httpx.HTTPError as exc:
            raise IntegrationError("RAG Core could not be reached for document ingestion.") from exc
        if response.is_error:
            logger.warning("RAG Core upload failed; status=%s", response.status_code)
            raise IntegrationError(f"RAG Core returned HTTP {response.status_code} while indexing.")
        try:
            payload = response.json()
        except ValueError as exc:
            raise IntegrationError("RAG Core returned an invalid upload response.") from exc
        if (
            not isinstance(payload, dict)
            or not isinstance(payload.get("id"), int)
            or payload.get("status") != "completed"
        ):
            raise IntegrationError("RAG Core did not confirm that the document was indexed.")
        return payload

    def delete_document(self, document_id):
        self.client.request("DELETE", f"/api/v1/documents/{document_id}/", allow_not_found=True)


class AiBackendClient:
    def __init__(self):
        self.client = ServiceClient(
            settings.AI_BACKEND_BASE_URL,
            settings.AI_BACKEND_API_KEY,
            settings.AI_TIMEOUT_SECONDS,
        )

    def create_assistant(self, *, name, description, instructions, knowledge_base_id, top_k, threshold):
        if not settings.AI_DEFAULT_MODEL:
            raise IntegrationNotConfigured("Set AI_DEFAULT_MODEL to a model configured on the AI backend.")
        data = self.client.request(
            "POST",
            "/api/v1/assistants/",
            json={
                "display_name": name,
                "description": description,
                "system_instructions": instructions,
                "model": settings.AI_DEFAULT_MODEL,
                "rag_enabled": True,
                "core_knowledge_base_id": knowledge_base_id,
                "retrieval_top_k": top_k,
                "similarity_threshold": threshold,
            },
        )
        if not isinstance(data, dict) or not data.get("id"):
            raise IntegrationError("AI backend returned an invalid assistant response.")
        return data

    def update_assistant(self, remote_id, *, name, description, instructions, top_k, threshold):
        return self.client.request(
            "PATCH",
            f"/api/v1/assistants/{remote_id}/",
            json={
                "display_name": name,
                "description": description,
                "system_instructions": instructions,
                "retrieval_top_k": top_k,
                "similarity_threshold": threshold,
            },
        )

    def delete_assistant(self, remote_id):
        self.client.request("DELETE", f"/api/v1/assistants/{remote_id}/", allow_not_found=True)

    def create_conversation(self, remote_assistant_id):
        data = self.client.request(
            "POST",
            "/api/v1/conversations/",
            json={"assistant_id": str(remote_assistant_id)},
        )
        if not isinstance(data, dict) or not data.get("id"):
            raise IntegrationError("AI backend returned an invalid conversation response.")
        return data["id"]

    def send_message(self, remote_conversation_id, question):
        data = self.client.request(
            "POST",
            f"/api/v1/conversations/{remote_conversation_id}/messages/",
            json={"question": question},
        )
        if not isinstance(data, dict) or not isinstance(data.get("answer"), str):
            raise IntegrationError("AI backend returned an invalid answer response.")
        return data
