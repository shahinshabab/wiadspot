"""Business operations: submissions, approvals, subscriptions, earnings, payouts."""

import uuid
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from ads.models import (
    Ad,
    Asset,
    Campaign,
    Placement,
    UserSubscription,
    Wallet,
    WalletTransaction,
)
from ads.services import manager_service

from . import rules
from .models import (
    CampaignPlan,
    LocationRequest,
    MarketplaceSettings,
    OwnerAccount,
    PlacementTerms,
    SpotDevice,
    SpotProfile,
    Withdrawal,
)

CENT = Decimal("0.01")


class MarketplaceError(Exception):
    """A rule was violated; the message is safe to show to the user."""


# ---------------------------------------------------------------- ad submissions


def has_active_subscription(user):
    sub = UserSubscription.objects.filter(user=user).first()
    return bool(sub and sub.is_valid_subscription())


@transaction.atomic
def submit_ad(*, user, role, name, title, media, ad_type, target_url, spots,
              total_budget, daily_budget, max_views, start_date, end_date):
    """Create a campaign, ad, plan and one pending placement per chosen spot."""
    allowed = {s.pk: s for s in rules.spots_for_booking(user, role)}
    chosen = []
    for spot in spots:
        if spot.pk not in allowed:
            raise MarketplaceError("One of the chosen locations is not available to you.")
        chosen.append(allowed[spot.pk])
    if not chosen:
        raise MarketplaceError("Choose at least one location.")

    conf = MarketplaceSettings.load()
    terms = [(spot, *rules.booking_terms(user, spot, conf)) for spot in chosen]
    paid = any(not free for _, _, free, _, _ in terms)
    if paid and total_budget <= 0:
        raise MarketplaceError("Set a total budget for the paid locations.")
    if not paid:
        total_budget = Decimal("0")

    if Campaign.objects.filter(owner=user, name=name).exists():
        raise MarketplaceError("You already have a campaign with this name.")
    sub = UserSubscription.objects.select_related("plan").filter(user=user).first()
    if sub and sub.is_valid_subscription() and sub.plan:
        used = Campaign.objects.filter(owner=user).exclude(review_status="REJECTED").count()
        if used >= sub.plan.max_campaigns:
            raise MarketplaceError(
                f"Your {sub.plan.name} plan allows {sub.plan.max_campaigns} campaign(s). "
                "Upgrade your plan to add more."
            )

    campaign = Campaign.objects.create(
        owner=user,
        name=name,
        review_status="PENDING",
        submitted_at=timezone.now(),
        start_date=max(start_date or timezone.localdate(), timezone.localdate()),
        end_date=end_date,
        created_by=user,
    )
    ad = Ad.objects.create(
        owner=user,
        campaign=campaign,
        title=title,
        ad_type=ad_type,
        media_file=media,
        target_url=target_url or None,
        status="PENDING",
        created_by=user,
    )
    CampaignPlan.objects.create(
        campaign=campaign, total_budget=total_budget,
        daily_budget=daily_budget, max_views=max_views,
    )
    for spot, rate, free, beneficiary, share in terms:
        placement = Placement.objects.create(
            ad=ad, asset=spot.asset, requested_by=user, status="PENDING",
            serving_enabled=False,
        )
        PlacementTerms.objects.create(
            placement=placement, rate_per_view=rate, free_own_spot=free,
            beneficiary=beneficiary, owner_share_percent=share,
        )
    return campaign


@transaction.atomic
def approve_submission(campaign, manager, remarks=""):
    manager_service.approve_campaign(campaign, manager, remarks)
    for ad in campaign.ads.all():
        manager_service.approve_ad(ad, manager, remarks)
        for placement in ad.placements.filter(status="PENDING"):
            manager_service.approve_placement(placement, manager, remarks)


@transaction.atomic
def reject_submission(campaign, manager, remarks):
    manager_service.reject_campaign(campaign, manager, remarks)
    for ad in campaign.ads.all():
        manager_service.reject_ad(ad, manager, remarks)
        for placement in ad.placements.filter(status="PENDING"):
            manager_service.reject_placement(placement, manager, remarks)


