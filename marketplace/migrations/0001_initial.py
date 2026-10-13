import decimal

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("ads", "0002_asset_default_downloadquota_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="Town",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=120, unique=True)),
                ("slug", models.SlugField(max_length=140, unique=True)),
                ("is_active", models.BooleanField(default=True)),
            ],
            options={"ordering": ["name"]},
        ),
        migrations.CreateModel(
            name="MarketplaceSettings",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("company_rate_per_view", models.DecimalField(decimal_places=4, default=decimal.Decimal("0.50"), help_text="Charged to the advertiser for each user who sees an ad on a WiadSpot-hosted spot.", max_digits=8, verbose_name="WiadSpot-hosted spot: cost per user")),
                ("partner_rate_per_view", models.DecimalField(decimal_places=4, default=decimal.Decimal("0.80"), help_text="Charged for each user on a spot a location owner has given to WiadSpot (higher than hosted).", max_digits=8, verbose_name="Owner-listed spot: cost per user")),
                ("owner_share_percent", models.DecimalField(decimal_places=2, default=decimal.Decimal("60.00"), max_digits=5, verbose_name="Owner share of listed-spot revenue (%)")),
                ("min_withdrawal", models.DecimalField(decimal_places=2, default=decimal.Decimal("500.00"), max_digits=10, verbose_name="Minimum withdrawal")),
                ("pool_strategy", models.CharField(choices=[("ROTATE", "Fair rotation (least recently shown first)"), ("WEIGHTED", "Weighted random (by placement weight)"), ("HIGHEST", "Highest priority and bid first")], default="ROTATE", max_length=10)),
                ("repeat_view_window_minutes", models.PositiveIntegerField(default=30, help_text="The same visitor seeing the same ad on the same spot inside this window is counted and billed once.", verbose_name="Repeat-view window (minutes)")),
                ("require_authentic_device", models.BooleanField(default=True, help_text="When on, views are billed only if the request carried the spot's encrypted gateway payload.", verbose_name="Bill only requests from authenticated spot devices")),
                ("image_width", models.PositiveIntegerField(default=1280, verbose_name="Image width (px)")),
                ("image_height", models.PositiveIntegerField(default=720, verbose_name="Image height (px)")),
                ("image_max_mb", models.PositiveIntegerField(default=5, verbose_name="Image max size (MB)")),
                ("video_width", models.PositiveIntegerField(default=1280, verbose_name="Video width (px)")),
                ("video_height", models.PositiveIntegerField(default=720, verbose_name="Video height (px)")),
                ("video_max_mb", models.PositiveIntegerField(default=20, verbose_name="Video max size (MB)")),
                ("video_min_seconds", models.PositiveIntegerField(default=5, verbose_name="Video min length (s)")),
                ("video_max_seconds", models.PositiveIntegerField(default=30, verbose_name="Video max length (s)")),
            ],
            options={"verbose_name": "Marketplace settings", "verbose_name_plural": "Marketplace settings"},
        ),
        migrations.CreateModel(
            name="SpotProfile",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("mode", models.CharField(choices=[("COMPANY", "WiadSpot hosted"), ("PRIVATE", "Owner's own spot (not listed)"), ("LISTED", "Owner spot listed on WiadSpot")], default="PRIVATE", max_length=10)),
                ("rate_override", models.DecimalField(blank=True, decimal_places=4, help_text="Leave empty to use the platform rate for this kind of spot.", max_digits=8, null=True, verbose_name="Cost per user override")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("asset", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="spot", to="ads.asset")),
                ("town", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="spots", to="marketplace.town")),
            ],
            options={"ordering": ["asset__name"]},
        ),
        migrations.CreateModel(
            name="SpotDevice",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("token_prefix", models.CharField(db_index=True, max_length=12)),
                ("token_hash", models.CharField(max_length=64)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("last_seen_at", models.DateTimeField(blank=True, null=True)),
                ("last_seen_ip", models.GenericIPAddressField(blank=True, null=True)),
                ("asset", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="device_credential", to="ads.asset")),
            ],
        ),
        migrations.CreateModel(
            name="LocationRequest",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("kind", models.CharField(choices=[("LIST_EXISTING", "List my existing spot on WiadSpot"), ("NEW_INSTALL", "Install a WiadSpot at my place")], max_length=15)),
                ("name", models.CharField(max_length=255)),
                ("address", models.TextField(blank=True)),
                ("contact_phone", models.CharField(blank=True, max_length=20)),
                ("notes", models.TextField(blank=True)),
                ("status", models.CharField(choices=[("PENDING", "Pending review"), ("APPROVED", "Approved"), ("INSTALLING", "Installation in progress"), ("COMPLETED", "Completed"), ("REJECTED", "Rejected")], default="PENDING", max_length=12)),
                ("reviewed_at", models.DateTimeField(blank=True, null=True)),
                ("review_note", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("asset", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="location_requests", to="ads.asset")),
                ("reviewed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
                ("town", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="location_requests", to="marketplace.town")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="location_requests", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="CampaignPlan",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("total_budget", models.DecimalField(decimal_places=2, max_digits=12)),
                ("daily_budget", models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True)),
                ("max_views", models.PositiveIntegerField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("campaign", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="plan", to="ads.campaign")),
            ],
        ),
        migrations.CreateModel(
            name="PlacementTerms",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("rate_per_view", models.DecimalField(decimal_places=4, max_digits=8)),
                ("free_own_spot", models.BooleanField(default=False, help_text="Owner advertising on their own spot: no per-user charge (subscription still required).")),
                ("owner_share_percent", models.DecimalField(decimal_places=2, default=decimal.Decimal("0.00"), max_digits=5)),
                ("beneficiary", models.ForeignKey(blank=True, help_text="Spot owner who earns a share of this placement's revenue.", null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
                ("placement", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="terms", to="ads.placement")),
            ],
        ),
        migrations.CreateModel(
            name="OwnerAccount",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("balance", models.DecimalField(decimal_places=4, default=decimal.Decimal("0"), max_digits=14)),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="owner_account", to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name="EarningEntry",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("amount", models.DecimalField(decimal_places=4, max_digits=12)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("asset", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="+", to="ads.asset")),
                ("event", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="earning", to="ads.adeventlog")),
                ("owner", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="earnings", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="Withdrawal",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("amount", models.DecimalField(decimal_places=2, max_digits=12)),
                ("payout_details", models.TextField(help_text="Bank account / UPI details for the transfer.")),
                ("status", models.CharField(choices=[("REQUESTED", "Requested"), ("PAID", "Paid"), ("REJECTED", "Rejected")], default="REQUESTED", max_length=10)),
                ("processed_at", models.DateTimeField(blank=True, null=True)),
                ("note", models.CharField(blank=True, max_length=255)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("owner", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="withdrawals", to=settings.AUTH_USER_MODEL)),
                ("processed_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-created_at"]},
        ),
    ]
