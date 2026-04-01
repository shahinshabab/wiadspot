# ads/utils.py
from __future__ import annotations

import base64
import hashlib
import logging
import re
from typing import Dict, List, Optional, Tuple
from urllib.parse import parse_qsl

import requests
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.http import (
    HttpRequest,
    HttpResponse,
    HttpResponseBadRequest,
    HttpResponseNotAllowed,
    HttpResponseServerError,
    JsonResponse,
)
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from .models import Asset, AuthGrant

User = get_user_model()
logger = logging.getLogger(__name__)

_MAC_RE = re.compile(r"^([0-9A-F]{2}:){5}[0-9A-F]{2}$")


class Msg91Error(Exception):
    pass


# =========================================================
# MSG91 HELPERS
# =========================================================
def _msg91_headers() -> Dict[str, str]:
    authkey = getattr(settings, "MSG91_AUTHKEY", "").strip()
    if not authkey:
        raise Msg91Error("MSG91_AUTHKEY is missing in settings.")
    return {
        "authkey": authkey,
        "Content-Type": "application/json",
    }


def _msg91_timeout() -> int:
    return int(getattr(settings, "MSG91_TIMEOUT", 15))


def _normalize_indian_msisdn(phone: str) -> str:
    """
    Normalize Indian number into 91XXXXXXXXXX format.
    Accepts:
    - 10 digits
    - +91XXXXXXXXXX
    - 91XXXXXXXXXX
    """
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())

    if len(digits) == 10:
        return f"91{digits}"

    if len(digits) == 12 and digits.startswith("91"):
        return digits

    raise Msg91Error("Invalid Indian phone number format. Use 10 digits or 91XXXXXXXXXX.")


def _parse_json_response(response: requests.Response, action: str):
    try:
        return response.json()
    except ValueError as exc:
        raise Msg91Error(
            f"MSG91 {action} returned invalid JSON: {response.text[:300]}"
        ) from exc


def _extract_error_message(data, default_message: str) -> str:
    if isinstance(data, dict):
        return (
            data.get("message")
            or data.get("error")
            or data.get("msg")
            or data.get("type")
            or default_message
        )
    return default_message


def _request(method: str, url: str, *, json=None, action: str = "request"):
    try:
        response = requests.request(
            method=method,
            url=url,
            json=json,
            headers=_msg91_headers(),
            timeout=_msg91_timeout(),
        )
    except requests.RequestException as exc:
        raise Msg91Error(f"MSG91 {action} request failed: {exc}") from exc

    data = _parse_json_response(response, action)

    if response.status_code >= 400:
        raise Msg91Error(_extract_error_message(data, f"MSG91 {action} failed."))

    if isinstance(data, dict):
        status = str(data.get("type", "")).lower()
        if status in {"error", "failed", "failure"}:
            raise Msg91Error(_extract_error_message(data, f"MSG91 {action} failed."))

    return data


def send_and_get_req_id(msisdn: str) -> str:
    msisdn = _normalize_indian_msisdn(msisdn)

    url = getattr(settings, "MSG91_SEND_OTP_URL", "").strip()
    if not url:
        raise Msg91Error("MSG91_SEND_OTP_URL is missing in settings.")

    payload = {
        "mobile": msisdn,
        "otp_expiry": int(getattr(settings, "MSG91_OTP_EXPIRY", 10)),
    }

    template_id = getattr(settings, "MSG91_TEMPLATE_ID", "").strip()
    if template_id:
        payload["template_id"] = template_id

    data = _request("POST", url, json=payload, action="send OTP")

    req_id = data.get("request_id") or data.get("req_id")
    if not req_id:
        raise Msg91Error(f"MSG91 did not return request_id/req_id. Response: {data}")

    return req_id


def retry_msg91_otp(req_id: str):
    req_id = (req_id or "").strip()
    if not req_id:
        raise Msg91Error("Missing req_id for retry.")

    url_template = getattr(settings, "MSG91_RETRY_OTP_URL", "").strip()
    if not url_template:
        raise Msg91Error("MSG91_RETRY_OTP_URL is missing in settings.")

    url = url_template.format(request_id=req_id)
    return _request("GET", url, action="retry OTP")


def verify_msg91_otp(req_id: str, otp: str):
    req_id = (req_id or "").strip()
    if not req_id:
        raise Msg91Error("Missing req_id for verify.")

    otp = (otp or "").strip()
    if not otp:
        raise Msg91Error("OTP is missing.")
    if not otp.isdigit():
        raise Msg91Error("OTP must contain digits only.")

    url_template = getattr(settings, "MSG91_VERIFY_OTP_URL", "").strip()
    if not url_template:
        raise Msg91Error("MSG91_VERIFY_OTP_URL is missing in settings.")

    url = url_template.format(request_id=req_id, otp=otp)
    return _request("GET", url, action="verify OTP")


