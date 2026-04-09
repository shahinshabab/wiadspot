from django.db import transaction
from django.db.models import Count, Sum, Q
from django.utils import timezone

from ads.models import (
    Campaign,
    Ad,
    Placement,
    AdMetrics,
    WalletTransaction,
    ManagerAuditLog,
)


def manager_dashboard_stats():
    today = timezone.localdate()

    return {
        "total_campaigns": Campaign.objects.count(),
        "active_campaigns": Campaign.objects.filter(status="ACTIVE", is_active=True).count(),
        "paused_campaigns": Campaign.objects.filter(status="PAUSED", is_active=True).count(),
        "pending_campaign_reviews": Campaign.objects.filter(review_status="PENDING").count(),
        "pending_ads": Ad.objects.filter(status="PENDING", is_active=True).count(),
        "pending_placements": Placement.objects.filter(status="PENDING", is_active=True).count(),
        "today_impressions": AdMetrics.objects.filter(date=today).aggregate(
            total=Sum("impressions")
        )["total"] or 0,
        "today_clicks": AdMetrics.objects.filter(date=today).aggregate(
            total=Sum("clicks")
        )["total"] or 0,
        "today_spend": AdMetrics.objects.filter(date=today).aggregate(
            total=Sum("spend")
        )["total"] or 0,
    }


@transaction.atomic
def approve_campaign(campaign, manager, remarks=""):
    campaign.review_status = "APPROVED"
    campaign.reviewed_by = manager
    campaign.reviewed_at = timezone.now()
    campaign.rejection_reason = ""
    if campaign.status == "DRAFT":
        campaign.status = "ACTIVE" if (campaign.start_date and campaign.start_date <= timezone.localdate()) else "DRAFT"
    campaign.save()

    ManagerAuditLog.objects.create(
        manager=manager,
        action="CAMPAIGN_APPROVED",
        campaign=campaign,
        remarks=remarks,
    )


@transaction.atomic
def reject_campaign(campaign, manager, remarks=""):
    campaign.review_status = "REJECTED"
    campaign.reviewed_by = manager
    campaign.reviewed_at = timezone.now()
    campaign.rejection_reason = remarks
    campaign.status = "STOPPED"
    campaign.save()

    ManagerAuditLog.objects.create(
        manager=manager,
        action="CAMPAIGN_REJECTED",
        campaign=campaign,
        remarks=remarks,
    )


@transaction.atomic
def approve_ad(ad, manager, remarks=""):
    ad.status = "APPROVED"
    ad.approved_by = manager
    ad.approved_at = timezone.now()
    ad.rejection_reason = ""
    ad.save()

    ManagerAuditLog.objects.create(
        manager=manager,
        action="AD_APPROVED",
        ad=ad,
        campaign=ad.campaign,
        remarks=remarks,
    )


@transaction.atomic
def reject_ad(ad, manager, remarks=""):
    ad.status = "REJECTED"
    ad.rejection_reason = remarks
    ad.approved_by = manager
    ad.approved_at = timezone.now()
    ad.save()

    ManagerAuditLog.objects.create(
        manager=manager,
        action="AD_REJECTED",
        ad=ad,
        campaign=ad.campaign,
        remarks=remarks,
    )


@transaction.atomic
def approve_placement(placement, manager, remarks=""):
    placement.status = "APPROVED"
    placement.approved_by = manager
    placement.approved_at = timezone.now()
    placement.rejected_by = None
    placement.rejected_at = None
    placement.rejection_reason = ""
    placement.serving_enabled = True
    placement.save()

    ManagerAuditLog.objects.create(
        manager=manager,
        action="PLACEMENT_APPROVED",
        placement=placement,
        ad=placement.ad,
        campaign=placement.ad.campaign,
        remarks=remarks,
    )


@transaction.atomic
def reject_placement(placement, manager, remarks=""):
    placement.status = "REJECTED"
    placement.rejected_by = manager
    placement.rejected_at = timezone.now()
    placement.rejection_reason = remarks
    placement.serving_enabled = False
    placement.save()

    ManagerAuditLog.objects.create(
        manager=manager,
        action="PLACEMENT_REJECTED",
        placement=placement,
        ad=placement.ad,
        campaign=placement.ad.campaign,
        remarks=remarks,
    )


@transaction.atomic
def pause_campaign(campaign, manager, remarks=""):
    campaign.status = "PAUSED"
    campaign.save(update_fields=["status", "updated_at"])

    campaign.ads.filter(status="RUNNING").update(status="PAUSED")
    Placement.objects.filter(ad__campaign=campaign, status__in=["APPROVED", "RUNNING"]).update(
        status="PAUSED",
        serving_enabled=False,
    )

    ManagerAuditLog.objects.create(
        manager=manager,
        action="CAMPAIGN_PAUSED",
        campaign=campaign,
        remarks=remarks,
    )


@transaction.atomic
def resume_campaign(campaign, manager, remarks=""):
    if campaign.review_status != "APPROVED":
        raise ValueError("Only approved campaigns can be resumed.")

    campaign.status = "ACTIVE"
    campaign.save(update_fields=["status", "updated_at"])

    Placement.objects.filter(ad__campaign=campaign, status="PAUSED", is_active=True).update(
        status="APPROVED",
        serving_enabled=True,
    )

    ManagerAuditLog.objects.create(
        manager=manager,
        action="CAMPAIGN_RESUMED",
        campaign=campaign,
        remarks=remarks,
    )