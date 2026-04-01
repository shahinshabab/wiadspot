from decimal import Decimal
from django.db.models import Q
from django.utils import timezone

from ads.models import (
    Asset,
    Placement,
    Wallet,
    UserSubscription,
    MetricPricing,
    AdServeSession,
    AdEventLog,
)


class AdServeError(Exception):
    pass


def _user_in_group(user, group_name):
    return user and user.groups.filter(name=group_name).exists()


def get_active_metric_pricing():
    pricing = MetricPricing.objects.filter(is_active=True).order_by("-created_at").first()
    if not pricing:
        raise AdServeError("No active metric pricing configured.")
    return pricing


def get_asset_by_code(asset_code):
    asset = Asset.objects.filter(
        code=asset_code,
        is_available_for_booking=True,
        status="ACTIVE",
    ).select_related("partner", "admin", "device_config").first()

    if not asset:
        raise AdServeError("Asset not found or not available.")
    return asset


def user_requires_subscription(user):
    if _user_in_group(user, "Admin"):
        return False
    return _user_in_group(user, "Client") or _user_in_group(user, "Partner")


def has_valid_subscription(user):
    if not user_requires_subscription(user):
        return True

    subscription = UserSubscription.objects.filter(
        user=user,
        is_active=True,
        status="ACTIVE",
    ).select_related("plan").first()

    if not subscription:
        return False

    return subscription.is_valid_subscription()


def get_wallet(user):
    return Wallet.objects.filter(user=user, is_active=True).first()


def has_credit_balance(user):
    wallet = get_wallet(user)
    return bool(wallet and wallet.balance > 0)


def is_campaign_live(campaign):
    today = timezone.localdate()

    if not campaign.is_active:
        return False
    if campaign.status not in ["ACTIVE"]:
        return False
    if campaign.start_date and campaign.start_date > today:
        return False
    if campaign.end_date and campaign.end_date < today:
        return False
    return True


def is_ad_live(ad):
    return ad.is_active and ad.status in ["APPROVED", "RUNNING"]


def is_placement_live(placement):
    now = timezone.now()

    if not placement.is_active:
        return False
    if not placement.serving_enabled:
        return False
    if placement.status not in ["APPROVED", "RUNNING"]:
        return False

    if placement.scheduled_start and placement.scheduled_start > now:
        return False
    if placement.scheduled_end and placement.scheduled_end < now:
        return False

    return True


def owner_can_pay(owner):
    if user_requires_subscription(owner):
        if not has_valid_subscription(owner):
            return False
    return has_credit_balance(owner) or _user_in_group(owner, "Admin")


def check_asset_permission_for_placement(asset, placement):
    approver = placement.approved_by

    if asset.owner_type == "PARTNER":
        # partner-owned asset: usually partner or admin may approve
        if not approver:
            return False

        if asset.partner and approver == asset.partner:
            return True
        if asset.allow_admin_approval and _user_in_group(approver, "Admin"):
            return True

        return False

    if asset.owner_type == "ADMIN":
        if not approver:
            return False

        if asset.admin and approver == asset.admin:
            return True
        if asset.allow_admin_approval and _user_in_group(approver, "Admin"):
            return True
        if asset.allow_manager_approval and _user_in_group(approver, "Manager"):
            return True

        return False

    return False


def placement_has_remaining_capacity(placement):
    if placement.max_impressions > 0:
        impression_count = placement.event_logs.filter(event_type="IMPRESSION").count()
        if impression_count >= placement.max_impressions:
            return False

    if placement.max_clicks > 0:
        click_count = placement.event_logs.filter(event_type="CLICK").count()
        if click_count >= placement.max_clicks:
            return False

    return True


def calculate_effective_score(placement, pricing):
    """
    Simple MVP bid strategy:
    - FIXED: priority + weight + campaign impression bid
    - LOWEST_COST: prioritize lower price-sensitive campaigns but still honor priority

    You can improve this later.
    """
    campaign = placement.ad.campaign
    base_priority = Decimal(str(placement.priority))
    weight_bonus = Decimal(str(placement.weight)) / Decimal("100")

    if campaign.bid_strategy == "FIXED":
        return base_priority + weight_bonus + campaign.max_bid_per_impression

    if campaign.bid_strategy == "LOWEST_COST":
        return base_priority + weight_bonus + Decimal("0.001")

    return base_priority + weight_bonus


def get_eligible_placements_for_asset(asset):
    placements = (
        Placement.objects
        .filter(
            asset=asset,
            is_active=True,
            serving_enabled=True,
        )
        .select_related(
            "asset",
            "approved_by",
            "ad",
            "ad__owner",
            "ad__campaign",
            "ad__campaign__owner",
        )
    )

    eligible = []

    for placement in placements:
        campaign = placement.ad.campaign
        ad = placement.ad
        owner = ad.owner

        if not is_campaign_live(campaign):
            continue
        if not is_ad_live(ad):
            continue
        if not is_placement_live(placement):
            continue
        if not check_asset_permission_for_placement(asset, placement):
            continue
        if not owner_can_pay(owner):
            continue
        if not placement_has_remaining_capacity(placement):
            continue

        eligible.append(placement)

    return eligible

def get_serve_session_or_none(session_id):
    return (
        AdServeSession.objects
        .select_related("asset", "placement", "ad", "ad__campaign")
        .filter(session_id=session_id)
        .first()
    )

