"""Serving and pricing rules the ad runtime consults."""

import random
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.utils import timezone

from .models import MarketplaceSettings, SpotProfile

BILLABLE_STATES = ("PENDING", "BILLED")


def terms_of(placement):
    """The booking terms of a placement, or None for legacy placements."""
    return getattr(placement, "terms", None)


def spots_for_booking(user, role):
    """Spots a signed-in advertiser may book.

    Advertisers see WiadSpot-hosted spots and owner-listed spots. Location
    owners see the hosted spots plus every spot they own.
    """
    spots = SpotProfile.objects.select_related("asset", "town").filter(
        asset__status="ACTIVE", asset__is_available_for_booking=True
    )
    if role == "owner":
        own = Q(asset__partner=user, asset__owner_type="PARTNER")
        return spots.filter(Q(mode=SpotProfile.MODE_COMPANY) | own)
    return spots.filter(mode__in=(SpotProfile.MODE_COMPANY, SpotProfile.MODE_LISTED))


def booking_terms(user, spot, conf=None):
    """(rate, free_own_spot, beneficiary, share_percent) for booking *spot* as *user*."""
    conf = conf or MarketplaceSettings.load()
    asset = spot.asset
    if asset.owner_type == "PARTNER" and asset.partner_id == user.pk:
        return Decimal("0"), True, None, Decimal("0")
    if spot.mode == SpotProfile.MODE_LISTED and asset.partner_id:
        return spot.rate_per_view, False, asset.partner, conf.owner_share_percent
    return spot.rate_per_view, False, None, Decimal("0")


def impression_amount(placement):
    """Charge for one view, or None to fall back to the legacy global pricing."""
    terms = terms_of(placement)
    if terms is None:
        return None
    return Decimal("0") if terms.free_own_spot else terms.rate_per_view


def placement_allowed(placement):
    """Extra serving checks for marketplace placements; legacy ones pass."""
    terms = terms_of(placement)
    if terms is None:
        return True
    spot = getattr(placement.asset, "spot", None)
    if spot is None:
        return False
    if not terms.free_own_spot and not spot.is_bookable_by_others:
        return False
    return placement_within_limits(placement)


def placement_within_limits(placement):
    from ads.models import AdEventLog

    campaign = placement.ad.campaign
    plan = getattr(campaign, "plan", None)
    if plan is None:
        return True
    day_start = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
    totals = AdEventLog.objects.filter(
        campaign=campaign, event_type="IMPRESSION", billing_status__in=BILLABLE_STATES
    ).aggregate(
        views=Count("id"),
        spent=Sum("billable_amount"),
        today=Sum("billable_amount", filter=Q(event_time__gte=day_start)),
    )
    spent = totals["spent"] or Decimal("0")
    today = totals["today"] or Decimal("0")
    if plan.max_views and totals["views"] >= plan.max_views:
        return False
    if plan.total_budget and spent >= plan.total_budget:
        return False
    if plan.daily_budget and today >= plan.daily_budget:
        return False
    return True


def rank_placements(eligible, score):
    """Order eligible placements by the pool strategy chosen in admin settings."""
    strategy = MarketplaceSettings.load().pool_strategy
    if strategy == MarketplaceSettings.POOL_HIGHEST:
        return sorted(eligible, key=score, reverse=True)
    if strategy == MarketplaceSettings.POOL_WEIGHTED:
        weights = [max(1, p.weight) * max(1, p.priority) for p in eligible]
        first = random.choices(eligible, weights=weights, k=1)[0]
        return [first] + [p for p in eligible if p is not first]
    epoch = datetime(1970, 1, 1, tzinfo=dt_timezone.utc)
    return sorted(eligible, key=lambda p: (p.last_served_at or epoch, -score(p)))


def impression_is_billable(asset, ad, visitor_token, request_meta):
    """(billable, reason). Unauthenticated or repeated views are served but not billed."""
    from ads.models import AdEventLog

    conf = MarketplaceSettings.load()
    if conf.require_authentic_device and not (request_meta or {}).get("fas"):
        return False, "Not billed: request did not carry the spot's gateway payload."
    if visitor_token and conf.repeat_view_window_minutes:
        since = timezone.now() - timedelta(minutes=conf.repeat_view_window_minutes)
        if AdEventLog.objects.filter(
            asset=asset,
            ad=ad,
            event_type="IMPRESSION",
            event_time__gte=since,
            billing_status__in=BILLABLE_STATES,
            serve_session__visitor_token=visitor_token,
        ).exists():
            return False, "Not billed: repeat view inside the repeat-view window."
    return True, ""
