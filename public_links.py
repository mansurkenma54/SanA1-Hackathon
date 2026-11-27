"""Bounded anonymous checks for referenced public HTTP resources."""

import http.client
import ipaddress
import json
import re
import socket
import ssl
from concurrent.futures import ThreadPoolExecutor, wait
from contextlib import closing
from datetime import datetime, timezone
from time import monotonic
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


HTTP_URL = re.compile(r'https?://[^\s<>{}\[\]|"\x00-\x20]+', re.IGNORECASE)
GITHUB_OWNER = r"[a-zA-Z0-9][a-zA-Z0-9-]{0,38}"
GITHUB_REPO = r"[a-zA-Z0-9_.-]{1,100}"
GITHUB_PATH = re.compile(rf"/({GITHUB_OWNER})/({GITHUB_REPO})/?")
LINK_LIMIT = 8
LINK_TIMEOUT = 5
LINK_WORKERS = ThreadPoolExecutor(max_workers=8)
NONPUBLIC_SUFFIXES = (".localhost", ".local", ".internal", ".test", ".invalid", ".onion")


def web_urls(text):
    for candidate in HTTP_URL.findall(text):
        url = candidate.rstrip(".,;:!?")
        while url.endswith(")") and url.count(")") > url.count("("):
            url = url[:-1]
        try:
            parsed = urlsplit(url)
            if parsed.hostname and parsed.username is None and parsed.password is None:
                yield url
        except ValueError:
            continue


def github_repository(url):
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.netloc.lower() != "github.com" or parts.query or parts.fragment:
        return None
    match = GITHUB_PATH.fullmatch(parts.path)
    return match.groups() if match and match[2] not in {".", ".."} else None


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        return None


def check_public_repository(owner, repository):
    endpoint = f"https://api.github.com/repos/{owner}/{repository}"
    request = Request(endpoint, headers={"Accept": "application/vnd.github+json", "User-Agent": "SanA1"})
    try:
        with build_opener(NoRedirect()).open(request, timeout=5) as response:
            data = json.loads(response.read(65536))
            if (data.get("private") is False
                    and str(data.get("full_name", "")).lower() == f"{owner}/{repository}".lower()):
                return "public"
            return "unconfirmed"
    except HTTPError as error:
        return "unconfirmed" if error.code == 404 else "unavailable"
    except (URLError, TimeoutError, ValueError, UnicodeError, AttributeError):
        return "unavailable"


def public_address(value):
    ip = ipaddress.ip_address(value)
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        elif ip.sixtofour or ip.teredo or ip in ipaddress.ip_network("64:ff9b::/96"):
            return False
    return ip.is_global and not ip.is_multicast and not ip.is_reserved


def check_public_url(url, deadline):
    """Connect to the screened IP directly and authenticate TLS against the original host."""
    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").rstrip(".").encode("idna").decode("ascii").lower()
        port = 443 if parts.scheme == "https" else 80
        if (parts.scheme not in {"http", "https"} or not host or parts.username is not None
                or parts.port not in {None, port} or host == "localhost" or host.endswith(NONPUBLIC_SUFFIXES)
                or ("." not in host and ":" not in host) or "%" in host):
            return "blocked"
        if parts.query:
            return "manual"
        addresses = list(dict.fromkeys(info[4][0] for info in
                                      socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)))
        if not addresses or not all(public_address(ip) for ip in addresses):
            return "blocked"
        remaining = deadline - monotonic()
        if remaining <= 0:
            return "unavailable"
        address = min(addresses, key=lambda ip: ipaddress.ip_address(ip).version)
        with closing(http.client.HTTPConnection(host, port, timeout=remaining)) as connection:
            connection.sock = socket.create_connection((address, port), timeout=remaining)
            if parts.scheme == "https":
                connection.sock = ssl.create_default_context().wrap_socket(connection.sock, server_hostname=host)
            connection.sock.settimeout(max(0.01, deadline - monotonic()))
            connection.request("HEAD", parts.path or "/", headers={"User-Agent": "SanA1", "Connection": "close"})
            with connection.getresponse() as result:
                if 200 <= result.status < 300:
                    return "public"
                if 300 <= result.status < 400:
                    return "redirect"
                return "unconfirmed" if result.status in {401, 403, 404, 405, 410} else "unavailable"
    except (OSError, ValueError, http.client.HTTPException):
        return "unavailable"


def check_audit_links(links, *, include_public_web=False):
    """Check at most eight links. Do not follow redirects or send cookies or credentials."""
    supported = [link["url"] for link in links if link["check"] == "github" or include_public_web][:LINK_LIMIT]
    if not supported:
        return []
    deadline = monotonic() + LINK_TIMEOUT

    def probe(url):
        if monotonic() >= deadline:
            return "unavailable"
        repo = github_repository(url)
        return check_public_repository(*repo) if repo else check_public_url(url, deadline)

    jobs = {LINK_WORKERS.submit(probe, url): url for url in supported}
    done, pending = wait(jobs, timeout=LINK_TIMEOUT)
    result = []
    for job, url in jobs.items():
        status = job.result() if job in done else "unavailable"
        result.append({"url": url, "status": status,
                       "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    for job in pending:
        job.cancel()
    return result
