from django.db import models
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.utils import timezone
from decimal import Decimal
import uuid
import re
from django.contrib.auth import get_user_model


User = get_user_model()

_MAC_RE = re.compile(r"^([0-9A-F]{2}:){5}[0-9A-F]{2}$")

# =========================================================
# SUBSCRIPTION PLAN
# =========================================================

class SubscriptionPlan(models.Model):
    """
    Platform access plan.
    This controls limits like how many campaigns and ads a user can have.
    Billing for ad delivery itself is handled by Wallet / Credits.
    """

    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, null=True)

    max_campaigns = models.PositiveIntegerField(default=1)
    max_ads = models.PositiveIntegerField(default=5)

    monthly_price = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


# =========================================================
# USER SUBSCRIPTION
# =========================================================

class UserSubscription(models.Model):
    """
    Current subscription attached to a user.
    Use this for Client / Partner mainly.
    Admin can exist without plan if you want.
    """

    BILLING_STATUS_CHOICES = (
        ("ACTIVE", "Active"),
        ("EXPIRED", "Expired"),
        ("CANCELLED", "Cancelled"),
        ("SUSPENDED", "Suspended"),
    )

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="ads_subscription"
    )
    plan = models.ForeignKey(
        SubscriptionPlan,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="subscriptions"
    )

    status = models.CharField(max_length=20, choices=BILLING_STATUS_CHOICES, default="ACTIVE")

    start_date = models.DateTimeField(default=timezone.now)
    end_date = models.DateTimeField(null=True, blank=True)

    auto_renew = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        plan_name = self.plan.name if self.plan else "No Plan"
        return f"{self.user.username} - {plan_name}"

    def is_valid_subscription(self):
        if not self.is_active:
            return False
        if self.status != "ACTIVE":
            return False
        if self.end_date and self.end_date < timezone.now():
            return False
        return True


# =========================================================
# WALLET
# =========================================================

class Wallet(models.Model):
    """
    Prepaid credit wallet.
    Ad delivery charges are deducted from here.
    If balance reaches zero, ads should stop.
    """

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="ads_wallet"
    )
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["user__username"]

    def __str__(self):
        return f"{self.user.username} Wallet - {self.balance}"

    def has_sufficient_balance(self, amount):
        return self.balance >= amount


# =========================================================
# WALLET TRANSACTION
# =========================================================

class WalletTransaction(models.Model):
    """
    Every credit addition / debit / refund should be recorded here.
    """

    TRANSACTION_TYPE_CHOICES = (
        ("CREDIT", "Credit"),
        ("DEBIT", "Debit"),
        ("REFUND", "Refund"),
        ("ADJUSTMENT", "Adjustment"),
    )

    wallet = models.ForeignKey(
        Wallet,
        on_delete=models.CASCADE,
        related_name="transactions"
    )

    ad_event = models.ForeignKey(
        "AdEventLog",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="wallet_transactions"
    )

    campaign = models.ForeignKey(
        "Campaign",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="wallet_transactions"
    )

    ad = models.ForeignKey(
        "Ad",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="wallet_transactions"
    )

    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPE_CHOICES)

    amount = models.DecimalField(max_digits=12, decimal_places=2)
    description = models.TextField(blank=True, null=True)

    reference_id = models.CharField(max_length=100, blank=True, null=True)

    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="wallet_transactions_created"
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.wallet.user.username} - {self.transaction_type} - {self.amount}"




# =========================================================
# ASSET
# =========================================================

