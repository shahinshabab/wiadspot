"""Workspace pages for the ad marketplace (advertiser, owner, manager, admin)."""

from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods, require_POST

from ads.models import (
    Asset,
    Campaign,
    SubscriptionPlan,
    UserSubscription,
    Wallet,
    WalletTransaction,
)
from core.portal_views import authorize, base_context

from . import forms, rules, services
from .models import (
    EarningEntry,
    LocationRequest,
    MarketplaceSettings,
    SpotDevice,
    SpotProfile,
    Withdrawal,
)

User = get_user_model()


def guard(request, role, allowed):
    """Authenticate for *role* and require it to be one of *allowed*."""
    response = authorize(request, role)
    if response:
        return response
    if role not in allowed:
        raise PermissionDenied("This page isn't available for your account type.")
    return None


def pk_of(value):
    """A posted id as an int, or 0 (which matches nothing) for junk."""
    return int(value) if str(value or "").isdigit() else 0


def wallet_of(user):
    return Wallet.objects.filter(user=user).first()


# ------------------------------------------------------------- advertisers/owners


def _spot_payload(user, role):
    conf = MarketplaceSettings.load()
    rows = []
    for spot in rules.spots_for_booking(user, role).order_by("town__name", "asset__name")[:1500]:
        rate, free, _, _ = rules.booking_terms(user, spot, conf)
        if free:
            kind = "Your location"
        elif spot.mode == SpotProfile.MODE_LISTED:
            kind = "Owner location"
        else:
            kind = "WiadSpot location"
        rows.append(
            {
                "id": spot.pk,
                "name": spot.asset.name,
                "town": spot.town.name if spot.town else "",
                "kind": kind,
                "rate": str(rate),
                "free": free,
            }
        )
    return rows


@require_http_methods(["GET", "POST"])
def ad_create(request, role):
    response = guard(request, role, {"customer", "owner"})
    if response:
        return response
    form = forms.AdSubmissionForm(
        request.POST or None, request.FILES or None, user=request.user, role=role
    )
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            services.submit_ad(
                user=request.user,
                role=role,
                name=data["name"],
                title=data["title"],
                media=form.processed_file,
                ad_type=form.processed_type,
                target_url=data["target_url"],
                spots=list(data["spots"]),
                total_budget=data["total_budget"],
                daily_budget=data["daily_budget"],
                max_views=data["max_views"],
                start_date=data["start_date"],
                end_date=data["end_date"],
            )
        except services.MarketplaceError as exc:
            form.add_error(None, str(exc))
        else:
            messages.success(
                request, "Ad submitted for review. It goes live once an ad manager approves it."
            )
            return redirect("portal_campaigns", role=role)
    conf = MarketplaceSettings.load()
    wallet = wallet_of(request.user)
    return render(
        request,
        "marketplace/ad_form.html",
        {
            **base_context(role),
            "form": form,
            "conf": conf,
            "spots": _spot_payload(request.user, role),
            "selected": [int(x) for x in request.POST.getlist("spots") if x.isdigit()],
            "wallet_balance": wallet.balance if wallet else Decimal("0"),
            "subscribed": services.has_active_subscription(request.user),
        },
    )


@never_cache
@require_http_methods(["GET", "POST"])
def billing(request, role):
    response = guard(request, role, {"customer", "owner"})
    if response:
        return response
    if request.method == "POST":
        plan = get_object_or_404(SubscriptionPlan, pk=pk_of(request.POST.get("plan_id")), is_active=True)
        try:
            services.subscribe(request.user, plan)
        except services.MarketplaceError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, f"You're subscribed to {plan.name} for the next 30 days.")
        return redirect("portal_billing", role=role)
    wallet = wallet_of(request.user)
    return render(
        request,
        "marketplace/billing.html",
        {
            **base_context(role),
            "conf": MarketplaceSettings.load(),
            "plans": SubscriptionPlan.objects.filter(is_active=True).order_by("monthly_price"),
            "subscription": UserSubscription.objects.select_related("plan").filter(user=request.user).first(),
            "wallet": wallet,
            "transactions": WalletTransaction.objects.filter(wallet=wallet)[:15] if wallet else [],
        },
    )


# --------------------------------------------------------------- location owners


