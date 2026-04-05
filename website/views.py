from django.core.cache import cache
from django.contrib import messages
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods
from django.contrib.staticfiles import finders
from django.utils import timezone
from .models import ContactMessage
from .forms import ContactForm
import logging 
import json
from datetime import datetime


logger = logging.getLogger(__name__) 

RATE_LIMIT_KEY = "contact_rate_{ip}"
RATE_LIMIT_SECONDS = 60

# -------------------------
# Dashboard / Home
# -------------------------
def landing(request):
    start = timezone.now()
    try:
        articles = _load_articles_index()[:3]

        host = request.get_host().split(":")[0].lower()
        is_local = host.endswith(".local") or "127.0.0.1" in host or "localhost" in host

        scheme = "http" if is_local else "https"
        base_domain = "wiadspot.local:8000" if is_local else "wiadspot.com"

        client_login_url = f"{scheme}://clients.{base_domain}/login/"
        partner_login_url = f"{scheme}://partner.{base_domain}/login/"

        logger.info("landing: rendering", extra={"articles_count": len(articles)})

        return render(
            request,
            "landing/landing_home.html",
            {
                "articles": articles,
                "client_login_url": client_login_url,
                "partner_login_url": partner_login_url,
            },
        )
    finally:
        _ms = (timezone.now() - start).total_seconds() * 1000
        logger.debug("landing: done", extra={"ms": round(_ms, 2)})

def landing_articles(request):
    start = timezone.now()
    try:
        return render(request, "landing/landing_articles.html")
    finally:
        _ms = (timezone.now() - start).total_seconds() * 1000
        logger.debug("landing_articles (shell): done", extra={"ms": round(_ms, 2)})

def _load_articles_index():
    start = timezone.now()
    path = finders.find("articles/index.json")
    if not path:
        logger.warning("_load_articles_index: index missing")
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            items = json.load(f)
        # sort by published_at desc (YYYY-MM-DD)
        def _dt(a):
            try:
                return datetime.strptime(a.get("published_at", ""), "%Y-%m-%d")
            except Exception:
                return datetime.min
        out = sorted(items, key=_dt, reverse=True)
        logger.debug("_load_articles_index: loaded", extra={"count": len(out)})
        return out
    except Exception as e:
        logger.exception("_load_articles_index: failed to load/parse", extra={"path": path})
        return []
    finally:
        _ms = (timezone.now() - start).total_seconds() * 1000
        logger.debug("_load_articles_index: done", extra={"ms": round(_ms, 2)})

def landing_articles(request):
    start = timezone.now()
    try:
        articles = _load_articles_index()
        logger.info("landing_articles: rendering", extra={"articles_count": len(articles)})
        return render(request, "landing/landing_articles.html", {"articles": articles})
    finally:
        _ms = (timezone.now() - start).total_seconds() * 1000
        logger.debug("landing_articles: done", extra={"ms": round(_ms, 2)})

def landing_article_read(request, slug: str):
    start = timezone.now()
    try:
        articles = _load_articles_index()
        art = next((a for a in articles if a.get("slug") == slug), None)
        if not art:
            logger.warning("landing_article_read: not found", extra={"slug": slug})
            raise Http404("Article not found")
        content_path = art.get("content_path")
        full_path = finders.find(content_path) if content_path else None
        if not full_path:
            logger.error("landing_article_read: content file missing", extra={"slug": slug, "content_path": content_path})
            raise Http404("Content file missing")
        with open(full_path, "r", encoding="utf-8") as f:
            html = f.read()
        art["content_html"] = mark_safe(html)  # static, trusted by you
        logger.info("landing_article_read: rendering", extra={"slug": slug})
        return render(request, "landing/landing_article_read.html", {"article": art, "recent": articles[:6]})
    except Http404:
        raise
    except Exception:
        logger.exception("landing_article_read: unexpected error", extra={"slug": slug})
        raise
    finally:
        _ms = (timezone.now() - start).total_seconds() * 1000
        logger.debug("landing_article_read: done", extra={"slug": slug, "ms": round(_ms, 2)})

def get_client_ip(request):
    # honor common proxy header if you’re behind a reverse proxy (Nginx)
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        ip = xff.split(",")[0].strip()
        logger.debug("get_client_ip: via x-forwarded-for", extra={"ip": ip})
        return ip
    ip = request.META.get("REMOTE_ADDR")
    logger.debug("get_client_ip: via remote_addr", extra={"ip": ip})
    return ip

@require_http_methods(["GET", "POST"])
def landing_contact(request):
    start = timezone.now()
    try:
        if request.method == "POST":
            ip = get_client_ip(request)
            if cache.get(RATE_LIMIT_KEY.format(ip=ip)):
                logger.info("landing_contact: rate-limited", extra={"ip": ip})
                messages.error(request, "Please wait a minute before submitting again.")
                return redirect("landing_contact")

            form = ContactForm(request.POST)
            if form.is_valid():
                cm = ContactMessage.objects.create(
                    name=form.cleaned_data["name"],
                    email=form.cleaned_data["email"],
                    message=form.cleaned_data["message"],
                    ip_address=ip,
                    user_agent=request.META.get("HTTP_USER_AGENT", "")[:500],
                    referer=request.META.get("HTTP_REFERER", "")[:500],
                )
                cache.set(RATE_LIMIT_KEY.format(ip=ip), True, RATE_LIMIT_SECONDS)
                logger.info("landing_contact: saved message", extra={"ip": ip, "id": cm.id})
                messages.success(request, "Thanks! We’ll get back to you soon.")
                return redirect("landing_contact")
            else:
                logger.warning("landing_contact: invalid form", extra={"errors": form.errors.get_json_data()})
        else:
            form = ContactForm()

        return render(request, "landing/landing_contact.html", {"form": form})
    except Exception:
        logger.exception("landing_contact: unexpected error")
        raise
    finally:
        _ms = (timezone.now() - start).total_seconds() * 1000
        logger.debug("landing_contact: done", extra={"ms": round(_ms, 2)})

def landing_about(request):
    logger.debug("landing_about: render")
    return render(request, "landing/landing_about.html")

def landing_career(request):
    logger.debug("landing_career: render")
    return render(request, "landing/landing_career.html")