def safe_media_url(ad):
    try:
        return ad.media_file.url if ad.media_file else None
    except Exception:
        return None
    
def choose_best_placement(asset):
    pricing = get_active_metric_pricing()
    eligible = get_eligible_placements_for_asset(asset)

    if not eligible:
        return None

    ranked = sorted(
        eligible,
        key=lambda p: calculate_effective_score(p, pricing),
        reverse=True
    )
    return ranked[0]


def create_serve_session(asset, placement, visitor_token=None, client_ip=None, user_agent=None, request_meta=None):
    session = AdServeSession.objects.create(
        asset=asset,
        placement=placement,
        ad=placement.ad,
        visitor_token=visitor_token,
        client_ip=client_ip,
        user_agent=user_agent,
        request_meta=request_meta or {},
    )
    return session


def log_raw_event(*, asset, placement, ad, campaign, event_type, serve_session=None, metadata=None):
    pricing = get_active_metric_pricing()

    if event_type == "IMPRESSION":
        amount = pricing.cost_per_impression
        if campaign.max_bid_per_impression and amount > campaign.max_bid_per_impression:
            amount = campaign.max_bid_per_impression

    elif event_type == "CLICK":
        amount = pricing.cost_per_click
        if campaign.max_bid_per_click and amount > campaign.max_bid_per_click:
            amount = campaign.max_bid_per_click

    elif event_type == "VIEW":
        amount = pricing.cost_per_view
        if campaign.max_bid_per_view and amount > campaign.max_bid_per_view:
            amount = campaign.max_bid_per_view

    elif event_type == "ENGAGEMENT":
        amount = pricing.cost_per_engagement
    else:
        amount = Decimal("0.0000")

    return AdEventLog.objects.create(
        asset=asset,
        placement=placement,
        ad=ad,
        campaign=campaign,
        serve_session=serve_session,
        event_type=event_type,
        billable_amount=amount,
        metadata=metadata or {},
    )


def build_ad_response_payload(placement, serve_session):
    ad = placement.ad
    return {
        "serve_session_id": str(serve_session.session_id),
        "ad_id": ad.id,
        "campaign_id": ad.campaign.id,
        "title": ad.title,
        "description": ad.description,
        "ad_type": ad.ad_type,
        "media_url": safe_media_url(ad),
        "target_url": ad.target_url,
        "call_to_action": ad.call_to_action,
        "asset_code": placement.asset.code,
    }


def serve_ad_for_asset(asset_code, visitor_token=None, client_ip=None, user_agent=None, request_meta=None):
    asset = get_asset_by_code(asset_code)
    placement = choose_best_placement(asset)

    if not placement:
        raise AdServeError("No eligible ads available for this asset.")

    serve_session = create_serve_session(
        asset=asset,
        placement=placement,
        visitor_token=visitor_token,
        client_ip=client_ip,
        user_agent=user_agent,
        request_meta=request_meta,
    )

    log_raw_event(
        asset=asset,
        placement=placement,
        ad=placement.ad,
        campaign=placement.ad.campaign,
        event_type="IMPRESSION",
        serve_session=serve_session,
        metadata=request_meta or {},
    )

    placement.last_served_at = timezone.now()
    placement.save(update_fields=["last_served_at"])

    campaign = placement.ad.campaign
    campaign.last_served_at = timezone.now()
    campaign.save(update_fields=["last_served_at"])

    return build_ad_response_payload(placement, serve_session)


def log_click_for_session(session_id, metadata=None):
    serve_session = (
        AdServeSession.objects
        .select_related("asset", "placement", "ad", "ad__campaign")
        .filter(session_id=session_id)
        .first()
    )

    if not serve_session:
        raise AdServeError("Serve session not found.")

    serve_session.clicked_at = timezone.now()
    serve_session.save(update_fields=["clicked_at"])

    event = log_raw_event(
        asset=serve_session.asset,
        placement=serve_session.placement,
        ad=serve_session.ad,
        campaign=serve_session.ad.campaign,
        event_type="CLICK",
        serve_session=serve_session,
        metadata=metadata or {},
    )

    return {
        "target_url": serve_session.ad.target_url,
        "event_id": str(event.event_uuid),
    }


def log_view_for_session(session_id, metadata=None):
    serve_session = (
        AdServeSession.objects
        .select_related("asset", "placement", "ad", "ad__campaign")
        .filter(session_id=session_id)
        .first()
    )

    if not serve_session:
        raise AdServeError("Serve session not found.")

    event = log_raw_event(
        asset=serve_session.asset,
        placement=serve_session.placement,
        ad=serve_session.ad,
        campaign=serve_session.ad.campaign,
        event_type="VIEW",
        serve_session=serve_session,
        metadata=metadata or {},
    )

    return {"event_id": str(event.event_uuid)}


def log_engagement_for_session(session_id, metadata=None):
    serve_session = (
        AdServeSession.objects
        .select_related("asset", "placement", "ad", "ad__campaign")
        .filter(session_id=session_id)
        .first()
    )

    if not serve_session:
        raise AdServeError("Serve session not found.")

    event = log_raw_event(
        asset=serve_session.asset,
        placement=serve_session.placement,
        ad=serve_session.ad,
        campaign=serve_session.ad.campaign,
        event_type="ENGAGEMENT",
        serve_session=serve_session,
        metadata=metadata or {},
    )

    return {"event_id": str(event.event_uuid)}