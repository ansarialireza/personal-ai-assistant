import http.client
import ipaddress
import re
import ssl
import socket
from functools import lru_cache
import time
import xml.etree.ElementTree as ET
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

from bs4 import BeautifulSoup, NavigableString, Tag
from django.conf import settings
from rest_framework.exceptions import ValidationError


class CrawlError(Exception):
    pass


_last_request_at = {}


def validate_public_url(url):
    return _resolve_public_url(url)[0]


def _resolve_public_url(url):
    try:
        parts = urlsplit(url)
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            raise ValueError
        if parts.username or parts.password or parts.port not in (None, 80, 443):
            raise ValueError
        host = parts.hostname.rstrip(".").lower()
        if host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
            raise ValueError
        try:
            literal_address = ipaddress.ip_address(host)
        except ValueError:
            literal_address = None
        if literal_address is not None and not literal_address.is_global:
            raise ValueError
        records = socket.getaddrinfo(host, parts.port or (443 if parts.scheme == "https" else 80), type=socket.SOCK_STREAM)
        if not records:
            raise ValueError
        addresses = []
        for record in records:
            address = ipaddress.ip_address(record[4][0])
            if not address.is_global:
                raise ValueError
            if str(address) not in addresses:
                addresses.append(str(address))
        path = parts.path or "/"
        normalized = urlunsplit((parts.scheme, parts.netloc, path, parts.query, ""))
        return normalized, addresses
    except (ValueError, OSError, socket.gaierror) as exc:
        raise ValidationError({"url": "Only publicly reachable HTTP or HTTPS URLs are allowed."}) from exc


def _request(url):
    current = url
    for _ in range(4):
        current, addresses = _resolve_public_url(current)
        parts = urlsplit(current)
        host = parts.hostname
        port = parts.port or (443 if parts.scheme == "https" else 80)
        target = parts.path or "/"
        if parts.query:
            target += f"?{parts.query}"
        conn_type = http.client.HTTPSConnection if parts.scheme == "https" else http.client.HTTPConnection
        connection = conn_type(host, port, timeout=settings.CRAWLER_TIMEOUT_SECONDS, **(
            {"context": ssl.create_default_context()} if parts.scheme == "https" else {}
        ))
        try:
            if host not in _last_request_at and len(_last_request_at) >= 1024:
                _last_request_at.clear()
            last_request = _last_request_at.get(host)
            if last_request is not None:
                delay = 1.0 - (time.monotonic() - last_request)
                if delay > 0:
                    time.sleep(delay)
            _last_request_at[host] = time.monotonic()
            last_error = None
            for address in addresses:
                try:
                    sock = socket.create_connection((address, port), timeout=settings.CRAWLER_TIMEOUT_SECONDS)
                    if parts.scheme == "https":
                        sock = connection._context.wrap_socket(sock, server_hostname=host)
                    connection.sock = sock
                    break
                except OSError as exc:
                    last_error = exc
                    if "sock" in locals() and sock:
                        sock.close()
            else:
                raise CrawlError("The public website could not be reached.") from last_error
            connection.putrequest("GET", target)
            connection.putheader("Host", parts.netloc)
            connection.putheader("User-Agent", settings.CRAWLER_USER_AGENT)
            connection.putheader("Accept", "text/html,application/xml,text/plain")
            connection.putheader("Accept-Encoding", "identity")
            connection.putheader("Connection", "close")
            connection.endheaders()
            response = connection.getresponse()
            headers = {name.lower(): value for name, value in response.getheaders()}
            if response.status in {301, 302, 303, 307, 308}:
                location = headers.get("location")
                if not location:
                    raise CrawlError("Redirect response did not include a destination.")
                current = validate_public_url(urljoin(current, location))
                continue
            if response.status >= 400:
                raise CrawlError(f"The website returned HTTP {response.status}.")
            body = response.read(settings.CRAWLER_MAX_CONTENT_BYTES + 1)
            if len(body) > settings.CRAWLER_MAX_CONTENT_BYTES:
                raise CrawlError("The page exceeded the configured response size limit.")
            return current, headers.get("content-type", "").lower(), body
        except (socket.timeout, TimeoutError) as exc:
            raise CrawlError("The website request timed out.") from exc
        except (OSError, ssl.SSLError, http.client.HTTPException) as exc:
            raise CrawlError("The website could not be fetched.") from exc
        finally:
            connection.close()
    raise CrawlError("The website exceeded the redirect limit.")