# =========================================================
# FAS HELPERS
# =========================================================
def _require_fas_key() -> str:
    key = getattr(settings, "FAS_KEY", "") or ""
    if not key:
        raise Msg91Error("FAS_KEY is not configured in settings.")
    return key


def _pkcs7_unpad(blocksize_bits: int, data: bytes) -> bytes:
    unpadder = padding.PKCS7(blocksize_bits).unpadder()
    return unpadder.update(data) + unpadder.finalize()


def _normalize_b64(s: str) -> str:
    s = (s or "").strip()
    s = s.replace(" ", "+").replace("-", "+").replace("_", "/")
    pad = (-len(s)) % 4
    if pad:
        s += "=" * pad
    return s


def _decrypt_once(ct: bytes, iv: bytes, key: bytes) -> bytes:
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
    decryptor = cipher.decryptor()
    return decryptor.update(ct) + decryptor.finalize()


def _parse_nds_kv(plaintext: str) -> Dict[str, str]:
    text = (
        plaintext.replace("\r\n", ", ")
        .replace("\r", ", ")
        .replace("\n", ", ")
        .replace("&", ", ")
        .replace(" ,", ",")
        .replace(",  ", ", ")
    )

    parts = [p.strip() for p in text.split(",") if p.strip()]
    data: Dict[str, str] = {}

    for part in parts:
        if "=" in part:
            k, v = part.split("=", 1)
            data[k.strip()] = v.strip()

    if not data:
        data = dict(parse_qsl(plaintext, keep_blank_values=True))

    return data


