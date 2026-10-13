from django.db import migrations
from django.utils.text import slugify

from marketplace.kerala_towns import town_names


def seed(apps, schema_editor):
    Town = apps.get_model("marketplace", "Town")
    Settings = apps.get_model("marketplace", "MarketplaceSettings")
    SpotProfile = apps.get_model("marketplace", "SpotProfile")
    Asset = apps.get_model("ads", "Asset")
    MetricPricing = apps.get_model("ads", "MetricPricing")

    existing = set(Town.objects.values_list("name", flat=True))
    Town.objects.bulk_create(
        [Town(name=name, slug=slugify(name)) for name in town_names() if name not in existing]
    )
    Settings.objects.get_or_create(pk=1)
    # Serving needs one active pricing row; marketplace rates override its amounts.
    if not MetricPricing.objects.filter(is_active=True).exists():
        MetricPricing.objects.create(name="Marketplace default", is_active=True)
    for asset in Asset.objects.all():
        mode = "COMPANY" if asset.owner_type == "ADMIN" else "PRIVATE"
        SpotProfile.objects.get_or_create(asset=asset, defaults={"mode": mode})
    Asset.objects.filter(allow_manager_approval=False).update(allow_manager_approval=True)


class Migration(migrations.Migration):
    dependencies = [("marketplace", "0001_initial")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
