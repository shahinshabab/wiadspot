"""Create or update the platform super admin from environment variables.

Idempotent; safe to run on every deploy. Does nothing unless a password is set,
so the password never lives in the repository.
"""

import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Ensure the super admin exists (SUPERADMIN_USERNAME / SUPERADMIN_PASSWORD)."

    def handle(self, *args, **options):
        username = os.environ.get("SUPERADMIN_USERNAME", "").strip()
        password = os.environ.get("SUPERADMIN_PASSWORD", "")
        if not username or not password:
            self.stdout.write("SUPERADMIN_USERNAME/SUPERADMIN_PASSWORD not set; skipping.")
            return
        user, created = get_user_model().objects.get_or_create(username=username)
        user.is_active = user.is_staff = user.is_superuser = True
        user.set_password(password)
        user.save()
        self.stdout.write(f"Super admin '{username}' {'created' if created else 'updated'}.")