def _looks_b64_bytes(b: bytes) -> bool:
    b64chars = set(b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=\r\n")
    return len(b) % 4 == 0 and all(ch in b64chars for ch in b)


def _compute_rhid(hid: str, key_str: str) -> str:
    h = hashlib.sha256()
    h.update(hid.strip().encode("utf-8"))
    h.update(key_str.strip().encode("utf-8"))
    return h.hexdigest()


def _looks_like_nds(s: str) -> bool:
    keys = (
        "clientip=",
        "clientmac=",
        "gatewayname=",
        "hid=",
        "originurl=",
        "tok=",
        "gatewayaddress=",
    )
    return sum(k in s for k in keys) >= 2


def _decrypt_fas_payload(
    fas_b64: str,
    iv_text: str,
    key_str: str,
) -> Tuple[str, List[str]]:
    dbg: List[str] = []

    try:
        fas_norm = _normalize_b64(fas_b64)
        ct = base64.b64decode(fas_norm)
    except Exception as exc:
        raise Msg91Error(f"Invalid FAS base64 payload: {exc}") from exc

    if _looks_b64_bytes(ct):
        try:
            ct = base64.b64decode(ct)
            dbg.append("double-base64 detected")
        except Exception:
            pass

    iv_candidates: List[Tuple[str, bytes]] = []
    iv_txt = (iv_text or "").strip()

    if len(iv_txt) == 16:
        try:
            iv_candidates.append(("iv ascii16", iv_txt.encode("ascii", "strict")))
        except Exception:
            pass

    if re.fullmatch(r"[0-9a-fA-F]{16}", iv_txt):
        try:
            b8 = bytes.fromhex(iv_txt)
            iv_candidates.append(("iv hex16 doubled", b8 + b8))
            iv_candidates.append(("iv hex16 zero-padded", b8 + b"\x00" * 8))
        except Exception:
            pass

    def ascii_trunc32(s: str) -> bytes:
        kb = s.encode("utf-8", errors="strict")
        return (kb + b"\x00" * 32)[:32]

    key_candidates: List[Tuple[str, bytes]] = [("ascii/trunc32", ascii_trunc32(key_str))]

    if re.fullmatch(r"[0-9a-fA-F]{64}", key_str.strip()):
        try:
            key_candidates.append(("hex64", bytes.fromhex(key_str.strip())))
        except Exception:
            pass

    for iv_label, iv in iv_candidates:
        for key_label, key in key_candidates:
            if len(iv) != 16 or len(key) != 32:
                continue

            try:
                pt_padded = _decrypt_once(ct, iv, key)
            except Exception:
                dbg.append(f"decrypt failed with {iv_label} / {key_label}")
                continue

            try:
                pt = _pkcs7_unpad(128, pt_padded)
                plaintext = pt.decode("utf-8", errors="replace")
                if _looks_like_nds(plaintext):
                    dbg.append(f"success with {iv_label} / {key_label}")
                    return plaintext, dbg
            except Exception:
                pass

            try:
                plaintext = pt_padded.rstrip(b"\x00").decode("utf-8", errors="replace")
                if _looks_like_nds(plaintext):
                    dbg.append(f"success with zero-strip {iv_label} / {key_label}")
                    return plaintext, dbg
            except Exception:
                pass

    raise Msg91Error("Unable to decrypt FAS payload.")


def decode_fas(fas_b64: str, iv_text: Optional[str]) -> Tuple[Dict[str, str], str, str]:
    """
    Returns:
        params_dict, hid, rhid
    """
    if not fas_b64:
        return {}, "", ""

    plaintext, _dbg = _decrypt_fas_payload(
        fas_b64=fas_b64,
        iv_text=iv_text or "",
        key_str=_require_fas_key(),
    )

    params = _parse_nds_kv(plaintext)
    hid = params.get("hid", "") or params.get("client_hid", "")
    rhid = _compute_rhid(hid, _require_fas_key()) if hid else ""

    return params, hid, rhid


# =========================================================
# PHONE MASKING
# =========================================================
def mask_phone(
    phone: str,
    keep_start: Optional[int] = None,
    keep_end: Optional[int] = None,
    mask_char: str = "*",
    preserve_format: bool = True,
) -> str:
    if not isinstance(phone, str) or not phone:
        return ""

    digits = [c for c in phone if c.isdigit()]
    n = len(digits)

    if keep_start is None or keep_end is None:
        if n == 10:
            ks, ke = 2, 3
        elif n <= 4:
            ks, ke = max(1, n - 1), 1
        else:
            ks, ke = 2, 2

        if keep_start is None:
            keep_start = ks
        if keep_end is None:
            keep_end = ke

    keep_start = max(0, min(keep_start, n))
    keep_end = max(0, min(keep_end, n - keep_start))
    middle = max(0, n - keep_start - keep_end)

    masked_digits = (
        digits[:keep_start]
        + [mask_char] * middle
        + (digits[-keep_end:] if keep_end else [])
    )

    if not preserve_format:
        return "".join(masked_digits)

    out = []
    di = 0
    for ch in phone:
        if ch.isdigit():
            out.append(masked_digits[di])
            di += 1
        else:
            out.append(ch)

    if di < len(masked_digits):
        out.append("".join(masked_digits[di:]))

    return "".join(out)


def mask_phone_in(indian_phone: str) -> str:
    return mask_phone(indian_phone, keep_start=2, keep_end=3, preserve_format=True)


# =========================================================
# BASIC REQUEST HELPERS
# =========================================================
def remote_ip(request: HttpRequest) -> str:
    xff = (request.META.get("HTTP_X_FORWARDED_FOR") or "").split(",", 1)[0].strip()
    return xff or (request.META.get("REMOTE_ADDR") or "")


def wants_json(request: HttpRequest) -> bool:
    fmt = (request.GET.get("format") or "").lower()
    accept = (request.headers.get("Accept") or "").lower()
    return fmt == "json" or "application/json" in accept


def safe_bool(v) -> bool:
    return bool(v)


def int_or_default(v, default: int) -> int:
    try:
        iv = int(v)
        return iv if iv >= 0 else int(default)
    except Exception:
        return int(default)


def clampi(v: Optional[int], lo: int = 0, hi: int = 10_000_000) -> int:
    try:
        x = int(v or 0)
        if x < lo:
            x = lo
        if x > hi:
            x = hi
        return x
    except Exception:
        return lo


def strip_token(tok: Optional[str]) -> str:
    return (tok or "").strip().split()[0]


def no_spaces(s: str) -> str:
    return (s or "").strip().replace(" ", "%20")


# =========================================================
# ASSET AUTH DEFAULTS
# =========================================================
def asset_auth_defaults(asset, *, redir: str = "") -> dict:
    """
    Defaults for AuthMon packet.
    """
    session_len = int_or_default(getattr(asset, "default_sessionlength", 60), 60)
    up_rate = int_or_default(getattr(asset, "default_uploadrate", 0), 0)
    down_rate = int_or_default(getattr(asset, "default_downloadrate", 0), 0)
    up_quota = int_or_default(getattr(asset, "default_uploadquota", 0), 0)
    down_quota = int_or_default(getattr(asset, "default_downloadquota", 0), 0)
    redir_clean = (redir or getattr(asset, "default_redirurl", "") or "").strip()

    return {
        "sessionlength": session_len,
        "uploadrate": up_rate,
        "downloadrate": down_rate,
        "uploadquota": up_quota,
        "downloadquota": down_quota,
        "redirurl": redir_clean,
        "custom": "",
    }


# =========================================================
# ASSET RESOLVER
# =========================================================
def resolve_asset_from_request(request, assetid=None, username=None):
    try:
        if assetid not in (None, ""):
            a = Asset.objects.filter(pk=assetid, is_active=True).first()
            if a:
                return a
            a = Asset.objects.filter(name=str(assetid), is_active=True).first()
            if a:
                return a

        if username and assetid:
            owner = User.objects.filter(username=username).first()
            if owner:
                a = (
                    Asset.objects.filter(actual_owner=owner, name=str(assetid), is_active=True).first()
                    or Asset.objects.filter(is_active=True).first()
                )
                if a:
                    return a

        params = request.GET.copy() or request.POST.copy()
        fas_b64 = params.get("fas")
        iv_b64 = params.get("iv")

        if fas_b64:
            try:
                decoded, _hid, _rhid = decode_fas(fas_b64, iv_b64 or None)
                for k, v in decoded.items():
                    params.setdefault(k, v)
            except Exception as exc:
                logger.warning("resolve_asset_from_request: decode failed: %s", str(exc)[:200])

        gateway = (
            params.get("gateway")
            or params.get("gw_address")
            or params.get("gatewayaddress")
            or params.get("gw")
            or ""
        )

        q = Q(is_active=True)
        if gateway:
            q &= Q(ip_address__iexact=gateway)

        return Asset.objects.filter(q).first()

    except Exception:
        logger.exception("resolve_asset_from_request: unexpected error")
        return None


# =========================================================
# AUTHMON HELPERS
# =========================================================
def build_grant_line(g: AuthGrant) -> str:
    rhid = strip_token(getattr(g, "rhid", ""))
    if not rhid:
        return ""

    st = clampi(getattr(g, "sessionlength", 0))
    ur = clampi(getattr(g, "uploadrate", 0))
    dr = clampi(getattr(g, "downloadrate", 0))
    uq = clampi(getattr(g, "uploadquota", 0))
    dq = clampi(getattr(g, "downloadquota", 0))

    parts = []
    if st > 0:
        parts.append(f"sessionlength={st}")
    if ur > 0:
        parts.append(f"uploadrate={ur}")
    if dr > 0:
        parts.append(f"downloadrate={dr}")
    if uq > 0:
        parts.append(f"uploadquota={uq}")
    if dq > 0:
        parts.append(f"downloadquota={dq}")

    ru = (getattr(g, "redirurl", "") or "").strip()
    if ru:
        parts.append(f"redirurl={no_spaces(ru)}")

    cu = (getattr(g, "custom", "") or "").strip()
    if cu:
        parts.append(f"custom={no_spaces(cu)}")

    return "* " + rhid + (" " + " ".join(parts) if parts else "")
@csrf_exempt
def handle_authmon_inline(request: HttpRequest, assetid):
    """
    Handle AuthMon when it arrives at /fas/<assetid> with auth_get=...
    Accepts numeric asset id or asset name.
    """
    try:
        resolved_asset_id = None

        try:
            resolved_asset_id = int(assetid)
        except Exception:
            asset = Asset.objects.filter(
                Q(pk=assetid) | Q(name=str(assetid)),
                is_active=True,
            ).first()
            resolved_asset_id = asset.pk if asset else None

        if not resolved_asset_id:
            logger.warning(
                "handle_authmon_inline: unknown asset",
                extra={"assetid_arg": assetid},
            )
            return HttpResponseBadRequest("Unknown asset")

        return handle_authmon_common(request, resolved_asset_id)

    except Exception:
        logger.exception("handle_authmon_inline: unexpected error")
        return HttpResponseServerError("Server error")

@csrf_exempt
def handle_authmon_common(request: HttpRequest, assetid: int):
    start = timezone.now()

    try:
        if request.method not in ("GET", "POST"):
            return HttpResponseNotAllowed(["GET", "POST"])

        asset = Asset.objects.filter(pk=assetid, is_active=True).first()
        if not asset:
            return HttpResponseBadRequest("Unknown asset")

        data = request.POST or request.GET
        mode = (data.get("auth_get") or "view").lower()
        as_json = wants_json(request)

        if mode in ("peek", "dump"):
            grants = list(
                AuthGrant.objects.filter(asset=asset, consumed_at__isnull=True)
                .order_by("created_at")[:100]
            )

            if as_json or mode == "dump":
                payload = [
                    {
                        "rhid": g.rhid,
                        "line": build_grant_line(g),
                        "created_at": g.created_at.isoformat(),
                        "sessionlength": int(g.sessionlength or 0),
                        "uploadrate": int(g.uploadrate or 0),
                        "downloadrate": int(g.downloadrate or 0),
                        "uploadquota": int(g.uploadquota or 0),
                        "downloadquota": int(g.downloadquota or 0),
                        "redirurl": g.redirurl or "",
                        "custom": g.custom or "",
                    }
                    for g in grants
                ]
                return JsonResponse({"status": "ok", "count": len(payload), "grants": payload})

            lines = [(build_grant_line(g) or "(invalid)") for g in grants]
            body = ("\n".join(lines) + "\n") if lines else "none\n"
            return HttpResponse(body, content_type="text/plain; charset=utf-8")

        if mode == "clear":
            now = timezone.now()
            updated = (
                AuthGrant.objects.filter(asset=asset, consumed_at__isnull=True)
                .update(consumed_at=now)
            )
            return JsonResponse({"status": "ok", "cleared": updated}) if as_json else HttpResponse(
                "OK\n",
                content_type="text/plain",
            )

        if mode not in ("view", "list"):
            return JsonResponse({"status": "bad_request", "error": "invalid auth_get"}, status=400) \
                if as_json else HttpResponseBadRequest("invalid auth_get")

        def _emit_response(body: str, *, consumed_id: Optional[int] = None) -> HttpResponse:
            resp = HttpResponse(body, content_type="text/plain; charset=utf-8")
            resp["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            resp["Pragma"] = "no-cache"
            resp["Connection"] = "close"
            if consumed_id:
                resp["X-Authmon-ConsumedId"] = str(consumed_id)
            return resp

        if mode == "view" and not as_json:
            now = timezone.now()
            with transaction.atomic():
                g = (
                    AuthGrant.objects.select_for_update(skip_locked=True)
                    .filter(asset=asset, consumed_at__isnull=True)
                    .order_by("created_at")
                    .first()
                )

                if not g:
                    maybe_requeue_stale_grants()
                    return _emit_response("none\n")

                line = build_grant_line(g)
                if not line:
                    g.consumed_at = now
                    g.save(update_fields=["consumed_at"])
                    return _emit_response("none\n")

                g.consumed_at = now
                g.last_emitted_at = now
                g.emit_attempts = (g.emit_attempts or 0) + 1
                g.save(update_fields=["consumed_at", "last_emitted_at", "emit_attempts"])

            return _emit_response(line + "\n", consumed_id=g.pk)

        grants = list(
            AuthGrant.objects.filter(asset=asset, consumed_at__isnull=True)
            .order_by("created_at")[:50]
        )

        if as_json:
            return JsonResponse(
                {
                    "status": "ok",
                    "grants": [
                        {
                            "rhid": g.rhid,
                            "sessionlength": int(g.sessionlength or 0),
                            "uploadrate": int(g.uploadrate or 0),
                            "downloadrate": int(g.downloadrate or 0),
                            "uploadquota": int(g.uploadquota or 0),
                            "downloadquota": int(g.downloadquota or 0),
                            "redirurl": g.redirurl or "",
                            "custom": g.custom or "",
                            "created_at": g.created_at.isoformat(),
                            "line": build_grant_line(g),
                        }
                        for g in grants
                    ],
                }
            )

        lines = [build_grant_line(g).strip() for g in grants if build_grant_line(g)]
        body = ("\n".join(lines) + "\n") if lines else "none\n"
        return _emit_response(body)

    except Exception:
        logger.exception("handle_authmon_common: unexpected error", extra={"assetid": assetid})
        return HttpResponseServerError("Server error")
    finally:
        ms = (timezone.now() - start).total_seconds() * 1000
        logger.debug("handle_authmon_common: done", extra={"assetid": assetid, "ms": round(ms, 2)})


REQUEUE_AFTER_SECONDS = 45


def maybe_requeue_stale_grants() -> int:
    now = timezone.now()
    cutoff = now - timezone.timedelta(seconds=REQUEUE_AFTER_SECONDS)
    count = 0

    with transaction.atomic():
        stale_qs = (
            AuthGrant.objects.select_for_update(skip_locked=True)
            .filter(
                consumed_at__isnull=False,
                confirmed_at__isnull=True,
                emit_attempts=1,
                last_emitted_at__lt=cutoff,
            )
            .order_by("created_at")[:100]
        )

        for g in stale_qs:
            g.consumed_at = None
            g.emit_attempts = 2
            g.save(update_fields=["consumed_at", "emit_attempts"])
            count += 1

    if count:
        logger.info("authmon_requeue_once", extra={"count": count})

    return count