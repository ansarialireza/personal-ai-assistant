import logging

import httpx
from django.conf import settings
from rest_framework.exceptions import ValidationError

from .crawler import CrawlError, local_extract, validate_public_url

logger = logging.getLogger(__name__)


class ExtractionError(Exception):
    def __init__(self, message, retryable=False):
        super().__init__(message)
        self.retryable = retryable


def _bounded_request(method, url, *, headers, json_body=None):
    try:
        with httpx.stream(
            method,
            url,
            headers=headers,
            json=json_body,
            timeout=settings.CRAWLER_TIMEOUT_SECONDS,
            follow_redirects=False,
        ) as response:
            body = bytearray()
            for chunk in response.iter_bytes():
                body.extend(chunk)
                if len(body) > settings.CRAWLER_MAX_CONTENT_BYTES:
                    raise ExtractionError("The extractor response exceeded the configured size limit.")
            return response.status_code, response.headers, bytes(body)
    except httpx.TimeoutException as exc:
        raise ExtractionError("The content extractor timed out.", retryable=True) from exc
    except httpx.HTTPError as exc:
        raise ExtractionError("The content extractor could not be reached.", retryable=True) from exc


def _jina(url):
    if not settings.JINA_API_KEY:
        raise ExtractionError("Jina Reader is not configured.")
    url = validate_public_url(url)
    status_code, headers, body = _bounded_request(
        "GET",
        f"{settings.JINA_API_BASE_URL.rstrip('/')}/{url}",
        headers={"Authorization": f"Bearer {settings.JINA_API_KEY}", "X-Return-Format": "markdown"},
    )
    if status_code in (401, 403):
        raise ExtractionError("Jina Reader rejected its configured credential.")
    if status_code in (408, 429) or status_code >= 500:
        raise ExtractionError(f"Jina Reader returned a temporary error (HTTP {status_code}).", retryable=True)
    if status_code >= 400:
        raise ExtractionError(f"Jina Reader returned HTTP {status_code}.")
    markdown = body.decode("utf-8", errors="replace").strip()
    if not markdown:
        raise ExtractionError("Jina Reader returned no usable content.")
    return {
        "url": url,
        "final_url": validate_public_url(headers.get("X-Final-URL", url)),
        "title": headers.get("X-Title", url)[:255],
        "markdown": markdown,
        "extractor": "jina",
    }


def _firecrawl(url):
    if not settings.FIRECRAWL_API_KEY:
        raise ExtractionError("Firecrawl is not configured.")
    url = validate_public_url(url)
    status_code, _, body = _bounded_request(
        "POST",
        f"{settings.FIRECRAWL_API_BASE_URL.rstrip('/')}/v1/scrape",
        headers={"Authorization": f"Bearer {settings.FIRECRAWL_API_KEY}", "Content-Type": "application/json"},
        json_body={"url": url, "formats": ["markdown"]},
    )
    if status_code in (401, 403):
        raise ExtractionError("Firecrawl rejected its configured credential.")
    if status_code in (408, 429) or status_code >= 500:
        raise ExtractionError(f"Firecrawl returned a temporary error (HTTP {status_code}).", retryable=True)
    if status_code >= 400:
        raise ExtractionError(f"Firecrawl returned HTTP {status_code}.")
    try:
        data = __import__("json").loads(body)["data"]
        metadata = data.get("metadata", {})
        markdown = data.get("markdown", "").strip()
    except (ValueError, KeyError, TypeError) as exc:
        raise ExtractionError("Firecrawl returned an invalid response.") from exc
    if not markdown:
        raise ExtractionError("Firecrawl returned no usable content.")
    final_url = validate_public_url(metadata.get("sourceURL", url))
    return {
        "url": url,
        "final_url": final_url,
        "title": str(metadata.get("title", url))[:255],
        "markdown": markdown[:settings.CRAWLER_MAX_CONTENT_BYTES],
        "extractor": "firecrawl",
    }


def extract(url):
    adapters = {"local": local_extract, "jina": _jina, "firecrawl": _firecrawl}
    primary = settings.CRAWLER_EXTRACTOR
    try:
        return adapters[primary](url)
    except ValidationError as exc:
        raise ExtractionError("The source URL is not allowed for extraction.") from exc
    except (CrawlError, ExtractionError) as primary_error:
        fallback = settings.CRAWLER_FALLBACK
        if not fallback or fallback == primary:
            raise ExtractionError(str(primary_error), getattr(primary_error, "retryable", False)) from primary_error
        if isinstance(primary_error, ExtractionError) and not primary_error.retryable:
            raise ExtractionError(str(primary_error)) from primary_error
        try:
            return adapters[fallback](url)
        except (CrawlError, ExtractionError) as fallback_error:
            logger.warning("Primary and fallback extraction failed; primary=%s fallback=%s", primary, fallback)
            raise ExtractionError(f"Primary and fallback extraction failed: {fallback_error}", getattr(fallback_error, "retryable", False)) from fallback_error
