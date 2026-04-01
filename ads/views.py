from django.shortcuts import redirect, render
from config.decorators import manager_required
import logging

from django.conf import settings
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.http import HttpRequest, HttpResponseBadRequest, HttpResponseServerError, HttpResponse 
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from ads.services.runtime_service import (
    AdServeError,
    serve_ad_for_asset,
    log_click_for_session,
)
from ads.models import AuthGrant, Audience, AudienceSession
from ads.utils import (
    Msg91Error,
    _normalize_indian_msisdn,
    mask_phone,
    retry_msg91_otp,
    send_and_get_req_id,
    verify_msg91_otp,
    handle_authmon_inline,
    build_grant_line,
    decode_fas,
    asset_auth_defaults,
    remote_ip,
    resolve_asset_from_request,
    strip_token,
)

logger = logging.getLogger(__name__)


@manager_required
def home(request):
    return render(request, "ads/home.html")


def _k_reqid(portal_id, msisdn):
    return f"fas:reqid:{portal_id}:{msisdn}"


def _k_cool_resend(portal_id, msisdn):
    return f"fas:cool:resend:{portal_id}:{msisdn}"


def _k_cool_verify(portal_id, msisdn):
    return f"fas:cool:verify:{portal_id}:{msisdn}"


def _is_cooling(key):
    return bool(cache.get(key))


def _set_cooldown(key, seconds):
    cache.set(key, 1, timeout=seconds)


def _safe_msisdn(phone: str) -> str:
    try:
        return _normalize_indian_msisdn(phone)
    except Msg91Error:
        return ""


def _build_common_context(
    *,
    portal,
    portal_owner,
    fas_b64="",
    iv_b64="",
    gatewayaddress="",
    tok="",
    redir="",
    ad_payload=None,
    ad_error="",
    error="",
    extra=None,
):
    ctx = {
        "fas": fas_b64,
        "iv": iv_b64,
        "gatewayaddress": gatewayaddress,
        "tok": tok,
        "redir": redir,
        "error": error,
        "portal": portal,
        "owner": portal_owner,
        "username": getattr(portal_owner, "username", ""),
        "portalid": getattr(portal, "name", portal.pk),
        "ad_payload": ad_payload,
        "ad_error": ad_error,
    }
    if extra:
        ctx.update(extra)
    return ctx