@require_http_methods(["GET", "POST"])
def owner_locations(request, role):
    response = guard(request, role, {"owner"})
    if response:
        return response
    request_form = forms.LocationRequestForm(prefix="new")
    list_form = forms.ListingForm(prefix="list")
    if request.method == "POST":
        if request.POST.get("form") == "install":
            request_form = forms.LocationRequestForm(request.POST, prefix="new")
            if request_form.is_valid():
                req = request_form.save(commit=False)
                req.user, req.kind = request.user, LocationRequest.KIND_INSTALL
                req.save()
                messages.success(request, "Request sent. Our team will review it and contact you.")
                return redirect("portal_locations", role=role)
        elif request.POST.get("form") == "list":
            list_form = forms.ListingForm(request.POST, prefix="list")
            if list_form.is_valid():
                asset = get_object_or_404(
                    Asset, pk=list_form.cleaned_data["asset_id"], owner_type="PARTNER", partner=request.user
                )
                try:
                    services.request_listing(request.user, asset, list_form.cleaned_data["town"])
                except services.MarketplaceError as exc:
                    messages.error(request, str(exc))
                else:
                    messages.success(request, "Sent to WiadSpot. An ad manager will review your location.")
                return redirect("portal_locations", role=role)
    spots = (
        SpotProfile.objects.select_related("asset", "town")
        .filter(asset__partner=request.user, asset__owner_type="PARTNER")
        .order_by("asset__name")
    )
    earned = dict(
        EarningEntry.objects.filter(owner=request.user)
        .values_list("asset_id")
        .annotate(total=Sum("amount"))
        .values_list("asset_id", "total")
    )
    open_assets = set(
        LocationRequest.objects.filter(user=request.user, status__in=LocationRequest.OPEN_STATUSES)
        .values_list("asset_id", flat=True)
    )
    rows = [
        {"spot": s, "earned": earned.get(s.asset_id, Decimal("0")), "pending": s.asset_id in open_assets}
        for s in spots
    ]
    return render(
        request,
        "marketplace/owner_locations.html",
        {
            **base_context(role),
            "rows": rows,
            "requests": LocationRequest.objects.filter(user=request.user).select_related("town")[:20],
            "request_form": request_form,
            "list_form": list_form,
            "conf": MarketplaceSettings.load(),
        },
    )


@never_cache
@require_http_methods(["GET", "POST"])
def owner_earnings(request, role):
    response = guard(request, role, {"owner"})
    if response:
        return response
    form = forms.WithdrawalForm()
    if request.method == "POST":
        form = forms.WithdrawalForm(request.POST)
        if form.is_valid():
            try:
                services.request_withdrawal(
                    request.user, form.cleaned_data["amount"], form.cleaned_data["payout_details"]
                )
            except services.MarketplaceError as exc:
                form.add_error("amount", str(exc))
            else:
                messages.success(request, "Withdrawal requested. WiadSpot will pay you and mark it paid.")
                return redirect("portal_earnings", role=role)
    return render(
        request,
        "marketplace/earnings.html",
        {
            **base_context(role),
            "summary": services.earnings_summary(request.user),
            "entries": EarningEntry.objects.filter(owner=request.user).select_related("asset")[:25],
            "withdrawals": Withdrawal.objects.filter(owner=request.user)[:20],
            "form": form,
            "conf": MarketplaceSettings.load(),
        },
    )


# ------------------------------------------------------------------ ad managers


@require_http_methods(["GET", "POST"])
def submissions(request, role):
    response = guard(request, role, {"manager", "admin"})
    if response:
        return response
    if request.method == "POST":
        campaign = get_object_or_404(Campaign, pk=pk_of(request.POST.get("campaign_id")), plan__isnull=False)
        action, remarks = request.POST.get("action"), request.POST.get("remarks", "").strip()
        if campaign.review_status != "PENDING":
            messages.error(request, "This submission was already reviewed.")
        elif action == "approve":
            services.approve_submission(campaign, request.user, remarks)
            messages.success(request, f"“{campaign.name}” approved. It will start serving on its locations.")
        elif action == "reject" and remarks:
            services.reject_submission(campaign, request.user, remarks)
            messages.success(request, f"“{campaign.name}” rejected.")
        else:
            messages.error(request, "Give a reason when rejecting an ad.")
        return redirect("portal_submissions", role=role)
    base = Campaign.objects.filter(plan__isnull=False).select_related("owner", "plan").prefetch_related(
        "ads", "ads__placements", "ads__placements__asset", "ads__placements__terms"
    )
    return render(
        request,
        "marketplace/submissions.html",
        {
            **base_context(role),
            "pending": base.filter(review_status="PENDING").order_by("submitted_at"),
            "recent": base.exclude(review_status="PENDING").order_by("-reviewed_at")[:15],
        },
    )


@require_http_methods(["GET", "POST"])
def location_requests(request, role):
    response = guard(request, role, {"manager", "admin"})
    if response:
        return response
    if request.method == "POST":
        req = get_object_or_404(LocationRequest, pk=pk_of(request.POST.get("request_id")))
        try:
            services.review_location_request(
                req, request.user, request.POST.get("action", ""), request.POST.get("note", "").strip()
            )
        except services.MarketplaceError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, "Request updated.")
        return redirect("portal_location_requests", role=role)
    qs = LocationRequest.objects.select_related("user", "town", "asset")
    return render(
        request,
        "marketplace/location_requests.html",
        {
            **base_context(role),
            "open_requests": qs.filter(status__in=LocationRequest.OPEN_STATUSES).order_by("created_at"),
            "closed_requests": qs.exclude(status__in=LocationRequest.OPEN_STATUSES)[:15],
        },
    )