# ------------------------------------------------------------------ subscriptions


@transaction.atomic
def subscribe(user, plan):
    """Pay for 30 days of *plan* from the wallet."""
    if not plan.is_active:
        raise MarketplaceError("This plan is not available.")
    wallet, _ = Wallet.objects.select_for_update().get_or_create(user=user)
    price = plan.monthly_price
    if wallet.balance < price:
        raise MarketplaceError(
            f"Your wallet balance (₹{wallet.balance}) is below the plan price (₹{price}). "
            "Add funds first."
        )
    if price:
        wallet.balance -= price
        wallet.save(update_fields=["balance", "updated_at"])
        WalletTransaction.objects.create(
            wallet=wallet, transaction_type="DEBIT", amount=price,
            description=f"Subscription: {plan.name} (30 days)", created_by=user,
            reference_id=f"sub-{uuid.uuid4().hex[:12]}",
        )
    now = timezone.now()
    sub = UserSubscription.objects.select_for_update().filter(user=user).first()
    if sub and sub.plan_id == plan.pk and sub.is_valid_subscription() and sub.end_date:
        sub.end_date = sub.end_date + timedelta(days=30)
    elif sub:
        sub.plan, sub.start_date, sub.end_date = plan, now, now + timedelta(days=30)
    else:
        sub = UserSubscription(user=user, plan=plan, start_date=now, end_date=now + timedelta(days=30))
    sub.status, sub.is_active = "ACTIVE", True
    sub.save()
    return sub


@transaction.atomic
def credit_wallet(user, amount, by, reference=""):
    if amount <= 0:
        raise MarketplaceError("Enter an amount above zero.")
    wallet, _ = Wallet.objects.select_for_update().get_or_create(user=user)
    wallet.balance += amount
    wallet.save(update_fields=["balance", "updated_at"])
    WalletTransaction.objects.create(
        wallet=wallet, transaction_type="CREDIT", amount=amount,
        description="Funds added by WiadSpot", reference_id=reference[:100] or None,
        created_by=by,
    )
    return wallet


# ------------------------------------------------------------------ owner earnings


def owner_account(user):
    account, _ = OwnerAccount.objects.get_or_create(user=user)
    return account


def credit_owner_earning(event, amount):
    """Credit the spot owner's share of a billed view. Idempotent per event."""
    from .models import EarningEntry

    terms = rules.terms_of(event.placement)
    if not terms or not terms.beneficiary_id or not terms.owner_share_percent or amount <= 0:
        return None
    share = (amount * terms.owner_share_percent / Decimal("100")).quantize(Decimal("0.0001"))
    if share <= 0:
        return None
    with transaction.atomic():
        account = OwnerAccount.objects.select_for_update().get_or_create(user=terms.beneficiary)[0]
        entry, created = EarningEntry.objects.get_or_create(
            event=event,
            defaults={"owner": terms.beneficiary, "asset": event.asset, "amount": share},
        )
        if created:
            account.balance += share
            account.save(update_fields=["balance"])
    return entry if created else None


@transaction.atomic
def request_withdrawal(user, amount, payout_details):
    conf = MarketplaceSettings.load()
    amount = Decimal(amount).quantize(CENT)
    if amount < conf.min_withdrawal:
        raise MarketplaceError(f"The minimum withdrawal is ₹{conf.min_withdrawal}.")
    if not payout_details.strip():
        raise MarketplaceError("Enter where the money should be sent.")
    account = OwnerAccount.objects.select_for_update().get_or_create(user=user)[0]
    if amount > account.balance:
        raise MarketplaceError("You can't withdraw more than your available balance.")
    account.balance -= amount
    account.save(update_fields=["balance"])
    return Withdrawal.objects.create(owner=user, amount=amount, payout_details=payout_details.strip())


