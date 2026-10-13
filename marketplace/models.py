"""Ad marketplace: spots by town, pricing, ad submissions, owner earnings."""

import hashlib
import hmac
import secrets
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.text import slugify

User = settings.AUTH_USER_MODEL


class Town(models.Model):
    """A Kerala town. There is no district level."""

    name = models.CharField(max_length=120, unique=True)
    slug = models.SlugField(max_length=140, unique=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)


class MarketplaceSettings(models.Model):
    """Single row of platform-wide values the administrator controls."""

    POOL_ROTATE = "ROTATE"
    POOL_WEIGHTED = "WEIGHTED"
    POOL_HIGHEST = "HIGHEST"
    POOL_CHOICES = (
        (POOL_ROTATE, "Fair rotation (least recently shown first)"),
        (POOL_WEIGHTED, "Weighted random (by placement weight)"),
        (POOL_HIGHEST, "Highest priority and bid first"),
    )

    company_rate_per_view = models.DecimalField(
        "WiadSpot-hosted spot: cost per user", max_digits=8, decimal_places=4,
        default=Decimal("0.50"),
        help_text="Charged to the advertiser for each user who sees an ad on a WiadSpot-hosted spot.",
    )
    partner_rate_per_view = models.DecimalField(
        "Owner-listed spot: cost per user", max_digits=8, decimal_places=4,
        default=Decimal("0.80"),
        help_text="Charged for each user on a spot a location owner has given to WiadSpot (higher than hosted).",
    )
    owner_share_percent = models.DecimalField(
        "Owner share of listed-spot revenue (%)", max_digits=5, decimal_places=2,
        default=Decimal("60.00"),
    )
    min_withdrawal = models.DecimalField(
        "Minimum withdrawal", max_digits=10, decimal_places=2, default=Decimal("500.00"),
    )

    pool_strategy = models.CharField(max_length=10, choices=POOL_CHOICES, default=POOL_ROTATE)
    repeat_view_window_minutes = models.PositiveIntegerField(
        "Repeat-view window (minutes)", default=30,
        help_text="The same visitor seeing the same ad on the same spot inside this window is counted and billed once.",
    )
    require_authentic_device = models.BooleanField(
        "Bill only requests from authenticated spot devices", default=True,
        help_text="When on, views are billed only if the request carried the spot's encrypted gateway payload.",
    )

    image_width = models.PositiveIntegerField("Image width (px)", default=1280)
    image_height = models.PositiveIntegerField("Image height (px)", default=720)
    image_max_mb = models.PositiveIntegerField("Image max size (MB)", default=5)
    video_width = models.PositiveIntegerField("Video width (px)", default=1280)
    video_height = models.PositiveIntegerField("Video height (px)", default=720)
    video_max_mb = models.PositiveIntegerField("Video max size (MB)", default=20)
    video_min_seconds = models.PositiveIntegerField("Video min length (s)", default=5)
    video_max_seconds = models.PositiveIntegerField("Video max length (s)", default=30)

    class Meta:
        verbose_name = "Marketplace settings"
        verbose_name_plural = "Marketplace settings"

    def __str__(self):
        return "Marketplace settings"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class SpotProfile(models.Model):
    """Marketplace data for an existing ads.Asset (a physical WiFi spot)."""

    MODE_COMPANY = "COMPANY"
    MODE_PRIVATE = "PRIVATE"
    MODE_LISTED = "LISTED"
    MODE_CHOICES = (
        (MODE_COMPANY, "WiadSpot hosted"),
        (MODE_PRIVATE, "Owner's own spot (not listed)"),
        (MODE_LISTED, "Owner spot listed on WiadSpot"),
    )

    asset = models.OneToOneField(
        "ads.Asset", on_delete=models.CASCADE, related_name="spot"
    )
    town = models.ForeignKey(
        Town, null=True, blank=True, on_delete=models.PROTECT, related_name="spots"
    )
    mode = models.CharField(max_length=10, choices=MODE_CHOICES, default=MODE_PRIVATE)
    rate_override = models.DecimalField(
        "Cost per user override", max_digits=8, decimal_places=4, null=True, blank=True,
        help_text="Leave empty to use the platform rate for this kind of spot.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["asset__name"]

    def __str__(self):
        return f"{self.asset.name} ({self.get_mode_display()})"

    @property
    def is_bookable_by_others(self):
        return self.mode in (self.MODE_COMPANY, self.MODE_LISTED)

    @property
    def rate_per_view(self):
        if self.rate_override is not None:
            return self.rate_override
        conf = MarketplaceSettings.load()
        if self.mode == self.MODE_LISTED:
            return conf.partner_rate_per_view
        return conf.company_rate_per_view


class SpotDevice(models.Model):
    """Credential a physical spot uses to authenticate to WiadSpot.

    Only a keyed hash of the token is stored; the token is shown once.
    """

    asset = models.OneToOneField(
        "ads.Asset", on_delete=models.CASCADE, related_name="device_credential"
    )
    token_prefix = models.CharField(max_length=12, db_index=True)
    token_hash = models.CharField(max_length=64)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)
    last_seen_ip = models.GenericIPAddressField(null=True, blank=True)

    def __str__(self):
        return f"Device for {self.asset.name}"

    @staticmethod
    def _digest(token):
        return hmac.new(
            settings.SECRET_KEY.encode(), token.encode(), hashlib.sha256
        ).hexdigest()

    @classmethod
    def issue(cls, asset):
        """Create or rotate the credential. Returns (device, plaintext_token)."""
        prefix = secrets.token_hex(4)
        token = f"wsd_{prefix}_{secrets.token_urlsafe(32)}"
        device, _ = cls.objects.update_or_create(
            asset=asset,
            defaults={
                "token_prefix": prefix,
                "token_hash": cls._digest(token),
                "is_active": True,
            },
        )
        return device, token

    @classmethod
    def authenticate(cls, token):
        parts = (token or "").split("_", 2)
        if len(parts) != 3 or parts[0] != "wsd":
            return None
        digest = cls._digest(token)
        for device in cls.objects.select_related("asset").filter(
            token_prefix=parts[1], is_active=True
        ):
            if hmac.compare_digest(device.token_hash, digest):
                return device
        return None