# ----------------------------------------------------------------------- admin


@require_http_methods(["GET", "POST"])
def admin_settings(request, role):
    response = guard(request, role, {"admin"})
    if response:
        return response
    conf = MarketplaceSettings.load()
    form = forms.SettingsForm(request.POST or None, instance=conf, prefix="s")
    plans = forms.PlanFormSet(
        request.POST or None, queryset=SubscriptionPlan.objects.order_by("monthly_price"), prefix="p"
    )
    if request.method == "POST" and form.is_valid() and plans.is_valid():
        form.save()
        for plan_form in plans:
            if plan_form.has_changed():
                plan_form.save()
        messages.success(request, "Settings saved.")
        return redirect("portal_settings", role=role)
    return render(
        request, "marketplace/admin_settings.html", {**base_context(role), "form": form, "plans": plans}
    )


@require_http_methods(["GET", "POST"])
def admin_withdrawals(request, role):
    response = guard(request, role, {"admin"})
    if response:
        return response
    if request.method == "POST":
        action = request.POST.get("action")
        if action in ("pay", "reject"):
            try:
                services.process_withdrawal(
                    pk_of(request.POST.get("withdrawal_id")), request.user, action == "pay",
                    request.POST.get("note", "").strip(),
                )
            except (services.MarketplaceError, Withdrawal.DoesNotExist) as exc:
                messages.error(request, str(exc) or "Withdrawal not found.")
            else:
                messages.success(request, "Withdrawal updated.")
        return redirect("portal_withdrawals", role=role)
    qs = Withdrawal.objects.select_related("owner")
    return render(
        request,
        "marketplace/admin_withdrawals.html",
        {
            **base_context(role),
            "requested": qs.filter(status="REQUESTED").order_by("created_at"),
            "done": qs.exclude(status="REQUESTED")[:20],
        },
    )


@require_http_methods(["GET", "POST"])
def admin_wallets(request, role):
    response = guard(request, role, {"admin"})
    if response:
        return response
    form = forms.WalletCreditForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = User.objects.filter(username=form.cleaned_data["username"]).first()
        if user is None:
            form.add_error("username", "No user with this username.")
        else:
            try:
                wallet = services.credit_wallet(
                    user, form.cleaned_data["amount"], request.user, form.cleaned_data["reference"]
                )
            except services.MarketplaceError as exc:
                form.add_error("amount", str(exc))
            else:
                messages.success(request, f"Added ₹{form.cleaned_data['amount']} to {user.username}. New balance ₹{wallet.balance}.")
                return redirect("portal_wallets", role=role)
    recent = WalletTransaction.objects.select_related("wallet__user").filter(transaction_type="CREDIT")[:20]
    return render(
        request, "marketplace/admin_wallets.html", {**base_context(role), "form": form, "recent": recent}
    )


@require_http_methods(["GET"])
def admin_spots(request, role):
    response = guard(request, role, {"admin"})
    if response:
        return response
    q = request.GET.get("q", "").strip()
    spots = SpotProfile.objects.select_related("asset", "town", "asset__partner")
    if q:
        spots = spots.filter(Q(asset__name__icontains=q) | Q(town__name__icontains=q) | Q(asset__code__icontains=q))
    page = Paginator(spots.order_by("asset__name"), 40).get_page(request.GET.get("page"))
    return render(
        request, "marketplace/admin_spots.html", {**base_context(role), "page": page, "q": q}
    )


@never_cache
@require_http_methods(["GET", "POST"])
def admin_spot_edit(request, role, pk):
    response = guard(request, role, {"admin"})
    if response:
        return response
    spot = get_object_or_404(SpotProfile.objects.select_related("asset", "town"), pk=pk)
    form = forms.SpotForm(request.POST if request.POST.get("form") == "spot" else None, instance=spot)
    token = None
    if request.method == "POST":
        if request.POST.get("form") == "spot" and form.is_valid():
            form.save()
            messages.success(request, "Location updated.")
            return redirect("portal_spot_edit", role=role, pk=pk)
        if request.POST.get("form") == "device":
            _, token = services.issue_device_token(spot.asset)
    device = SpotDevice.objects.filter(asset=spot.asset).first()
    return render(
        request,
        "marketplace/admin_spot_edit.html",
        {**base_context(role), "spot": spot, "form": form, "device": device, "token": token},
    )


@require_POST
def admin_device_revoke(request, role, pk):
    response = guard(request, role, {"admin"})
    if response:
        return response
    spot = get_object_or_404(SpotProfile, pk=pk)
    SpotDevice.objects.filter(asset=spot.asset).update(is_active=False)
    messages.success(request, "Device key revoked. The spot can no longer authenticate until a new key is made.")
    return redirect("portal_spot_edit", role=role, pk=pk)
