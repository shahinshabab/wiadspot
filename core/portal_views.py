"""Website account screens, independent of the captive-portal/FAS flow."""

import os
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q, Sum
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from ads.models import Ad, AdMetrics, Asset, AudienceSession, Campaign, UserSubscription
from config.host_routing import site_address
from .portal_forms import CampaignSubmissionForm

ROLES = {
    "admin": {
        "group": "Admin",
        "label": "Administrator",
        "title": "Platform overview",
        "subtitle": "A clear view of your locations, campaigns and community.",
        "icon": "grid-1x2",
    },
    "manager": {
        "group": "Manager",
        "label": "Ad manager",
        "title": "Campaign overview",
        "subtitle": "Keep great campaigns moving, from review to delivery.",
        "icon": "megaphone",
    },
    "customer": {
        "group": "Client",
        "label": "Advertising customer",
        "title": "Your advertising, at a glance",
        "subtitle": "Reach people where they connect. See how your posters perform.",
        "icon": "image",
    },
    "owner": {
        "group": "Partner",
        "label": "Location owner",
        "title": "Your location workspace",
        "subtitle": "Your Wi-Fi, your audience. Manage the places you own.",
        "icon": "geo-alt",
    },
}


def role_details(role):
    if role not in ROLES:
        raise Http404("Account type not found")
    return ROLES[role]


def authorize(request, role):
    details = role_details(role)
    if request.workspace_role and request.workspace_role != role:
        raise PermissionDenied("This workspace belongs to another account type.")
    if not request.user.is_authenticated:
        return redirect(reverse("account_login") + "?" + urlencode({"role": role}))
    if not request.user.groups.filter(name=details["group"]).exists():
        raise PermissionDenied("This account does not have access to this workspace.")
    if request.workspace_role and request.session.get("workspace_role", role) != role:
        raise PermissionDenied("Sign in separately to this workspace.")
    return None


@require_http_methods(["GET", "POST"])
def account_login(request):
    role = request.workspace_role or request.POST.get(
        "role", request.GET.get("role", "customer")
    )
    details = role_details(role)
    error = ""
    if request.workspace_role:
        supplied_role = (
            request.POST.get("role")
            if request.method == "POST"
            else request.GET.get("role")
        )
        if supplied_role and supplied_role != request.workspace_role:
            raise PermissionDenied(
                "The account type is fixed by this workspace address."
            )
    if request.method == "POST":
        user = authenticate(
            request,
            username=request.POST.get("username", "").strip(),
            password=request.POST.get("password", ""),
        )
        if user and user.groups.filter(name=details["group"]).exists():
            login(request, user)
            request.session["workspace_role"] = role
            return redirect("portal_dashboard", role=role)
        error = "The credentials or account type are incorrect. Please try again."
    elif (
        request.user.is_authenticated
        and request.user.groups.filter(name=details["group"]).exists()
        and request.session.get("workspace_role", role) == role
    ):
        return redirect("portal_dashboard", role=role)
    return render(
        request,
        "platform/login.html",
        {
            "role": role,
            "account": details,
            "roles": [(role, details)] if request.workspace_role else ROLES.items(),
            "error": error,
        },
    )


@require_POST
def account_logout(request):
    logout(request)
    return redirect(site_address(request) + "/")


@require_http_methods(["GET"])
def workspace_home(request):
    return dashboard(request, request.workspace_role)


