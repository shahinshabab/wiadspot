from decimal import Decimal
from django.db import models, transaction
from django.db.models import Sum, Count
from django.utils import timezone
from ads.models import (
    Campaign,
    Placement,
    Wallet,
    WalletTransaction,
    AdMetrics,
    AdEventLog,
    BillingRunLog,
)


# =========================================================
# CAMPAIGN STATUS SYNC
# =========================================================

def sync_campaign_statuses():
    today = timezone.localdate()

    # Activate campaigns whose time has started
    Campaign.objects.filter(
        is_active=True,
        status="DRAFT",
        start_date__isnull=False,
        start_date__lte=today
    ).update(status="ACTIVE")

    # Stop expired campaigns
    Campaign.objects.filter(
        is_active=True,
        status__in=["ACTIVE", "PAUSED"],
        end_date__isnull=False,
        end_date__lt=today
    ).update(status="COMPLETED")

    # Stop campaigns that exceeded budget
    over_budget_campaigns = Campaign.objects.filter(
        is_active=True,
        status="ACTIVE",
        daily_budget__gt=0,
        total_spend__gte=models.F("daily_budget"),
    )
    over_budget_campaigns.update(status="PAUSED")


# =========================================================
# PLACEMENT STATUS SYNC
# =========================================================

def sync_placement_statuses():
    now = timezone.now()

    Placement.objects.filter(
        is_active=True,
        serving_enabled=True,
        status="APPROVED",
        scheduled_start__isnull=False,
        scheduled_start__lte=now
    ).update(status="RUNNING")

    Placement.objects.filter(
        is_active=True,
        status__in=["APPROVED", "RUNNING", "PAUSED"],
        scheduled_end__isnull=False,
        scheduled_end__lt=now
    ).update(status="STOPPED")


# =========================================================
# BILL RAW EVENTS
# =========================================================

def bill_pending_events(batch_size=1000):
    run = BillingRunLog.objects.create(run_type="BILLING", status="STARTED")

    processed = 0
    total_billed = Decimal("0.00")

    pending_events = (
        AdEventLog.objects
        .filter(billing_status="PENDING")
        .select_related("ad", "campaign", "placement", "asset", "ad__owner")
        .order_by("id")[:batch_size]
    )

    for event in pending_events:
        owner = event.ad.owner

        # admin ads can be skipped if you don't want to bill them
        if owner.groups.filter(name="Admin").exists():
            event.billing_status = "SKIPPED"
            event.billed_at = timezone.now()
            event.notes = (event.notes or "") + " | Admin-owned ad, billing skipped."
            event.save(update_fields=["billing_status", "billed_at", "notes"])
            processed += 1
            continue

        wallet = Wallet.objects.filter(user=owner, is_active=True).first()
        if not wallet:
            event.billing_status = "FAILED"
            event.notes = (event.notes or "") + " | Wallet not found."
            event.save(update_fields=["billing_status", "notes"])
            processed += 1
            continue

        amount = event.billable_amount or Decimal("0.0000")

        # If insufficient balance, mark failed and later pause campaign/placements
        if wallet.balance < amount:
            event.billing_status = "FAILED"
            event.notes = (event.notes or "") + " | Insufficient wallet balance."
            event.save(update_fields=["billing_status", "notes"])
            processed += 1
            continue

        with transaction.atomic():
            wallet.balance = wallet.balance - amount
            wallet.save(update_fields=["balance", "updated_at"])

            WalletTransaction.objects.create(
                wallet=wallet,
                transaction_type="DEBIT",
                amount=amount,
                description=f"{event.event_type} charge for ad '{event.ad.title}'",
                created_by=None,
                ad_event=event,
                campaign=event.campaign,
                ad=event.ad,
            )

            # update campaign and placement spend
            event.campaign.total_spend = (event.campaign.total_spend or Decimal("0.00")) + amount
            event.campaign.save(update_fields=["total_spend", "updated_at"])

            event.placement.total_spend = (event.placement.total_spend or Decimal("0.00")) + amount
            event.placement.save(update_fields=["total_spend", "updated_at"])

            event.billing_status = "BILLED"
            event.billed_at = timezone.now()
            event.save(update_fields=["billing_status", "billed_at"])

        total_billed += amount
        processed += 1

    run.total_events_processed = processed
    run.total_amount_billed = total_billed
    run.completed_at = timezone.now()
    run.status = "COMPLETED"
    run.save(update_fields=[
        "total_events_processed",
        "total_amount_billed",
        "completed_at",
        "status",
    ])

    return {
        "processed": processed,
        "total_billed": total_billed,
    }


# =========================================================
# AGGREGATE RAW EVENTS INTO ADMTRICS
# =========================================================