class Asset(models.Model):
    """
    Business-level asset model.
    Represents a real-world WiFi/captive portal asset owned by Partner or Admin.
    Technical configuration is stored in AssetDeviceConfig.
    """

    OWNER_TYPE_CHOICES = (
        ("PARTNER", "Partner"),
        ("ADMIN", "Admin"),
    )

    ASSET_TYPE_CHOICES = (
        ("ROUTER", "Router"),
        ("MODEM", "Modem"),
        ("HOTSPOT", "Hotspot Device"),
        ("CAPTIVE_PORTAL_NODE", "Captive Portal Node"),
        ("OTHER", "Other"),
    )

    STATUS_CHOICES = (
        ("ACTIVE", "Active"),
        ("INACTIVE", "Inactive"),
        ("MAINTENANCE", "Maintenance"),
    )

    name = models.CharField(max_length=255)
    code = models.CharField(max_length=100, unique=True)

    owner_type = models.CharField(max_length=20, choices=OWNER_TYPE_CHOICES)

    partner = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="owned_partner_assets"
    )
    admin = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="owned_admin_assets"
    )

    asset_type = models.CharField(max_length=30, choices=ASSET_TYPE_CHOICES, default="ROUTER")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="ACTIVE")

    location = models.CharField(max_length=255, blank=True, null=True)
    address = models.TextField(blank=True, null=True)

    is_available_for_booking = models.BooleanField(default=True)

    allow_partner_approval = models.BooleanField(default=True)
    allow_manager_approval = models.BooleanField(default=False)
    allow_admin_approval = models.BooleanField(default=True)

    notes = models.TextField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Asset"
        verbose_name_plural = "Assets"

    def __str__(self):
        return f"{self.name} ({self.owner_type})"

    def clean(self):
        if self.owner_type == "PARTNER":
            if not self.partner:
                raise ValidationError("Partner-owned asset must have a partner user.")
            if self.admin:
                raise ValidationError("Partner-owned asset cannot have admin set.")

        elif self.owner_type == "ADMIN":
            if not self.admin:
                raise ValidationError("Admin-owned asset must have an admin user.")
            if self.partner:
                raise ValidationError("Admin-owned asset cannot have partner set.")

    @property
    def actual_owner(self):
        return self.partner if self.owner_type == "PARTNER" else self.admin

# =========================================================
# ASSET DEVICE CONFIG
# =========================================================

# =========================================================
# ASSET DEVICE CONFIG
# =========================================================

class AssetDeviceConfig(models.Model):
    """
    Technical configuration for router/modem/captive portal asset.
    Keep technical device data separate from business asset data.
    """

    DEVICE_MODE_CHOICES = (
        ("ROUTER", "Router"),
        ("MODEM", "Modem"),
        ("ACCESS_POINT", "Access Point"),
        ("CAPTIVE_PORTAL", "Captive Portal"),
        ("HYBRID", "Hybrid"),
    )

    asset = models.OneToOneField(
        Asset,
        on_delete=models.CASCADE,
        related_name="device_config"
    )

    device_mode = models.CharField(max_length=30, choices=DEVICE_MODE_CHOICES, default="CAPTIVE_PORTAL")

    brand = models.CharField(max_length=100, blank=True, null=True)
    model_name = models.CharField(max_length=100, blank=True, null=True)
    firmware_version = models.CharField(max_length=100, blank=True, null=True)

    serial_number = models.CharField(max_length=100, blank=True, null=True, unique=True)
    mac_address = models.CharField(max_length=50, unique=True)
    ip_address = models.GenericIPAddressField(blank=True, null=True)

    ssid = models.CharField(max_length=100, blank=True, null=True)
    portal_url = models.URLField(blank=True, null=True)
    login_page_url = models.URLField(blank=True, null=True)
    callback_url = models.URLField(blank=True, null=True)

    router_username = models.CharField(max_length=100, blank=True, null=True)
    router_password = models.CharField(max_length=255, blank=True, null=True)

    last_seen_at = models.DateTimeField(blank=True, null=True)
    last_sync_at = models.DateTimeField(blank=True, null=True)

    is_online = models.BooleanField(default=False)
    config_json = models.JSONField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Asset Device Config"
        verbose_name_plural = "Asset Device Configs"

    def __str__(self):
        return f"{self.asset.name} Device Config"

# =========================================================
# CAMPAIGN
# =========================================================

class Campaign(models.Model):
    """
    A campaign groups multiple ads under one business goal.
    Example: Ramadan Sale / Summer Promotion / Launch Campaign
    """

    STATUS_CHOICES = (
        ("DRAFT", "Draft"),
        ("ACTIVE", "Active"),
        ("PAUSED", "Paused"),
        ("COMPLETED", "Completed"),
        ("STOPPED", "Stopped"),
    )

    owner = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="ad_campaigns"
    )
    BID_STRATEGY_CHOICES = (
        ("FIXED", "Fixed"),
        ("LOWEST_COST", "Lowest Cost"),
    )

    bid_strategy = models.CharField(max_length=20, choices=BID_STRATEGY_CHOICES, default="FIXED")
    max_bid_per_impression = models.DecimalField(max_digits=10, decimal_places=4, default=0.0000)
    max_bid_per_click = models.DecimalField(max_digits=10, decimal_places=4, default=0.0000)
    max_bid_per_view = models.DecimalField(max_digits=10, decimal_places=4, default=0.0000)

    daily_budget = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    total_spend = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)

    last_served_at = models.DateTimeField(null=True, blank=True)

    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="DRAFT")

    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)

    is_active = models.BooleanField(default=True)

    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="campaigns_created"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        unique_together = ("owner", "name")

    def __str__(self):
        return f"{self.name} - {self.owner.username}"

    def clean(self):
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValidationError("Campaign end date cannot be earlier than start date.")