@csrf_exempt
def fas(request: HttpRequest, assetid=None, username=None):
    """
    L3/L4 FAS entrypoint:
      GET  -> render login page with live ad
      POST -> send_otp / resend_otp / verify_otp
      auth_get -> inline authmon response
    """
    start = timezone.now()

    try:
        logger.debug(
            "fas: request",
            extra={
                "method": request.method,
                "path": request.path,
                "assetid_arg": assetid,
                "username_arg": username,
                "ua": request.META.get("HTTP_USER_AGENT", "")[:160],
                "ip": remote_ip(request),
                "get_keys": sorted(request.GET.keys()),
                "post_keys": sorted(request.POST.keys()),
            },
        )

        if "auth_get" in request.GET or "auth_get" in request.POST:
            return handle_authmon_inline(request, assetid)

        asset = resolve_asset_from_request(request, assetid=assetid, username=username)
        if not asset or not asset.is_active:
            logger.warning(
                "fas: asset not found or inactive",
                extra={"assetid": assetid, "username": username},
            )
            return HttpResponseBadRequest("Asset not found or inactive.")

        asset_owner = getattr(asset, "owner", None) or getattr(asset, "actual_owner", None)
        if not asset_owner:
            logger.warning("fas: asset owner missing", extra={"asset_id": asset.id})
            return HttpResponseBadRequest("Asset owner not configured.")

        params_in = request.GET.copy() or request.POST.copy()
        fas_b64 = params_in.get("fas") or ""
        iv_b64 = params_in.get("iv") or ""
        redir = (params_in.get("redir") or getattr(asset, "default_redirurl", "") or "").strip()

        try:
            if fas_b64:
                decoded, hid, rhid = decode_fas(fas_b64, iv_b64 or None)
                tok = strip_token(rhid)
            else:
                decoded, hid, rhid = ({}, "", params_in.get("tok", ""))
                tok = strip_token(rhid)
        except Exception as e:
            logger.warning(
                "fas: invalid 'fas' parameter",
                extra={"asset_id": asset.id, "error": str(e)[:500]},
            )
            return HttpResponseBadRequest(f"Invalid 'fas' parameter: {e}")

        fas_params = {**{k: v for k, v in params_in.items() if v}, **decoded}

        gatewayaddress = (
            fas_params.get("gatewayaddress")
            or fas_params.get("gw_address")
            or fas_params.get("gateway")
            or ""
        )

        client_mac = (fas_params.get("clientmac") or fas_params.get("mac") or "").upper()
        client_ip = (
            fas_params.get("clientip")
            or (request.META.get("HTTP_X_FORWARDED_FOR", "").split(",", 1)[0].strip() or None)
            or request.META.get("REMOTE_ADDR")
        )

        asset_code = (
            fas_params.get("gatewayname")
            or fas_params.get("gatewayaddress")
            or getattr(asset, "code", None)
        )

        ad_payload = None
        ad_error = ""

        try:
            if asset_code:
                ad_payload = serve_ad_for_asset(
                    asset_code=asset_code,
                    visitor_token=tok or client_mac or client_ip,
                    client_ip=client_ip,
                    user_agent=request.META.get("HTTP_USER_AGENT", "")[:500],
                    request_meta={
                        "fas": bool(fas_b64),
                        "gatewayaddress": gatewayaddress,
                        "client_mac": client_mac,
                        "client_ip": client_ip,
                        "asset_id": asset.id,
                    },
                )
        except AdServeError as e:
            logger.info("fas: no eligible ad", extra={"asset_code": asset_code, "error": str(e)})
            ad_error = str(e)
        except Exception:
            logger.exception("fas: unexpected ad serving error", extra={"asset_code": asset_code})
            ad_error = "Unable to load ad."

        if request.method == "GET":
            return render(
                request,
                "fas/login.html",
                _build_common_context(
                    asset=asset,
                    asset_owner=asset_owner,
                    fas_b64=fas_b64,
                    iv_b64=iv_b64,
                    gatewayaddress=gatewayaddress,
                    tok=tok,
                    redir=redir,
                    ad_payload=ad_payload,
                    ad_error=ad_error,
                ),
            )

        actions = request.POST.getlist("action")
        action = actions[-1].strip() if actions else ""

        if not action:
            if (request.POST.get("otp") or "").strip():
                action = "verify_otp"
            elif request.POST.get("req_id"):
                action = "resend_otp"

        if action == "send_otp":
            phone = (request.POST.get("phone") or "").strip()
            tnc_ok = request.POST.get("tnc") == "yes"
            msisdn = _safe_msisdn(phone)

            if not msisdn or not tnc_ok:
                err = (
                    "Enter a valid mobile number."
                    if not msisdn
                    else "You must accept the Terms & Conditions."
                )
                return render(
                    request,
                    "fas/login.html",
                    _build_common_context(
                        asset=asset,
                        asset_owner=asset_owner,
                        fas_b64=fas_b64,
                        iv_b64=iv_b64,
                        gatewayaddress=gatewayaddress,
                        tok=tok,
                        redir=redir,
                        ad_payload=ad_payload,
                        ad_error=ad_error,
                        error=err,
                    ),
                )

            resend_gate = getattr(settings, "OTP_RESEND_COOLDOWN", 30)
            if _is_cooling(_k_cool_resend(asset.id, msisdn)):
                return render(
                    request,
                    "fas/login.html",
                    _build_common_context(
                        asset=asset,
                        asset_owner=asset_owner,
                        fas_b64=fas_b64,
                        iv_b64=iv_b64,
                        gatewayaddress=gatewayaddress,
                        tok=tok,
                        redir=redir,
                        ad_payload=ad_payload,
                        ad_error=ad_error,
                        error=f"Please wait {resend_gate}s before requesting another OTP.",
                    ),
                )

            audience, _ = Audience.objects.get_or_create(
                mobile_number=msisdn,
                defaults={
                    "owner": asset_owner,
                    "consent_accepted": tnc_ok,
                    "consent_accepted_at": timezone.now() if tnc_ok else None,
                },
            )

            if audience.owner_id != asset_owner.id:
                audience.owner = asset_owner
            if tnc_ok and not audience.consent_accepted:
                audience.consent_accepted = True
                audience.consent_accepted_at = timezone.now()

            audience.last_seen_at = timezone.now()
            audience.save()

            session = AudienceSession.objects.create(
                audience=audience,
                owner=asset_owner,
                asset=asset,
                ad_id=ad_payload.get("ad_id") if ad_payload else None,
                serve_session_id=ad_payload.get("serve_session_id") if ad_payload else None,
                rhid=tok or "",
                client_ip=client_ip,
                client_mac=client_mac or "",
                user_agent=request.META.get("HTTP_USER_AGENT", "")[:1000],
                auth_status="OTP_SENT",
                otp_sent_at=timezone.now(),
                request_meta={
                    "gatewayaddress": gatewayaddress,
                    "redir": redir,
                    "asset_code": asset_code,
                },
            )

            try:
                req_id = send_and_get_req_id(msisdn)
            except Msg91Error as e:
                logger.warning(
                    "fas: otp send failed",
                    extra={"asset_id": asset.id, "msisdn": msisdn, "error": str(e)[:200]},
                )
                session.auth_status = "FAILED"
                session.save(update_fields=["auth_status"])
                return render(
                    request,
                    "fas/login.html",
                    _build_common_context(
                        asset=asset,
                        asset_owner=asset_owner,
                        fas_b64=fas_b64,
                        iv_b64=iv_b64,
                        gatewayaddress=gatewayaddress,
                        tok=tok,
                        redir=redir,
                        ad_payload=ad_payload,
                        ad_error=ad_error,
                        error="Could not send OTP at the moment. Please try again.",
                    ),
                )

            cache.set(_k_reqid(asset.id, msisdn), req_id, timeout=600)
            _set_cooldown(_k_cool_resend(asset.id, msisdn), resend_gate)

            return render(
                request,
                "fas/auth.html",
                _build_common_context(
                    asset=asset,
                    asset_owner=asset_owner,
                    fas_b64=fas_b64,
                    iv_b64=iv_b64,
                    gatewayaddress=gatewayaddress,
                    tok=tok,
                    redir=redir,
                    ad_payload=ad_payload,
                    ad_error=ad_error,
                    extra={
                        "phone": msisdn,
                        "phone_masked": mask_phone(msisdn),
                        "audience_session_id": session.pk,
                        "initial_gate": 30,
                        "verify_cooldown": 15,
                        "resend_cooldown": resend_gate,
                        "req_id": req_id,
                    },
                ),
            )

        if action == "resend_otp":
            phone = (request.POST.get("phone") or "").strip()
            msisdn = _safe_msisdn(phone)
            resend_gate = getattr(settings, "OTP_RESEND_COOLDOWN", 30)

            if not msisdn:
                return render(
                    request,
                    "fas/login.html",
                    _build_common_context(
                        asset=asset,
                        asset_owner=asset_owner,
                        fas_b64=fas_b64,
                        iv_b64=iv_b64,
                        gatewayaddress=gatewayaddress,
                        tok=tok,
                        redir=redir,
                        ad_payload=ad_payload,
                        ad_error=ad_error,
                        error="Enter a valid mobile number.",
                    ),
                )

            req_id = cache.get(_k_reqid(asset.id, msisdn))

            if _is_cooling(_k_cool_resend(asset.id, msisdn)):
                return render(
                    request,
                    "fas/auth.html",
                    _build_common_context(
                        asset=asset,
                        asset_owner=asset_owner,
                        fas_b64=fas_b64,
                        iv_b64=iv_b64,
                        gatewayaddress=gatewayaddress,
                        tok=tok,
                        redir=redir,
                        ad_payload=ad_payload,
                        ad_error=ad_error,
                        error=f"Please wait {resend_gate}s before requesting another OTP.",
                        extra={
                            "phone": msisdn,
                            "phone_masked": mask_phone(msisdn),
                            "audience_session_id": request.POST.get("audience_session_id"),
                            "initial_gate": 0,
                            "verify_cooldown": 15,
                            "resend_cooldown": resend_gate,
                            "req_id": req_id,
                        },
                    ),
                )

            try:
                if not req_id:
                    req_id = send_and_get_req_id(msisdn)
                    cache.set(_k_reqid(asset.id, msisdn), req_id, timeout=600)
                else:
                    retry_msg91_otp(req_id)
            except Msg91Error as e:
                logger.warning(
                    "fas: otp resend failed",
                    extra={"asset_id": asset.id, "msisdn": msisdn, "error": str(e)[:200]},
                )
                return render(
                    request,
                    "fas/auth.html",
                    _build_common_context(
                        asset=asset,
                        asset_owner=asset_owner,
                        fas_b64=fas_b64,
                        iv_b64=iv_b64,
                        gatewayaddress=gatewayaddress,
                        tok=tok,
                        redir=redir,
                        ad_payload=ad_payload,
                        ad_error=ad_error,
                        error="Could not resend OTP right now.",
                        extra={
                            "phone": msisdn,
                            "phone_masked": mask_phone(msisdn),
                            "audience_session_id": request.POST.get("audience_session_id"),
                            "initial_gate": 0,
                            "verify_cooldown": 15,
                            "resend_cooldown": resend_gate,
                            "req_id": req_id,
                        },
                    ),
                )

            _set_cooldown(_k_cool_resend(asset.id, msisdn), resend_gate)

            return render(
                request,
                "fas/auth.html",
                _build_common_context(
                    asset=asset,
                    asset_owner=asset_owner,
                    fas_b64=fas_b64,
                    iv_b64=iv_b64,
                    gatewayaddress=gatewayaddress,
                    tok=tok,
                    redir=redir,
                    ad_payload=ad_payload,
                    ad_error=ad_error,
                    extra={
                        "phone": msisdn,
                        "phone_masked": mask_phone(msisdn),
                        "audience_session_id": request.POST.get("audience_session_id"),
                        "initial_gate": 0,
                        "verify_cooldown": 15,
                        "resend_cooldown": resend_gate,
                        "req_id": req_id,
                    },
                ),
            )

        if action == "verify_otp":
            otp = (request.POST.get("otp") or "").strip()
            phone_in = (request.POST.get("phone") or "").strip()
            audience_session_id = request.POST.get("audience_session_id")

            verify_gate = 15
            resend_gate = getattr(settings, "OTP_RESEND_COOLDOWN", 30)
            otp_min = getattr(settings, "OTP_MIN_LEN", 4)
            otp_max = getattr(settings, "OTP_MAX_LEN", 8)

            msisdn = _safe_msisdn(phone_in)
            if not msisdn:
                return render(
                    request,
                    "fas/login.html",
                    _build_common_context(
                        asset=asset,
                        asset_owner=asset_owner,
                        fas_b64=fas_b64,
                        iv_b64=iv_b64,
                        gatewayaddress=gatewayaddress,
                        tok=tok,
                        redir=redir,
                        ad_payload=ad_payload,
                        ad_error=ad_error,
                        error="Enter a valid mobile number.",
                    ),
                )

            if not otp.isdigit() or not (otp_min <= len(otp) <= otp_max):
                return render(
                    request,
                    "fas/auth.html",
                    _build_common_context(
                        asset=asset,
                        asset_owner=asset_owner,
                        fas_b64=fas_b64,
                        iv_b64=iv_b64,
                        gatewayaddress=gatewayaddress,
                        tok=tok,
                        redir=redir,
                        ad_payload=ad_payload,
                        ad_error=ad_error,
                        error=f"Enter a valid {otp_min}-{otp_max} digit OTP.",
                        extra={
                            "phone": msisdn,
                            "phone_masked": mask_phone(msisdn),
                            "audience_session_id": audience_session_id,
                            "initial_gate": 0,
                            "verify_cooldown": verify_gate,
                            "resend_cooldown": resend_gate,
                            "req_id": request.POST.get("req_id") or cache.get(_k_reqid(asset.id, msisdn), ""),
                        },
                    ),
                )

            req_id = cache.get(_k_reqid(asset.id, msisdn)) or (request.POST.get("req_id") or "").strip()
            if not req_id:
                return render(
                    request,
                    "fas/auth.html",
                    _build_common_context(
                        asset=asset,
                        asset_owner=asset_owner,
                        fas_b64=fas_b64,
                        iv_b64=iv_b64,
                        gatewayaddress=gatewayaddress,
                        tok=tok,
                        redir=redir,
                        ad_payload=ad_payload,
                        ad_error=ad_error,
                        error="Session expired. Please resend OTP.",
                        extra={
                            "phone": msisdn,
                            "phone_masked": mask_phone(msisdn),
                            "audience_session_id": audience_session_id,
                            "initial_gate": 0,
                            "verify_cooldown": verify_gate,
                            "resend_cooldown": resend_gate,
                        },
                    ),
                )

            if _is_cooling(_k_cool_verify(asset.id, msisdn)):
                return render(
                    request,
                    "fas/auth.html",
                    _build_common_context(
                        asset=asset,
                        asset_owner=asset_owner,
                        fas_b64=fas_b64,
                        iv_b64=iv_b64,
                        gatewayaddress=gatewayaddress,
                        tok=tok,
                        redir=redir,
                        ad_payload=ad_payload,
                        ad_error=ad_error,
                        error=f"Please wait {verify_gate}s before trying again.",
                        extra={
                            "phone": msisdn,
                            "phone_masked": mask_phone(msisdn),
                            "audience_session_id": audience_session_id,
                            "initial_gate": 0,
                            "verify_cooldown": verify_gate,
                            "resend_cooldown": resend_gate,
                            "req_id": req_id,
                        },
                    ),
                )

            _set_cooldown(_k_cool_verify(asset.id, msisdn), verify_gate)

            try:
                verify_msg91_otp(req_id, otp)
            except Msg91Error:
                return render(
                    request,
                    "fas/auth.html",
                    _build_common_context(
                        asset=asset,
                        asset_owner=asset_owner,
                        fas_b64=fas_b64,
                        iv_b64=iv_b64,
                        gatewayaddress=gatewayaddress,
                        tok=tok,
                        redir=redir,
                        ad_payload=ad_payload,
                        ad_error=ad_error,
                        error="Invalid or expired OTP. Please try again or resend.",
                        extra={
                            "phone": msisdn,
                            "phone_masked": mask_phone(msisdn),
                            "audience_session_id": audience_session_id,
                            "initial_gate": 0,
                            "verify_cooldown": verify_gate,
                            "resend_cooldown": resend_gate,
                            "req_id": req_id,
                        },
                    ),
                )

            audience, _ = Audience.objects.get_or_create(
                mobile_number=msisdn,
                defaults={"owner": asset_owner},
            )

            session = None
            if audience_session_id:
                session = AudienceSession.objects.filter(pk=audience_session_id, asset=asset).first()

            if session is None:
                session = AudienceSession.objects.create(
                    audience=audience,
                    owner=asset_owner,
                    asset=asset,
                    ad_id=ad_payload.get("ad_id") if ad_payload else None,
                    serve_session_id=ad_payload.get("serve_session_id") if ad_payload else None,
                    rhid=tok or "",
                    client_ip=client_ip,
                    client_mac=client_mac or "",
                    user_agent=request.META.get("HTTP_USER_AGENT", "")[:1000],
                    auth_status="OTP_VERIFIED",
                )

            if tok:
                session.rhid = tok
            if client_mac:
                session.client_mac = client_mac.upper()
            if client_ip:
                session.client_ip = client_ip

            session.is_verified = True
            session.verified_at = timezone.now()
            session.auth_status = "OTP_VERIFIED"
            session.save()

            if not audience.is_phone_verified:
                audience.first_verified_at = timezone.now()

            audience.is_phone_verified = True
            audience.last_verified_at = timezone.now()
            audience.last_login_at = timezone.now()
            audience.last_seen_at = timezone.now()
            audience.total_sessions = (audience.total_sessions or 0) + 1
            audience.total_verified_sessions = (audience.total_verified_sessions or 0) + 1
            audience.save()

            if not tok:
                return HttpResponseBadRequest("Missing token (rhid) from FAS parameters.")

            chosen_redir = (redir or getattr(asset, "default_redirurl", "") or "").strip()
            defaults = asset_auth_defaults(asset, redir=chosen_redir)

            last_err = None
            for _ in range(2):
                try:
                    with transaction.atomic():
                        grant = (
                            AuthGrant.objects.select_for_update(of=("self",))
                            .filter(asset=asset, rhid=tok)
                            .first()
                        )
                        if grant is None:
                            grant = AuthGrant.objects.create(
                                asset=asset,
                                audience_session=session,
                                rhid=tok,
                                consumed_at=None,
                                confirmed_at=None,
                                emit_attempts=0,
                                last_emitted_at=None,
                                **defaults,
                            )
                        else:
                            grant.audience_session = session
                            for k, v in defaults.items():
                                setattr(grant, k, v)
                            grant.consumed_at = None
                            grant.confirmed_at = None
                            grant.last_emitted_at = None
                            grant.emit_attempts = 0
                            grant.save()

                    logger.info(
                        "fas: queued authgrant",
                        extra={
                            "asset_id": asset.id,
                            "audience_session_id": session.pk,
                            "rhid_head": tok[:12],
                            "preview": build_grant_line(grant),
                        },
                    )
                    break
                except IntegrityError as e:
                    last_err = e
                    continue
            else:
                logger.exception(
                    "fas: enqueue grant failed",
                    extra={"asset_id": asset.id, "error": str(last_err)[:200]},
                )
                return HttpResponseServerError(
                    "Could not queue authorisation for router. Please retry."
                )

            wants_ui = (request.POST.get("show_ui") == "1") or settings.DEBUG
            if wants_ui:
                return render(
                    request,
                    "fas/auth.html",
                    _build_common_context(
                        asset=asset,
                        asset_owner=asset_owner,
                        fas_b64=fas_b64,
                        iv_b64=iv_b64,
                        gatewayaddress=gatewayaddress,
                        tok=tok,
                        redir=redir,
                        ad_payload=ad_payload,
                        ad_error=ad_error,
                        extra={
                            "phone": msisdn,
                            "phone_masked": mask_phone(msisdn),
                            "audience_session_id": session.pk,
                            "verified_ok": True,
                        },
                    ),
                )

            resp = HttpResponse(status=204)
            resp["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
            resp["Pragma"] = "no-cache"
            resp["Connection"] = "close"
            return resp

        return render(
            request,
            "fas/login.html",
            _build_common_context(
                asset=asset,
                asset_owner=asset_owner,
                fas_b64=fas_b64,
                iv_b64=iv_b64,
                gatewayaddress=gatewayaddress,
                tok=tok,
                redir=redir,
                ad_payload=ad_payload,
                ad_error=ad_error,
                error="Something went wrong. Please try again.",
            ),
        )

    except Exception:
        logger.exception("fas: unexpected error", extra={"assetid": assetid, "username": username})
        raise
    finally:
        ms = (timezone.now() - start).total_seconds() * 1000
        logger.debug("fas: done", extra={"assetid": assetid, "ms": round(ms, 2)})


def ad_click_redirect(request, session_id):
    """
    Click endpoint used by the ad UI.
    Logs click, then redirects to target url.
    """
    try:
        result = log_click_for_session(
            session_id=session_id,
            metadata={
                "ip": request.META.get("REMOTE_ADDR"),
                "ua": request.META.get("HTTP_USER_AGENT", "")[:500],
            },
        )
        target_url = result.get("target_url") or "/"
        return redirect(target_url)
    except Exception:
        logger.exception("ad_click_redirect failed", extra={"session_id": str(session_id)})
        return redirect("/")