@require_http_methods(["GET"])
def dashboard(request, role):
    response = authorize(request, role)
    if response:
        return response
    now = timezone.localdate()
    month_start = now.replace(day=1)
    campaigns = Campaign.objects.select_related("owner").prefetch_related("ads")
    locations = Asset.objects.all()
    metrics = AdMetrics.objects.filter(date__gte=month_start, date__lte=now)
    sessions = AudienceSession.objects.filter(
        session_started_at__date__gte=month_start, session_started_at__date__lte=now
    )
    if role == "customer":
        campaigns = campaigns.filter(owner=request.user)
        locations = locations.filter(placements__ad__owner=request.user).distinct()
        metrics = metrics.filter(ad__owner=request.user)
        sessions = sessions.filter(ad__owner=request.user)
    elif role == "owner":
        locations = locations.filter(partner=request.user, owner_type="PARTNER")
        campaigns = campaigns.filter(
            Q(owner=request.user) | Q(ads__placements__asset__in=locations)
        ).distinct()
        metrics = metrics.filter(placement__asset__in=locations)
        sessions = sessions.filter(asset__in=locations)
    totals = metrics.aggregate(impressions=Sum("impressions"), clicks=Sum("clicks"))
    impressions = totals["impressions"] or 0
    clicks = totals["clicks"] or 0
    stats = [
        {
            "label": "Campaigns",
            "value": campaigns.count(),
            "icon": "megaphone",
            "hint": "All campaign statuses",
        },
        {
            "label": "Locations",
            "value": locations.count(),
            "icon": "geo-alt",
            "hint": "Connected to this workspace",
        },
        {
            "label": "Ad impressions",
            "value": impressions,
            "icon": "eye",
            "hint": "Recorded this month",
        },
        {
            "label": "Ad clicks",
            "value": clicks,
            "icon": "cursor",
            "hint": "Recorded this month",
        },
    ]
    if role == "owner":
        stats[0] = {
            "label": "Verified visitors",
            "value": sessions.filter(is_verified=True)
            .values("audience_id")
            .distinct()
            .count(),
            "icon": "people",
            "hint": "Unique visitors this month",
        }
    context = {
        "role": role,
        "account": ROLES[role],
        "stats": stats,
        "campaigns": campaigns[:8],
        "locations": locations[:6],
        "pending_count": campaigns.filter(review_status="PENDING").count(),
        "subscription": UserSubscription.objects.select_related("plan")
        .filter(user=request.user)
        .first(),
        "click_rate": round(clicks / impressions * 100, 1) if impressions else 0,
        "month": now,
        "demo": os.environ.get("WIADSPOT_DEMO") == "1",
    }
    return render(request, "platform/dashboard.html", context)


@require_http_methods(["GET", "POST"])
def create_campaign(request, role):
    response = authorize(request, role)
    if response:
        return response
    if role not in {"customer", "owner"}:
        raise PermissionDenied(
            "Use an advertising customer or location owner account to submit a poster."
        )
    form = CampaignSubmissionForm(
        request.POST or None, request.FILES or None, user=request.user, role=role
    )
    if request.method == "POST" and form.is_valid():
        if Campaign.objects.filter(
            owner=request.user, name=form.cleaned_data["name"]
        ).exists():
            form.add_error("name", "You already have a campaign with this name.")
        else:
            location = form.cleaned_data["location"]
            if "IMAGE" not in [
                kind.strip().upper() for kind in location.supported_ad_types.split(",")
            ]:
                form.add_error(
                    "location", "This location does not support image posters."
                )
            else:
                with transaction.atomic():
                    campaign = Campaign.objects.create(
                        owner=request.user,
                        name=form.cleaned_data["name"],
                        review_status="PENDING",
                        submitted_at=timezone.now(),
                        start_date=timezone.localdate(),
                        created_by=request.user,
                    )
                    ad = Ad.objects.create(
                        owner=request.user,
                        campaign=campaign,
                        title=form.cleaned_data["title"],
                        ad_type="IMAGE",
                        media_file=form.cleaned_data["poster"],
                        target_url=form.cleaned_data["target_url"],
                        status="PENDING",
                        created_by=request.user,
                    )
                    ad.placements.create(
                        asset=location,
                        requested_by=request.user,
                        status="PENDING",
                        serving_enabled=False,
                    )
                messages.success(
                    request,
                    "Poster submitted. Your campaign and placement are awaiting review.",
                )
                return redirect("portal_dashboard", role=role)
    return render(
        request,
        "platform/campaign_form.html",
        {"role": role, "account": ROLES[role], "form": form},
    )