# =========================================================
# AD
# =========================================================

class Ad(models.Model):
    """
    Actual ad unit inside a campaign.
    Can be image or video.
    """

    AD_TYPE_CHOICES = (
        ("IMAGE", "Image"),
        ("VIDEO", "Video"),
    )

    STATUS_CHOICES = (
        ("DRAFT", "Draft"),
        ("PENDING", "Pending Approval"),
        ("APPROVED", "Approved"),
        ("RUNNING", "Running"),
        ("PAUSED", "Paused"),
        ("STOPPED", "Stopped"),
        ("REJECTED", "Rejected"),
    )

    campaign = models.ForeignKey(
        Campaign,
        on_delete=models.CASCADE,
        related_name="ads"
    )
    owner = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="owned_ads"
    )

    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)

    ad_type = models.CharField(max_length=10, choices=AD_TYPE_CHOICES)

    media_file = models.FileField(upload_to="ads/media/")
    thumbnail = models.ImageField(upload_to="ads/thumbnails/", null=True, blank=True)

    aspect_ratio = models.CharField(max_length=20, blank=True, null=True)
    duration_seconds = models.PositiveIntegerField(null=True, blank=True)

    target_url = models.URLField(blank=True, null=True)
    call_to_action = models.CharField(max_length=100, blank=True, null=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="DRAFT")
    is_active = models.BooleanField(default=True)

    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ads_created"
    )

    approved_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ads_approved"
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    rejection_reason = models.TextField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.title} - {self.owner.username}"

    def clean(self):
        if self.campaign and self.owner and self.campaign.owner != self.owner:
            raise ValidationError("Ad owner must match campaign owner.")

        if self.ad_type == "VIDEO" and not self.duration_seconds:
            raise ValidationError("Video ad must have duration_seconds.")

        if self.ad_type == "IMAGE" and self.duration_seconds:
            raise ValidationError("Image ad should not have duration_seconds.")


# =========================================================
# PLACEMENT REQUEST
# =========================================================

class Placement(models.Model):
    """
    Connects an Ad to an Asset.
    This is the ad placement request / approval layer.
    """

    STATUS_CHOICES = (
        ("PENDING", "Pending"),
        ("APPROVED", "Approved"),
        ("REJECTED", "Rejected"),
        ("PAUSED", "Paused"),
        ("RUNNING", "Running"),
        ("STOPPED", "Stopped"),
    )

    ad = models.ForeignKey(
        Ad,
        on_delete=models.CASCADE,
        related_name="placements"
    )
    asset = models.ForeignKey(
        Asset,
        on_delete=models.CASCADE,
        related_name="placements"
    )

    requested_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="placement_requests_made"
    )

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="PENDING")

    scheduled_start = models.DateTimeField(null=True, blank=True)
    scheduled_end = models.DateTimeField(null=True, blank=True)

    approved_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="placement_requests_approved"
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    rejected_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="placement_requests_rejected"
    )
    rejected_at = models.DateTimeField(null=True, blank=True)

    rejection_reason = models.TextField(blank=True, null=True)
    notes = models.TextField(blank=True, null=True)

    priority = models.PositiveIntegerField(default=1)
    weight = models.PositiveIntegerField(default=1)

    max_impressions = models.PositiveIntegerField(default=0, help_text="0 means unlimited")
    max_clicks = models.PositiveIntegerField(default=0, help_text="0 means unlimited")
    total_spend = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)

    serving_enabled = models.BooleanField(default=True)
    last_served_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        unique_together = ("ad", "asset")

    def __str__(self):
        return f"{self.ad.title} -> {self.asset.name}"

    def clean(self):
        if self.scheduled_start and self.scheduled_end and self.scheduled_end < self.scheduled_start:
            raise ValidationError("Placement end time cannot be earlier than start time.")

        if self.asset and self.ad:
            supported = (self.asset.supported_ad_types or "").upper()
            if supported:
                allowed_types = [x.strip() for x in supported.split(",") if x.strip()]
                if self.ad.ad_type not in allowed_types:
                    raise ValidationError(
                        f"This asset supports only: {', '.join(allowed_types)}"
                    )

            if self.asset.supported_ratio and self.ad.aspect_ratio:
                if self.asset.supported_ratio != self.ad.aspect_ratio:
                    raise ValidationError(
                        f"Ad aspect ratio {self.ad.aspect_ratio} does not match asset supported ratio {self.asset.supported_ratio}."
                    )


