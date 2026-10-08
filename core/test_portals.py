import io
import shutil
import tempfile

from PIL import Image
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from ads.models import Ad, AdMetrics, Asset, Campaign, Placement
from .portal_views import ROLES


class PlatformPortalTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.users = {}
        for role, details in ROLES.items():
            group = Group.objects.create(name=details["group"])
            user = get_user_model().objects.create_user(
                username=role, password="test-password"
            )
            user.groups.add(group)
            cls.users[role] = user
        cls.other = get_user_model().objects.create_user(username="other-customer")
        cls.hosted = Asset.objects.create(
            name="Hosted café",
            code="hosted",
            owner_type="ADMIN",
            admin=cls.users["admin"],
        )
        cls.owned = Asset.objects.create(
            name="Owner café",
            code="owned",
            owner_type="PARTNER",
            partner=cls.users["owner"],
        )
        cls.foreign = Asset.objects.create(
            name="Unrelated location",
            code="foreign",
            owner_type="PARTNER",
            partner=cls.other,
        )
        cls.mine = Campaign.objects.create(
            name="My campaign", owner=cls.users["customer"]
        )
        cls.theirs = Campaign.objects.create(
            name="Private foreign campaign", owner=cls.other
        )
        cls.ad = Ad.objects.create(
            owner=cls.users["customer"],
            campaign=cls.mine,
            title="My poster",
            ad_type="IMAGE",
        )
        cls.other_ad = Ad.objects.create(
            owner=cls.other, campaign=cls.theirs, title="Other poster", ad_type="IMAGE"
        )
        placement = Placement.objects.create(ad=cls.ad, asset=cls.owned)
        other_placement = Placement.objects.create(ad=cls.other_ad, asset=cls.foreign)
        AdMetrics.objects.create(
            ad=cls.ad,
            placement=placement,
            date=timezone.localdate(),
            impressions=50,
            clicks=5,
        )
        AdMetrics.objects.create(
            ad=cls.other_ad,
            placement=other_placement,
            date=timezone.localdate(),
            impressions=999,
            clicks=99,
        )

    def setUp(self):
        self.media = tempfile.mkdtemp(prefix="wiadspot-test-")
        self.settings_override = override_settings(MEDIA_ROOT=self.media)
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.addCleanup(shutil.rmtree, self.media)

    def poster(self):
        buffer = io.BytesIO()
        Image.new("RGB", (120, 120), "green").save(buffer, format="PNG")
        return SimpleUploadedFile(
            "poster.png", buffer.getvalue(), content_type="image/png"
        )

    def submission(self, location, name="New campaign"):
        return {
            "name": name,
            "title": "Fresh poster",
            "location": location.pk,
            "target_url": "https://example.com",
            "poster": self.poster(),
        }

    def test_public_home_and_account_choices(self):
        response = self.client.get("/")
        self.assertContains(response, "Pay per user.")
        self.assertContains(response, "A monthly subscription.")
        for role in ROLES:
            self.assertContains(
                self.client.get(reverse("account_login") + "?role=" + role),
                "Your workspace awaits.",
            )

    def test_unauthenticated_workspaces_redirect_to_selected_login(self):
        for role in ROLES:
            response = self.client.get(reverse("portal_dashboard", args=[role]))
            self.assertRedirects(response, reverse("account_login") + "?role=" + role)

    def test_each_account_can_render_only_its_workspace(self):
        for role, user in self.users.items():
            self.client.force_login(user)
            self.assertEqual(
                self.client.get(reverse("portal_dashboard", args=[role])).status_code,
                200,
            )
            for other_role in ROLES:
                if other_role != role:
                    self.assertEqual(
                        self.client.get(
                            reverse("portal_dashboard", args=[other_role])
                        ).status_code,
                        403,
                    )

    def test_customer_only_sees_own_campaign_metrics(self):
        self.client.force_login(self.users["customer"])
        response = self.client.get(reverse("portal_dashboard", args=["customer"]))
        self.assertContains(response, "My campaign")
        self.assertNotContains(response, "Private foreign campaign")
        self.assertEqual(response.context["stats"][2]["value"], 50)
        self.assertEqual(response.context["click_rate"], 10)

    def test_owner_only_sees_own_locations_and_their_activity(self):
        self.client.force_login(self.users["owner"])
        response = self.client.get(reverse("portal_dashboard", args=["owner"]))
        self.assertContains(response, "Owner café")
        self.assertNotContains(response, "Unrelated location")
        self.assertNotContains(response, "Private foreign campaign")
        self.assertEqual(response.context["stats"][2]["value"], 50)

    def test_wrong_account_selection_does_not_authenticate(self):
        response = self.client.post(
            reverse("account_login"),
            {"role": "admin", "username": "customer", "password": "test-password"},
        )
        self.assertContains(response, "credentials or account type are incorrect")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_login_redirect_and_post_only_logout(self):
        response = self.client.post(
            reverse("account_login"),
            {"role": "customer", "username": "customer", "password": "test-password"},
        )
        self.assertRedirects(response, reverse("portal_dashboard", args=["customer"]))
        self.assertEqual(self.client.get(reverse("account_logout")).status_code, 405)
        self.client.post(reverse("account_logout"))
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_customer_submission_creates_pending_entities_and_image(self):
        self.client.force_login(self.users["customer"])
        response = self.client.post(
            reverse("portal_campaign_create", args=["customer"]),
            self.submission(self.hosted),
        )
        self.assertRedirects(response, reverse("portal_dashboard", args=["customer"]))
        campaign = Campaign.objects.get(name="New campaign")
        self.assertEqual(campaign.review_status, "PENDING")
        self.assertEqual(campaign.status, "DRAFT")
        self.assertEqual(campaign.start_date, timezone.localdate())
        ad = campaign.ads.get()
        self.assertEqual(ad.status, "PENDING")
        self.assertTrue(ad.media_file.storage.exists(ad.media_file.name))
        placement = ad.placements.get()
        self.assertEqual(placement.status, "PENDING")
        self.assertFalse(placement.serving_enabled)

    def test_owner_cannot_submit_to_someone_elses_location(self):
        self.client.force_login(self.users["owner"])
        response = self.client.post(
            reverse("portal_campaign_create", args=["owner"]),
            self.submission(self.foreign),
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("location", response.context["form"].errors)
        self.assertFalse(Campaign.objects.filter(name="New campaign").exists())

    def test_closed_location_and_duplicate_campaign_are_rejected(self):
        self.client.force_login(self.users["customer"])
        url = reverse("portal_campaign_create", args=["customer"])
        self.hosted.is_available_for_booking = False
        self.hosted.save()
        response = self.client.post(url, self.submission(self.hosted))
        self.assertIn("location", response.context["form"].errors)
        self.hosted.is_available_for_booking = True
        self.hosted.save()
        response = self.client.post(
            url, self.submission(self.hosted, name="My campaign")
        )
        self.assertIn("name", response.context["form"].errors)
        self.assertEqual(self.mine.ads.count(), 1)

    def test_invalid_image_is_rejected_without_database_writes(self):
        self.client.force_login(self.users["customer"])
        data = self.submission(self.hosted)
        data["poster"] = SimpleUploadedFile(
            "poster.png", b"not-an-image", content_type="image/png"
        )
        response = self.client.post(
            reverse("portal_campaign_create", args=["customer"]), data
        )
        self.assertIn("poster", response.context["form"].errors)
        self.assertFalse(Campaign.objects.filter(name="New campaign").exists())

    def test_unknown_role_returns_404_and_management_accounts_cannot_upload(self):
        self.assertEqual(self.client.get("/portal/unknown/").status_code, 404)
        for role in ("admin", "manager"):
            self.client.force_login(self.users[role])
            self.assertEqual(
                self.client.get(
                    reverse("portal_campaign_create", args=[role])
                ).status_code,
                403,
            )

    def test_new_workspaces_route_on_existing_subdomains(self):
        self.client.force_login(self.users["admin"])
        response = self.client.get(
            "/portal/admin/", HTTP_HOST="admin.wiadspot.local:8000"
        )
        self.assertContains(response, "Platform overview")
        response = self.client.get("/", HTTP_HOST="www.wiadspot.local:8000")
        self.assertContains(response, "Make every")

    def test_login_requires_csrf_token(self):
        client = Client(enforce_csrf_checks=True)
        response = client.post(
            reverse("account_login"),
            {"role": "admin", "username": "admin", "password": "test-password"},
        )
        self.assertEqual(response.status_code, 403)

    def test_existing_manager_review_tools_are_accessible_and_protected(self):
        self.client.force_login(self.users["manager"])
        self.assertEqual(self.client.get(reverse("review_queue")).status_code, 200)
        self.client.force_login(self.users["customer"])
        self.assertEqual(self.client.get(reverse("review_queue")).status_code, 302)

    def test_existing_review_actions_approve_each_entity_separately(self):
        self.client.force_login(self.users["manager"])
        placement = self.ad.placements.get()
        for route, obj in (
            ("campaign_review", self.mine),
            ("ad_review", self.ad),
            ("placement_review", placement),
        ):
            response = self.client.post(
                reverse("ads:" + route, args=[obj.pk, "approve"]),
                {"reason": "Approved in test"},
            )
            self.assertEqual(response.status_code, 302)
        self.mine.refresh_from_db()
        self.ad.refresh_from_db()
        placement.refresh_from_db()
        self.assertEqual(self.mine.review_status, "APPROVED")
        self.assertEqual(self.ad.status, "APPROVED")
        self.assertEqual(placement.status, "APPROVED")
