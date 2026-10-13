from django.contrib import admin

from .models import (
    CampaignPlan,
    EarningEntry,
    LocationRequest,
    MarketplaceSettings,
    OwnerAccount,
    PlacementTerms,
    SpotDevice,
    SpotProfile,
    Town,
    Withdrawal,
)


@admin.register(Town)
class TownAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active")
    search_fields = ("name",)


@admin.register(SpotProfile)
class SpotProfileAdmin(admin.ModelAdmin):
    list_display = ("asset", "town", "mode", "rate_override")
    list_filter = ("mode", "town")
    search_fields = ("asset__name", "asset__code", "town__name")


@admin.register(SpotDevice)
class SpotDeviceAdmin(admin.ModelAdmin):
    list_display = ("asset", "token_prefix", "is_active", "last_seen_at", "last_seen_ip")
    readonly_fields = ("token_prefix", "token_hash", "last_seen_at", "last_seen_ip")


@admin.register(Withdrawal)
class WithdrawalAdmin(admin.ModelAdmin):
    list_display = ("owner", "amount", "status", "created_at")
    list_filter = ("status",)


admin.site.register(MarketplaceSettings)
admin.site.register(LocationRequest)
admin.site.register(CampaignPlan)
admin.site.register(PlacementTerms)
admin.site.register(OwnerAccount)
admin.site.register(EarningEntry)