# =========================================================
# METRIC PRICING
# =========================================================

class MetricPricing(models.Model):
    """
    Defines how much credit is charged for delivery metrics.
    You can keep one active pricing row globally at first.
    Later you can make this asset-specific or plan-specific.
    """

    name = models.CharField(max_length=100, unique=True)

    cost_per_impression = models.DecimalField(max_digits=10, decimal_places=4, default=0.0000)
    cost_per_click = models.DecimalField(max_digits=10, decimal_places=4, default=0.0000)
    cost_per_view = models.DecimalField(max_digits=10, decimal_places=4, default=0.0000)
    cost_per_engagement = models.DecimalField(max_digits=10, decimal_places=4, default=0.0000)

    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.name


# =========================================================
# AD METRICS
# =========================================================

class AdMetrics(models.Model):
    """
    Aggregated metrics for each ad.
    Keep this separate from Ad model for scalability.
    """

    ad = models.ForeignKey(
        Ad,
        on_delete=models.CASCADE,
        related_name="metrics"
    )
    placement = models.ForeignKey(
        Placement,
        on_delete=models.CASCADE,
        related_name="metrics",
        null=True,
        blank=True
    )

    date = models.DateField(default=timezone.now)

    impressions = models.PositiveIntegerField(default=0)
    clicks = models.PositiveIntegerField(default=0)
    views = models.PositiveIntegerField(default=0)
    engagement = models.PositiveIntegerField(default=0)

    spend = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-date", "-id"]
        unique_together = ("ad", "placement", "date")

    def __str__(self):
        return f"{self.ad.title} - {self.date}"

    @property
    def ctr(self):
        if self.impressions == 0:
            return 0
        return round((self.clicks / self.impressions) * 100, 2)

# =========================================================
# AD SERVE SESSION
# =========================================================

class AdServeSession(models.Model):
    """
    Tracks one captive portal / device session where an ad was served.
    Helps connect impression and click events.
    """

    session_id = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)

    asset = models.ForeignKey(
        Asset,
        on_delete=models.CASCADE,
        related_name="serve_sessions"
    )
    placement = models.ForeignKey(
        Placement,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="serve_sessions"
    )
    ad = models.ForeignKey(
        Ad,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="serve_sessions"
    )

    visitor_token = models.CharField(max_length=255, blank=True, null=True)
    client_ip = models.GenericIPAddressField(blank=True, null=True)
    user_agent = models.TextField(blank=True, null=True)
    request_meta = models.JSONField(blank=True, null=True)

    served_at = models.DateTimeField(auto_now_add=True)
    clicked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-served_at"]

    def __str__(self):
        return f"{self.asset.code} - {self.session_id}"
    
# =========================================================
# AD EVENT LOG
# =========================================================