@transaction.atomic
def process_withdrawal(withdrawal_id, admin, paid, note=""):
    withdrawal = Withdrawal.objects.select_for_update().get(pk=withdrawal_id)
    if withdrawal.status != "REQUESTED":
        raise MarketplaceError("This withdrawal was already processed.")
    withdrawal.status = "PAID" if paid else "REJECTED"
    withdrawal.processed_by, withdrawal.processed_at, withdrawal.note = admin, timezone.now(), note[:255]
    withdrawal.save()
    if not paid:
        account = OwnerAccount.objects.select_for_update().get_or_create(user=withdrawal.owner)[0]
        account.balance += withdrawal.amount
        account.save(update_fields=["balance"])
    return withdrawal


def earnings_summary(user):
    from .models import EarningEntry

    total = EarningEntry.objects.filter(owner=user).aggregate(t=Sum("amount"))["t"] or Decimal("0")
    return {
        "available": owner_account(user).balance,
        "lifetime": total,
        "paid_out": Withdrawal.objects.filter(owner=user, status="PAID").aggregate(t=Sum("amount"))["t"] or Decimal("0"),
        "pending": Withdrawal.objects.filter(owner=user, status="REQUESTED").aggregate(t=Sum("amount"))["t"] or Decimal("0"),
    }


# ----------------------------------------------------------------- location flows


@transaction.atomic
def request_listing(user, asset, town):
    if asset.owner_type != "PARTNER" or asset.partner_id != user.pk:
        raise MarketplaceError("You can only list a location you own.")
    spot = asset.spot
    if spot.mode != SpotProfile.MODE_PRIVATE:
        raise MarketplaceError("This location is already listed.")
    if LocationRequest.objects.filter(asset=asset, status__in=LocationRequest.OPEN_STATUSES).exists():
        raise MarketplaceError("A request for this location is already waiting for review.")
    return LocationRequest.objects.create(
        user=user, kind=LocationRequest.KIND_LIST, asset=asset, name=asset.name, town=town,
        address=asset.address or "",
    )


def _unique_code(prefix):
    while True:
        code = f"{prefix}-{uuid.uuid4().hex[:8]}"
        if not Asset.objects.filter(code=code).exists():
            return code


@transaction.atomic
def review_location_request(req, manager, action, note=""):
    """Manager actions: approve, reject, start_install, complete."""
    req = LocationRequest.objects.select_for_update().get(pk=req.pk)
    if req.status not in LocationRequest.OPEN_STATUSES:
        raise MarketplaceError("This request is already closed.")
    kind = req.kind
    if action == "reject":
        req.status = "REJECTED"
    elif action == "approve" and req.status == "PENDING":
        req.status = "APPROVED"
        if kind == LocationRequest.KIND_LIST:
            _finish_listing(req)
    elif action == "start_install" and kind == LocationRequest.KIND_INSTALL and req.status == "APPROVED":
        req.status = "INSTALLING"
    elif action == "complete" and kind == LocationRequest.KIND_INSTALL and req.status in ("APPROVED", "INSTALLING"):
        asset = Asset.objects.create(
            name=req.name, code=_unique_code("spot"), owner_type="PARTNER", partner=req.user,
            location=req.town.name, address=req.address, allow_manager_approval=True,
        )
        SpotProfile.objects.filter(asset=asset).update(town=req.town)
        req.asset = asset
        req.status = "COMPLETED"
    else:
        raise MarketplaceError("That action is not available for this request.")
    req.reviewed_by, req.reviewed_at, req.review_note = manager, timezone.now(), note
    req.save()
    return req


def _finish_listing(req):
    """An approved listing becomes bookable at the owner-listed rate."""
    spot = req.asset.spot
    spot.mode, spot.town = SpotProfile.MODE_LISTED, req.town
    spot.save(update_fields=["mode", "town"])
    Asset.objects.filter(pk=req.asset_id).update(allow_manager_approval=True)
    req.status = "COMPLETED"


def issue_device_token(asset):
    """Create or rotate the spot's device credential. The token is shown once."""
    return SpotDevice.issue(asset)