def aggregate_pending_events(batch_limit=5000):
    run = BillingRunLog.objects.create(run_type="AGGREGATION", status="STARTED")

    events = (
        AdEventLog.objects
        .filter(aggregation_status="PENDING")
        .select_related("ad", "placement")
        .order_by("id")[:batch_limit]
    )

    if not events:
        run.completed_at = timezone.now()
        run.status = "COMPLETED"
        run.save(update_fields=["completed_at", "status"])
        return {"processed": 0}

    grouped = {}
    event_ids = []

    for event in events:
        event_date = timezone.localtime(event.event_time).date()
        key = (event.ad_id, event.placement_id, event_date)

        if key not in grouped:
            grouped[key] = {
                "impressions": 0,
                "clicks": 0,
                "views": 0,
                "engagement": 0,
                "spend": Decimal("0.00"),
            }

        if event.event_type == "IMPRESSION":
            grouped[key]["impressions"] += 1
        elif event.event_type == "CLICK":
            grouped[key]["clicks"] += 1
        elif event.event_type == "VIEW":
            grouped[key]["views"] += 1
        elif event.event_type == "ENGAGEMENT":
            grouped[key]["engagement"] += 1

        if event.billing_status == "BILLED":
            grouped[key]["spend"] += event.billable_amount

        event_ids.append(event.id)

    with transaction.atomic():
        for (ad_id, placement_id, metric_date), values in grouped.items():
            metrics_obj, created = AdMetrics.objects.get_or_create(
                ad_id=ad_id,
                placement_id=placement_id,
                date=metric_date,
                defaults={
                    "impressions": 0,
                    "clicks": 0,
                    "views": 0,
                    "engagement": 0,
                    "spend": Decimal("0.00"),
                }
            )

            metrics_obj.impressions += values["impressions"]
            metrics_obj.clicks += values["clicks"]
            metrics_obj.views += values["views"]
            metrics_obj.engagement += values["engagement"]
            metrics_obj.spend += values["spend"]
            metrics_obj.save()

        AdEventLog.objects.filter(id__in=event_ids).update(
            aggregation_status="AGGREGATED",
            aggregated_at=timezone.now(),
        )

    run.total_events_processed = len(event_ids)
    run.completed_at = timezone.now()
    run.status = "COMPLETED"
    run.save(update_fields=["total_events_processed", "completed_at", "status"])

    return {"processed": len(event_ids)}


# =========================================================
# PAUSE ADS / PLACEMENTS WHEN WALLET IS EMPTY
# =========================================================

def pause_entities_with_insufficient_balance():
    wallets = Wallet.objects.filter(is_active=True).select_related("user")

    paused_campaign_ids = set()
    paused_placement_ids = set()

    for wallet in wallets:
        owner = wallet.user

        # admin can continue without prepaid wallet restriction
        if owner.groups.filter(name="Admin").exists():
            continue

        if wallet.balance > 0:
            continue

        campaigns = Campaign.objects.filter(owner=owner, status="ACTIVE", is_active=True)
        placements = Placement.objects.filter(
            ad__owner=owner,
            status__in=["APPROVED", "RUNNING"],
            is_active=True,
            serving_enabled=True,
        )

        for campaign in campaigns:
            campaign.status = "PAUSED"
            campaign.save(update_fields=["status", "updated_at"])
            paused_campaign_ids.add(campaign.id)

        for placement in placements:
            placement.status = "PAUSED"
            placement.serving_enabled = False
            placement.save(update_fields=["status", "serving_enabled", "updated_at"])
            paused_placement_ids.add(placement.id)

    return {
        "paused_campaigns": len(paused_campaign_ids),
        "paused_placements": len(paused_placement_ids),
    }


# =========================================================
# RESUME ADS / PLACEMENTS WHEN WALLET IS RECHARGED
# =========================================================

def resume_entities_with_balance():
    wallets = Wallet.objects.filter(is_active=True, balance__gt=0).select_related("user")

    resumed_campaign_ids = set()
    resumed_placement_ids = set()

    for wallet in wallets:
        owner = wallet.user

        if owner.groups.filter(name="Admin").exists():
            continue

        campaigns = Campaign.objects.filter(owner=owner, status="PAUSED", is_active=True)
        placements = Placement.objects.filter(
            ad__owner=owner,
            status="PAUSED",
            is_active=True,
            serving_enabled=False,
        )

        for campaign in campaigns:
            today = timezone.localdate()
            if campaign.start_date and campaign.start_date > today:
                continue
            if campaign.end_date and campaign.end_date < today:
                continue

            campaign.status = "ACTIVE"
            campaign.save(update_fields=["status", "updated_at"])
            resumed_campaign_ids.add(campaign.id)

        for placement in placements:
            now = timezone.now()
            if placement.scheduled_start and placement.scheduled_start > now:
                continue
            if placement.scheduled_end and placement.scheduled_end < now:
                continue

            placement.status = "APPROVED"
            placement.serving_enabled = True
            placement.save(update_fields=["status", "serving_enabled", "updated_at"])
            resumed_placement_ids.add(placement.id)

    return {
        "resumed_campaigns": len(resumed_campaign_ids),
        "resumed_placements": len(resumed_placement_ids),
    }


# =========================================================
# MASTER TASK RUNNER
# =========================================================

def run_ad_runtime_cycle():
    """
    Recommended periodic order:
    1. sync campaign statuses
    2. sync placement statuses
    3. bill raw events
    4. aggregate events
    5. pause zero-balance entities
    6. resume recharged entities
    """
    sync_campaign_statuses()
    sync_placement_statuses()
    billing_result = bill_pending_events()
    aggregation_result = aggregate_pending_events()
    pause_result = pause_entities_with_insufficient_balance()
    resume_result = resume_entities_with_balance()

    return {
        "billing": billing_result,
        "aggregation": aggregation_result,
        "pause": pause_result,
        "resume": resume_result,
    }