class AdEventLog(models.Model):
    """
    Raw immutable event log.
    This is the source of truth for billing and metric aggregation.
    """

    EVENT_TYPE_CHOICES = (
        ("IMPRESSION", "Impression"),
        ("CLICK", "Click"),
        ("VIEW", "View"),
        ("ENGAGEMENT", "Engagement"),
    )

    BILLING_STATUS_CHOICES = (
        ("PENDING", "Pending"),
        ("BILLED", "Billed"),
        ("SKIPPED", "Skipped"),
        ("FAILED", "Failed"),
    )

    AGGREGATION_STATUS_CHOICES = (
        ("PENDING", "Pending"),
        ("AGGREGATED", "Aggregated"),
    )

    event_uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)

    asset = models.ForeignKey(
        Asset,
        on_delete=models.CASCADE,
        related_name="event_logs"
    )
    placement = models.ForeignKey(
        Placement,
        on_delete=models.CASCADE,
        related_name="event_logs"
    )
    ad = models.ForeignKey(
        Ad,
        on_delete=models.CASCADE,
        related_name="event_logs"
    )
    campaign = models.ForeignKey(
        Campaign,
        on_delete=models.CASCADE,
        related_name="event_logs"
    )
    serve_session = models.ForeignKey(
        AdServeSession,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="event_logs"
    )

    event_type = models.CharField(max_length=20, choices=EVENT_TYPE_CHOICES)
    event_time = models.DateTimeField(default=timezone.now)

    billable_amount = models.DecimalField(max_digits=12, decimal_places=4, default=Decimal("0.0000"))
    billing_status = models.CharField(max_length=20, choices=BILLING_STATUS_CHOICES, default="PENDING")
    billed_at = models.DateTimeField(null=True, blank=True)

    aggregation_status = models.CharField(max_length=20, choices=AGGREGATION_STATUS_CHOICES, default="PENDING")
    aggregated_at = models.DateTimeField(null=True, blank=True)

    metadata = models.JSONField(blank=True, null=True)
    notes = models.TextField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-event_time"]
        indexes = [
            models.Index(fields=["event_type", "billing_status"]),
            models.Index(fields=["event_type", "aggregation_status"]),
            models.Index(fields=["event_time"]),
        ]

    def __str__(self):
        return f"{self.ad.title} - {self.event_type} - {self.event_time}"
    

# =========================================================
# BILLING RUN LOG
# =========================================================

class BillingRunLog(models.Model):
    """
    Optional bookkeeping table to track periodic task runs.
    """

    run_type = models.CharField(max_length=50)  # BILLING / AGGREGATION / CAMPAIGN_SYNC
    started_at = models.DateTimeField(default=timezone.now)
    completed_at = models.DateTimeField(null=True, blank=True)

    total_events_processed = models.PositiveIntegerField(default=0)
    total_amount_billed = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)

    status = models.CharField(max_length=20, default="STARTED")
    notes = models.TextField(blank=True, null=True)

    class Meta:
        ordering = ["-started_at"]

    def __str__(self):
        return f"{self.run_type} - {self.started_at}"
    

# =========================================================
# AUDIENCE
# =========================================================

class Audience(models.Model):
    """
    One real audience/user identity.
    Indian mobile number is treated as the login identity.
    This table stores the reusable identity, not one login session.
    """

    owner = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="audiences",
        help_text="Portal owner / business owner who owns this audience record"
    )

    mobile_number = models.CharField(
        max_length=12,
        unique=True,
        db_index=True,
        help_text="Indian MSISDN in normalized format: 91XXXXXXXXXX"
    )

    client_name = models.CharField(
        max_length=128,
        blank=True,
        default="",
        help_text="Optional name or label for this audience"
    )

    is_phone_verified = models.BooleanField(default=False)
    first_verified_at = models.DateTimeField(null=True, blank=True)
    last_verified_at = models.DateTimeField(null=True, blank=True)

    consent_accepted = models.BooleanField(default=False)
    consent_accepted_at = models.DateTimeField(null=True, blank=True)

    first_seen_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)
    last_login_at = models.DateTimeField(null=True, blank=True)

    total_sessions = models.PositiveIntegerField(default=0)
    total_verified_sessions = models.PositiveIntegerField(default=0)

    notes = models.TextField(blank=True, default="")
    profile_data = models.JSONField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-last_seen_at"]
        indexes = [
            models.Index(fields=["owner", "created_at"]),
            models.Index(fields=["owner", "last_seen_at"]),
            models.Index(fields=["mobile_number"]),
            models.Index(fields=["is_phone_verified", "last_verified_at"]),
        ]

    def clean(self):
        if self.mobile_number:
            digits = "".join(ch for ch in self.mobile_number if ch.isdigit())
            if len(digits) == 10:
                digits = f"91{digits}"
            if not (len(digits) == 12 and digits.startswith("91")):
                raise ValidationError("Audience mobile number must be a valid Indian number in 91XXXXXXXXXX format.")
            self.mobile_number = digits

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    @property
    def login_id(self):
        return self.mobile_number

    def __str__(self):
        base = self.client_name or self.mobile_number or "audience"
        return f"{self.owner.username} — {base}"