@lru_cache(maxsize=256)
def _robots_parser(robots_url):
    try:
        _, content_type, body = _request(robots_url)
        if len(body) > 256_000 or ("text/" not in content_type and "plain" not in content_type):
            return None
        lines = body.decode("utf-8", errors="replace").splitlines()
        recognized = re.compile(r"^(user-agent|disallow|allow|crawl-delay|sitemap)\s*:", re.IGNORECASE)
        if not any(recognized.match(line.strip()) for line in lines) or not any(
            line.strip().lower().startswith("user-agent:") for line in lines
        ):
            return None
        parser = RobotFileParser()
        parser.set_url(robots_url)
        parser.parse(lines)
        return parser
    except (CrawlError, ValidationError):
        return None


def _robots_allowed(url):
    if not settings.CRAWLER_RESPECT_ROBOTS:
        return True
    parts = urlsplit(url)
    robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
    parser = _robots_parser(robots_url)
    return bool(parser and parser.can_fetch(settings.CRAWLER_USER_AGENT, url))


def _is_html_candidate(url):
    path = urlsplit(url).path.lower()
    return not any(path.endswith(ext) for ext in (
        ".pdf", ".doc", ".docx", ".zip", ".png", ".jpg", ".jpeg", ".gif",
        ".svg", ".mp4", ".mp3", ".xml", ".json", ".css", ".js",
    ))


def discover(start_url):
    normalized = validate_public_url(start_url)
    origin = urlsplit(normalized)
    origin_host = origin.netloc.lower()
    queue = [(normalized, 0, "submitted"), (urljoin(normalized, "/sitemap.xml"), 0, "sitemap")]
    seen = set()
    results = []
    visited = 0
    while queue and len(results) < settings.CRAWLER_MAX_PAGES and visited < settings.CRAWLER_MAX_PAGES:
        url, depth, source = queue.pop(0)
        url = validate_public_url(url)
        if url in seen or not _is_html_candidate(url):
            continue
        seen.add(url)
        if not _robots_allowed(url):
            continue
        try:
            final_url, content_type, body = _request(url)
        except (CrawlError, ValidationError):
            continue
        visited += 1
        if final_url in seen and final_url != url:
            continue
        seen.add(final_url)
        if "xml" in content_type or final_url.endswith(".xml"):
            try:
                root = ET.fromstring(body)
                for loc in root.findall(".//{*}loc"):
                    if loc.text:
                        child_url = validate_public_url(loc.text.strip())
                        if urlsplit(child_url).netloc.lower() == origin_host and child_url not in seen:
                            queue.append((child_url, 0, "sitemap"))
            except (ET.ParseError, ValidationError):
                pass
            continue
        if "html" not in content_type:
            continue
        soup = BeautifulSoup(body, "html.parser")
        title = soup.title.get_text(" ", strip=True)[:255] if soup.title else ""
        results.append({"url": final_url, "title": title, "depth": depth, "discovery_source": source, "selected": False})
        if depth < settings.CRAWLER_MAX_DEPTH:
            for link in soup.select("a[href]"):
                candidate = urljoin(final_url, link.get("href", ""))
                try:
                    candidate = validate_public_url(candidate)
                except ValidationError:
                    continue
                if urlsplit(candidate).netloc.lower() == origin_host and candidate not in seen and _is_html_candidate(candidate):
                    queue.append((candidate, depth + 1, "link"))
    return results


def local_extract(url):
    final_url, content_type, body = _request(url)
    if "html" not in content_type:
        raise CrawlError("Local extraction only supports HTML pages.")
    soup = BeautifulSoup(body, "html.parser")
    title = soup.title.get_text(" ", strip=True)[:255] if soup.title else final_url
    for node in soup(["script", "style", "nav", "footer", "header", "noscript", "svg", "form"]):
        node.decompose()
    article = soup.find("main") or soup.find("article") or soup.body or soup
    def render(node):
        if isinstance(node, NavigableString):
            return str(node).strip()
        if not isinstance(node, Tag):
            return ""
        name = node.name.lower()
        children = "".join(render(child) for child in node.children)
        content = children.strip()
        if name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            return f"\n\n{'#' * int(name[1])} {content}\n\n"
        if name in {"p", "div", "section", "article", "main", "blockquote"}:
            return f"\n\n{content}\n\n"
        if name in {"ul", "ol"}:
            items = [f"- {render(item).strip()}" for item in node.find_all("li", recursive=False)]
            return "\n" + "\n".join(items) + "\n"
        if name == "li":
            return f"{content}\n"
        if name == "br":
            return "\n"
        if name == "a":
            href = node.get("href", "").strip()
            scheme = urlsplit(href).scheme.lower()
            if href and scheme in {"", "http", "https"}:
                return f"[{content}]({urljoin(final_url, href)})"
        return children

    text = render(article)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not text:
        raise CrawlError("No readable page text was found.")
    bounded = text.encode("utf-8")[:settings.CRAWLER_MAX_CONTENT_BYTES].decode("utf-8", errors="ignore").strip()
    return {"url": url, "final_url": final_url, "title": title, "markdown": bounded, "extractor": "local"}
