from django.db.models.signals import post_save
from django.dispatch import receiver

from ads.models import Asset


@receiver(post_save, sender=Asset)
def ensure_spot_profile(sender, instance, created, **kwargs):
    """Every spot gets marketplace data; managers must be able to approve its ads."""
    from .models import SpotProfile

    mode = SpotProfile.MODE_COMPANY if instance.owner_type == "ADMIN" else SpotProfile.MODE_PRIVATE
    SpotProfile.objects.get_or_create(asset=instance, defaults={"mode": mode})
    if not instance.allow_manager_approval:
        Asset.objects.filter(pk=instance.pk).update(allow_manager_approval=True)