# =========================================================
# AUDIENCE SESSION
# =========================================================

class AudienceSession(models.Model):
    AUTH_STATUS_CHOICES = (
        ("STARTED", "Started"),
        ("OTP_SENT", "OTP Sent"),
        ("OTP_VERIFIED", "OTP Verified"),
        ("AUTHORISED", "Authorised"),
        ("FAILED", "Failed"),
        ("EXPIRED", "Expired"),
    )

    audience = models.ForeignKey(
        Audience,
        on_delete=models.CASCADE,
        related_name="sessions"
    )

    owner = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="audience_sessions"
    )

    asset = models.ForeignKey(
        "Asset",
        on_delete=models.CASCADE,
        related_name="audience_sessions"
    )

    ad = models.ForeignKey(
        "Ad",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audience_sessions"
    )

    serve_session = models.ForeignKey(
        "AdServeSession",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audience_sessions"
    )

    rhid = models.CharField(max_length=128, blank=True, default="", db_index=True)

    client_ip = models.GenericIPAddressField(blank=True, null=True)
    client_mac = models.CharField(max_length=32, blank=True, default="")
    user_agent = models.TextField(blank=True, default="")

    auth_status = models.CharField(max_length=20, choices=AUTH_STATUS_CHOICES, default="STARTED")

    is_verified = models.BooleanField(default=False)
    otp_sent_at = models.DateTimeField(null=True, blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)
    authorised_at = models.DateTimeField(null=True, blank=True)
    expired_at = models.DateTimeField(null=True, blank=True)

    session_started_at = models.DateTimeField(auto_now_add=True)
    session_ended_at = models.DateTimeField(null=True, blank=True)

    request_meta = models.JSONField(blank=True, null=True)
    analytics_data = models.JSONField(blank=True, null=True)

    class Meta:
        ordering = ["-session_started_at"]
        indexes = [
            models.Index(fields=["owner", "session_started_at"]),
            models.Index(fields=["asset", "session_started_at"]),
            models.Index(fields=["audience", "session_started_at"]),
            models.Index(fields=["client_mac"]),
            models.Index(fields=["ad"]),
            models.Index(fields=["is_verified", "verified_at"]),
            models.Index(fields=["rhid"]),
            models.Index(fields=["auth_status"]),
        ]

    def save(self, *args, **kwargs):
        if self.client_mac:
            mac = self.client_mac.strip().upper().replace("-", ":")
            if _MAC_RE.match(mac):
                self.client_mac = mac
        super().save(*args, **kwargs)

    def __str__(self):
        base = self.audience.mobile_number if self.audience_id else "unknown"
        return f"{self.asset.name} — {base} @ {self.session_started_at:%Y-%m-%d %H:%M:%S}"
    

class AuthGrant(models.Model):
    asset = models.ForeignKey("Asset", on_delete=models.CASCADE)
    audience_session = models.ForeignKey(
        "AudienceSession",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="auth_grants"
    )

    rhid = models.CharField(max_length=128, db_index=True)

    sessionlength = models.PositiveIntegerField(default=0)
    uploadrate = models.PositiveIntegerField(default=0)
    downloadrate = models.PositiveIntegerField(default=0)
    uploadquota = models.PositiveIntegerField(default=0)
    downloadquota = models.PositiveIntegerField(default=0)
    redirurl = models.CharField(max_length=512, blank=True, default="")
    custom = models.CharField(max_length=256, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    consumed_at = models.DateTimeField(null=True, blank=True)

    confirmed_at = models.DateTimeField(null=True, blank=True)
    emit_attempts = models.PositiveIntegerField(default=0)
    last_emitted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at"]
        constraints = [
            models.UniqueConstraint(fields=["asset", "rhid"], name="uniq_asset_rhid"),
        ]
        indexes = [
            models.Index(fields=["asset", "rhid"]),
            models.Index(fields=["asset", "consumed_at"]),
            models.Index(fields=["asset", "confirmed_at"]),
            models.Index(fields=["created_at"]),
            models.Index(fields=["last_emitted_at", "emit_attempts"]),
        ]

    def __str__(self):
        return f"{self.asset_id}:{self.rhid[:12]} created={self.created_at:%Y-%m-%d %H:%M:%S}"