"""Authenticated endpoints for the physical spots.

A spot authenticates with the bearer token issued to it in the admin
workspace. Only a keyed hash of the token is stored, requests are rate
limited, and the manifest lists nothing but ads that are fully approved and
within their limits for that one spot.
"""

from django.core.cache import cache
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from ads.services.runtime_service import get_eligible_placements_for_asset

from .models import SpotDevice

RATE_LIMIT = 60  # requests per minute per client address
FAILURE_LIMIT = 10  # failed logins per minute per client address


def _client_ip(request):
    return request.META.get("REMOTE_ADDR", "")


def _bump(key, window=60):
    cache.add(key, 0, window)
    try:
        return cache.incr(key)
    except ValueError:
        cache.set(key, 1, window)
        return 1


def _authenticate(request):
    ip = _client_ip(request)
    if _bump(f"dev-rate:{ip}") > RATE_LIMIT:
        return None, JsonResponse({"error": "rate_limited"}, status=429)
    header = request.META.get("HTTP_AUTHORIZATION", "")
    token = header[7:].strip() if header.lower().startswith("bearer ") else ""
    device = SpotDevice.authenticate(token) if token else None
    if device is None or device.asset.status != "ACTIVE":
        if _bump(f"dev-fail:{ip}") > FAILURE_LIMIT:
            return None, JsonResponse({"error": "rate_limited"}, status=429)
        return None, JsonResponse({"error": "unauthorized"}, status=401)
    SpotDevice.objects.filter(pk=device.pk).update(last_seen_at=timezone.now(), last_seen_ip=ip or None)
    return device, None


@csrf_exempt
@never_cache
@require_http_methods(["GET", "POST"])
def ping(request):
    device, error = _authenticate(request)
    if error:
        return error
    return JsonResponse({"ok": True, "spot": device.asset.code, "server_time": timezone.now().isoformat()})


@csrf_exempt
@never_cache
@require_http_methods(["GET"])
def manifest(request):
    device, error = _authenticate(request)
    if error:
        return error
    ads = []
    for placement in get_eligible_placements_for_asset(device.asset):
        ad = placement.ad
        ads.append(
            {
                "ad_id": ad.pk,
                "type": ad.ad_type,
                "title": ad.title,
                "media_url": request.build_absolute_uri(ad.media_file.url) if ad.media_file else None,
                "seconds": ad.duration_seconds,
            }
        )
    return JsonResponse({"spot": device.asset.code, "ads": ads})
