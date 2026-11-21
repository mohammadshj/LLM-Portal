"""Bounded GET for administrator-configured discovery origins."""

import asyncio
import ipaddress
import json
import os
import socket
import ssl

import httpx
from asgiref.sync import async_to_sync
from django.conf import settings
from django.core.exceptions import ValidationError

from .validators import validate_connection_url, validate_key_env

ERRORS = {
    "auth": "مجوز یا کلید اتصال پذیرفته نشد.",
    "credential": "ارجاع کلید اتصال یا مقدار آن در محیط سرور معتبر نیست.",
    "endpoint": "سرویس مسیر دریافت فهرست مدل‌ها را پشتیبانی نمی‌کند.",
    "rate_limit": "سقف درخواست سرویس رسیده است. بعداً تلاش کنید.",
    "timeout": "مهلت دریافت فهرست پایان یافت.",
    "network": "برقراری اتصال امن با سرویس ممکن نشد.",
    "destination": "نشانی مقصد با سیاست شبکهٔ Discovery سازگار نیست.",
    "redirect": "سرویس درخواست انتقال به نشانی دیگری داد.",
    "pagination": "Provider فهرست چندصفحه‌ای برگرداند. قرارداد صفحه‌بندی این اتصال پشتیبانی نمی‌شود.",
    "response": "ساختار یا اندازهٔ فهرست دریافتی معتبر نیست.",
    "http": "سرویس در دریافت فهرست خطا برگرداند.",
    "internal": "همگام‌سازی به دلیل خطای داخلی کامل نشد.",
    "busy": "همگام‌سازی دیگری برای این اتصال در حال اجراست.",
    "changed": "تنظیمات اتصال در حین همگام‌سازی تغییر کرد. دوباره تلاش کنید.",
    "disabled": "اتصال غیرفعال است.",
}


class DiscoveryError(Exception):
    def __init__(self, code, status=None):
        self.code, self.status = code, status
        super().__init__(ERRORS[code])


LOCAL_NETS = tuple(
    ipaddress.ip_network(n)
    for n in (
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.0.0/16",
        "127.0.0.0/8",
        "::1/128",
        "fc00::/7",
    )
)


def allowed_ip(address, local):
    ip = ipaddress.ip_address(address)
    if ip.version == 6 and (
        ip.is_site_local
        or ip.ipv4_mapped
        or ip.sixtofour
        or ip.teredo
        or ip in ipaddress.ip_network("64:ff9b::/96")
    ):
        return False
    if (
        str(ip) in ("168.63.129.16", "fd00:ec2::254", "fd20:ce::254")
        or ip.is_multicast
        or ip.is_link_local
        or ip.is_unspecified
    ):
        return False
    if any(ip in net for net in LOCAL_NETS):
        return local
    return ip.is_global and not ip.is_reserved


async def _read(address, authorization, byte_limit, params):
    try:
        validate_connection_url(address)
        url = httpx.URL(address)
        origin = str(url.copy_with(path="/")).rstrip("/")
        local = origin in settings.DISCOVERY_LOCAL_ORIGINS
        if url.scheme != "https" and not local:
            raise DiscoveryError("destination")
        records = await asyncio.get_running_loop().getaddrinfo(
            url.host,
            url.port or (443 if url.scheme == "https" else 80),
            type=socket.SOCK_STREAM,
        )
        ips = [record[4][0] for record in records]
        if not ips or not all(allowed_ip(ip, local) for ip in ips):
            raise DiscoveryError("destination")
        if url.scheme == "http" and any(
            ipaddress.ip_address(ip).is_global for ip in ips
        ):
            raise DiscoveryError("destination")
        headers = {
            "Host": url.netloc.decode(),
            "Accept": "application/json",
            "Accept-Encoding": "identity",
        }
        if authorization:
            headers["Authorization"] = "Bearer " + authorization
        # Connect to the exact vetted address, retaining the original TLS name and Host.
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(10, connect=5),
            verify=ssl.create_default_context(),
            trust_env=False,
            follow_redirects=False,
        ) as client:
            async with client.stream(
                "GET",
                url.copy_with(host=ips[0]),
                params=params,
                headers=headers,
                extensions={"sni_hostname": url.raw_host.decode()},
            ) as response:
                status = response.status_code
                if status != 200:
                    code = {
                        401: "auth",
                        403: "auth",
                        404: "endpoint",
                        405: "endpoint",
                        429: "rate_limit",
                    }.get(status, "redirect" if 300 <= status < 400 else "http")
                    raise DiscoveryError(code, status)
                if (
                    response.headers.get("content-encoding", "identity").lower()
                    != "identity"
                ):
                    raise DiscoveryError("response")
                body = bytearray()
                async for chunk in response.aiter_raw():
                    if len(body) + len(chunk) > byte_limit:
                        raise DiscoveryError("response")
                    body.extend(chunk)
                return json.loads(body)
    except (ValidationError, httpx.InvalidURL):
        raise DiscoveryError("destination") from None
    except (ValueError, UnicodeError, RecursionError):
        raise DiscoveryError("response") from None
    except (httpx.TimeoutException, TimeoutError):
        raise DiscoveryError("timeout") from None
    except (httpx.HTTPError, OSError):
        raise DiscoveryError("network") from None


async def _bounded(url, key, limit, params=None):
    try:
        async with asyncio.timeout(25):
            return await _read(url, key, limit, params)
    except TimeoutError:
        raise DiscoveryError("timeout") from None


read_json = async_to_sync(_bounded)


def credential(connection):
    if not connection.api_key_env:
        return ""
    try:
        validate_key_env(connection.api_key_env)
    except ValidationError:
        raise DiscoveryError("credential") from None
    key = os.environ.get(connection.api_key_env, "").strip()
    if not key or not key.isascii() or not key.isprintable():
        raise DiscoveryError("credential")
    return key