class LocationRequest(models.Model):
    """An owner asks WiadSpot to list an existing spot, or install a new one."""

    KIND_LIST = "LIST_EXISTING"
    KIND_INSTALL = "NEW_INSTALL"
    KIND_CHOICES = (
        (KIND_LIST, "List my existing spot on WiadSpot"),
        (KIND_INSTALL, "Install a WiadSpot at my place"),
    )
    STATUS_CHOICES = (
        ("PENDING", "Pending review"),
        ("APPROVED", "Approved"),
        ("INSTALLING", "Installation in progress"),
        ("COMPLETED", "Completed"),
        ("REJECTED", "Rejected"),
    )
    OPEN_STATUSES = ("PENDING", "APPROVED", "INSTALLING")

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="location_requests")
    kind = models.CharField(max_length=15, choices=KIND_CHOICES)
    asset = models.ForeignKey(
        "ads.Asset", null=True, blank=True, on_delete=models.CASCADE,
        related_name="location_requests",
    )
    name = models.CharField(max_length=255)
    town = models.ForeignKey(Town, on_delete=models.PROTECT, related_name="location_requests")
    address = models.TextField(blank=True)
    contact_phone = models.CharField(max_length=20, blank=True)
    notes = models.TextField(blank=True)

    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default="PENDING")
    reviewed_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_kind_display()}: {self.name}"


class CampaignPlan(models.Model):
    """Budget and delivery limits chosen by the advertiser for a campaign."""

    campaign = models.OneToOneField(
        "ads.Campaign", on_delete=models.CASCADE, related_name="plan"
    )
    total_budget = models.DecimalField(max_digits=12, decimal_places=2)
    daily_budget = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    max_views = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Plan for {self.campaign.name}"


class PlacementTerms(models.Model):
    """Price and revenue split fixed when an ad was booked on a spot."""

    placement = models.OneToOneField(
        "ads.Placement", on_delete=models.CASCADE, related_name="terms"
    )
    rate_per_view = models.DecimalField(max_digits=8, decimal_places=4)
    free_own_spot = models.BooleanField(
        default=False,
        help_text="Owner advertising on their own spot: no per-user charge (subscription still required).",
    )
    beneficiary = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+",
        help_text="Spot owner who earns a share of this placement's revenue.",
    )
    owner_share_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal("0.00")
    )

    def __str__(self):
        return f"Terms for placement {self.placement_id}"


class OwnerAccount(models.Model):
    """Earnings balance of a location owner."""

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="owner_account")
    balance = models.DecimalField(max_digits=14, decimal_places=4, default=Decimal("0"))

    def __str__(self):
        return f"{self.user} balance {self.balance}"


class EarningEntry(models.Model):
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="earnings")
    event = models.OneToOneField(
        "ads.AdEventLog", on_delete=models.PROTECT, related_name="earning"
    )
    asset = models.ForeignKey("ads.Asset", on_delete=models.PROTECT, related_name="+")
    amount = models.DecimalField(max_digits=12, decimal_places=4)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]


class Withdrawal(models.Model):
    STATUS_CHOICES = (
        ("REQUESTED", "Requested"),
        ("PAID", "Paid"),
        ("REJECTED", "Rejected"),
    )

    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="withdrawals")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    payout_details = models.TextField(help_text="Bank account / UPI details for the transfer.")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="REQUESTED")
    processed_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    processed_at = models.DateTimeField(null=True, blank=True)
    note = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.owner} withdrawal {self.amount} ({self.status})"
