import logging
import mimetypes
import re
import time
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import close_old_connections
from django.utils import timezone
from datetime import timedelta

from product_api.crawler import CrawlError, discover
from product_api.extractors import ExtractionError, extract
from product_api.integrations import IntegrationError, RagCoreClient
from product_api.models import CrawlJob, Source

logger = logging.getLogger(__name__)


def _sync_crawl_page_status(source):
    jobs = CrawlJob.objects.filter(assistant=source.assistant)
    for job in jobs:
        changed = False
        for page in job.discovered_pages:
            if page.get("url") == source.url and page.get("selected"):
                page["status"] = source.status
                page["error"] = source.error_message
                changed = True
        if not changed:
            continue
        if job.status == CrawlJob.Status.FAILED:
            selected = [page for page in job.discovered_pages if page.get("selected")]
            if selected and all(page.get("status") == Source.Status.INDEXED for page in selected):
                job.status = CrawlJob.Status.COMPLETED
                job.error_message = ""
        job.save(update_fields=["discovered_pages", "status", "error_message", "updated_at"])


def _ingest_source(source):
    source.status = Source.Status.PROCESSING
    source.error_message = ""
    source.save(update_fields=["status", "error_message"])
    try:
        if source.kind == Source.Kind.WEBSITE and not source.content:
            result = extract(source.url)
            source.content = result["markdown"]
            source.title = result["title"] or source.title
            source.url = result["final_url"] or source.url
            source.save(update_fields=["content", "title", "url"])
        if source.file_path:
            path = Path(source.file_path)
            content = path.read_bytes()
            filename = path.name
            content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        else:
            content = source.content.encode("utf-8")
            safe_title = re.sub(r"[^A-Za-z0-9._-]+", "-", source.title).strip(".-")[:160] or "source"
            filename = f"{safe_title}.md" if source.kind == Source.Kind.WEBSITE else f"{safe_title}.txt"
            content_type = "text/markdown" if filename.endswith(".md") else "text/plain"
        if not content:
            raise ValueError("The source is empty.")
        remote = RagCoreClient().upload(
            source.assistant.remote_knowledge_base_id,
            filename,
            content,
            content_type,
        )
        source.remote_document_id = remote["id"]
        source.status = Source.Status.INDEXED
        source.save(update_fields=["remote_document_id", "status"])
        _sync_crawl_page_status(source)
    except (IntegrationError, ExtractionError, CrawlError, OSError, ValueError) as exc:
        source.status = Source.Status.FAILED
        source.error_message = str(exc)[:500]
        source.save(update_fields=["status", "error_message"])
        _sync_crawl_page_status(source)
        logger.warning("Source processing failed; source_id=%s error=%s", source.pk, exc)


def _run_job(job):
    if job.status == CrawlJob.Status.PENDING:
        job.status = CrawlJob.Status.DISCOVERING
        job.save(update_fields=["status", "updated_at"])
        try:
            pages = discover(job.start_url)
        except Exception as exc:
            logger.exception("Crawl discovery failed; job_id=%s", job.pk)
            job.status = CrawlJob.Status.FAILED
            job.error_message = str(exc)[:500]
            job.save(update_fields=["status", "error_message", "updated_at"])
            return
        if CrawlJob.objects.filter(pk=job.pk, status=CrawlJob.Status.CANCELLED).exists():
            return
        if not pages:
            job.status = CrawlJob.Status.FAILED
            job.error_message = "No eligible pages were discovered. Check the URL, site access, and robots rules."
            job.save(update_fields=["status", "error_message", "updated_at"])
            return
        job.discovered_pages = pages
        if job.mode == CrawlJob.Mode.AUTOMATIC:
            for page in job.discovered_pages:
                page["selected"] = True
            job.status = CrawlJob.Status.PROCESSING
        else:
            job.status = CrawlJob.Status.DISCOVERED
        job.save(update_fields=["discovered_pages", "status", "updated_at"])
    if job.status != CrawlJob.Status.PROCESSING:
        return

    pages = job.discovered_pages
    for page in pages:
        if not page.get("selected") or page.get("status") == Source.Status.INDEXED:
            continue
        if CrawlJob.objects.filter(pk=job.pk, status=CrawlJob.Status.CANCELLED).exists():
            return
        source, _ = Source.objects.get_or_create(
            assistant=job.assistant,
            url=page["url"],
            defaults={
                "kind": Source.Kind.WEBSITE,
                "title": page.get("title") or page["url"],
                "status": Source.Status.PENDING,
            },
        )
        if source.status == Source.Status.INDEXED:
            page["status"] = Source.Status.INDEXED
            page["error"] = ""
            continue
        _ingest_source(source)
        page["status"] = source.status
        page["error"] = source.error_message
        job.discovered_pages = pages
        job.save(update_fields=["discovered_pages", "updated_at"])
    failed_pages = [page for page in pages if page.get("selected") and page.get("status") == Source.Status.FAILED]
    job.status = CrawlJob.Status.FAILED if failed_pages else CrawlJob.Status.COMPLETED
    job.error_message = "One or more selected pages failed. Retry failed sources from the source list." if failed_pages else ""
    job.save(update_fields=["status", "error_message", "updated_at"])


class Command(BaseCommand):
    help = "Run the product's database-backed ingestion and crawl worker."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Process one queue pass and exit.")
        parser.add_argument("--poll-seconds", type=float, default=2.0)

    def handle(self, *args, **options):
        # Recover work abandoned by a process crash after a bounded lease.
        cutoff = timezone.now() - timedelta(minutes=15)
        Source.objects.filter(status=Source.Status.PROCESSING, updated_at__lt=cutoff).update(status=Source.Status.PENDING)
        while True:
            close_old_connections()
            job = CrawlJob.objects.filter(
                status__in=[CrawlJob.Status.PENDING, CrawlJob.Status.PROCESSING]
            ).select_related("assistant").order_by("created_at").first()
            if job:
                _run_job(job)
            else:
                source = Source.objects.filter(status=Source.Status.PENDING).select_related("assistant").order_by("created_at").first()
                if source:
                    _ingest_source(source)
            if options["once"]:
                break
            time.sleep(max(0.2, options["poll_seconds"]))
