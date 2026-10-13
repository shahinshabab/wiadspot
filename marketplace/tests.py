import io
import shutil
import tempfile
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from ads.models import (
    Ad,
    AdEventLog,
    AdServeSession,
    Asset,
    Campaign,
    Placement,
    SubscriptionPlan,
    UserSubscription,
    Wallet,
)
from ads.services.runtime_service import AdServeError, serve_ad_for_asset
from ads.tasks import bill_pending_events
from core.portal_views import ROLES

from . import media, services
from .models import (
    LocationRequest,
    MarketplaceSettings,
    OwnerAccount,
    SpotDevice,
    SpotProfile,
    Town,
    Withdrawal,
)

STATIC = Path(settings.BASE_DIR) / "static" / "marketplace"
FAS = {"fas": True}  # request metadata of a request that carried the gateway payload


def example_image():
    return SimpleUploadedFile("my ad.png", (STATIC / "example-ad.png").read_bytes(), content_type="image/png")


@override_settings(DEBUG=True, ROUTING_MODE="subdomain")
class MarketplaceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.users = {}
        for role, details in ROLES.items():
            user = User.objects.create_user(role, password="pw-for-tests")
            user.groups.add(Group.objects.create(name=details["group"]))
            cls.users[role] = user
        cls.rival = User.objects.create_user("rival-owner")
        cls.rival.groups.add(Group.objects.get(name="Partner"))
        cls.kochi = Town.objects.get(name="Kochi")
        cls.munnar = Town.objects.get(name="Munnar")

        cls.hosted = Asset.objects.create(
            name="Hosted café", code="hosted", owner_type="ADMIN", admin=cls.users["admin"]
        )
        cls.hosted.spot.town = cls.kochi
        cls.hosted.spot.save()

        cls.mine = Asset.objects.create(
            name="Owner shop", code="owner-shop", owner_type="PARTNER", partner=cls.users["owner"]
        )
        cls.mine.spot.town = cls.munnar
        cls.mine.spot.save()

        cls.listed = Asset.objects.create(
            name="Rival bakery", code="rival-bakery", owner_type="PARTNER", partner=cls.rival
        )
        cls.listed.spot.mode, cls.listed.spot.town = SpotProfile.MODE_LISTED, cls.kochi
        cls.listed.spot.save()

        cls.private_other = Asset.objects.create(
            name="Rival back room", code="rival-private", owner_type="PARTNER", partner=cls.rival
        )

        cls.plan = SubscriptionPlan.objects.create(name="Basic", monthly_price=Decimal("100"), max_campaigns=5)
        for user in (cls.users["customer"], cls.users["owner"]):
            UserSubscription.objects.create(
                user=user, plan=cls.plan, end_date=timezone.now() + timedelta(days=20)
            )
            Wallet.objects.create(user=user, balance=Decimal("1000"))

    def setUp(self):
        cache.clear()  # device rate limits live in the cache
        self.media_root = tempfile.mkdtemp(prefix="wiadspot-mp-")
        override = override_settings(MEDIA_ROOT=self.media_root)
        override.enable()
        self.addCleanup(override.disable)
        self.addCleanup(shutil.rmtree, self.media_root)

    # -- helpers ------------------------------------------------------------

    def submit(self, role="customer", spots=None, **extra):
        self.client.force_login(self.users[role])
        data = {
            "name": "Diwali sale",
            "title": "Diwali sale",
            "media_file": example_image(),
            "target_url": "https://example.com/sale",
            "spots": [s.pk for s in (spots or [self.hosted.spot])],
            "total_budget": "500",
            "daily_budget": "",
            "max_views": "",
            "start_date": "",
            "end_date": "",
        }
        data.update(extra)
        return self.client.post(reverse("portal_ad_create", args=[role]), data)

    def submitted_campaign(self, **kwargs):
        response = self.submit(**kwargs)
        self.assertEqual(response.status_code, 302, getattr(response, "context", None) and response.context["form"].errors)
        return Campaign.objects.get(name=kwargs.get("name", "Diwali sale"))

    def go_live(self, campaign):
        services.approve_submission(campaign, self.users["manager"])

    # -- towns --------------------------------------------------------------

    def test_kerala_towns_are_seeded_and_there_is_no_district_level(self):
        self.assertGreater(Town.objects.count(), 150)
        for name in ("Kochi", "Thiruvananthapuram", "Kozhikode", "Munnar", "Kasaragod"):
            self.assertTrue(Town.objects.filter(name=name).exists(), name)
        self.assertFalse(hasattr(Town, "district"))

    # -- upload validation --------------------------------------------------

    def test_media_accepts_the_example_files(self):
        conf = MarketplaceSettings.load()
        file, width, height = media.process_image(example_image(), conf)
        self.assertEqual((width, height), (1280, 720))
        self.assertRegex(file.name, r"^[0-9a-f]{32}\.png$")
        with (STATIC / "example-ad.mp4").open("rb") as handle:
            file, width, height, seconds = media.process_video(handle, conf)
        self.assertEqual((width, height, seconds), (1280, 720, 6))
        self.assertTrue(file.name.endswith(".mp4"))

    def test_media_rejects_wrong_size_wrong_type_and_disguised_files(self):
        conf = MarketplaceSettings.load()
        small = io.BytesIO()
        Image.new("RGB", (100, 100)).save(small, "PNG")
        for bad in (small.getvalue(), b"not an image", b"<svg xmlns='http://www.w3.org/2000/svg'/>", b"GIF89a" + b"\0" * 40):
            with self.assertRaises(media.MediaError):
                media.process_image(io.BytesIO(bad), conf)
        with self.assertRaises(media.MediaError):
            media.process_video(io.BytesIO(b"\0\0\0\x18ftypmp42" + b"\0" * 64), conf)
        with self.assertRaises(media.MediaError):
            media.process_video(io.BytesIO((STATIC / "example-ad.png").read_bytes()), conf)

    def test_media_enforces_the_admin_configured_size_limit(self):
        conf = MarketplaceSettings.load()
        conf.image_max_mb = 0
        with self.assertRaises(media.MediaError):
            media.process_image(example_image(), conf)

    def test_a_polyglot_image_is_reencoded_without_its_payload(self):
        buffer = io.BytesIO()
        Image.new("RGB", (1280, 720), "white").save(buffer, "PNG")
        evil = SimpleUploadedFile("x.png", buffer.getvalue() + b"<?php system($_GET['c']); ?>")
        file, _, _ = media.process_image(evil, MarketplaceSettings.load())
        self.assertNotIn(b"<?php", file.read())

    # -- submission ---------------------------------------------------------

    def test_customer_submission_is_pending_with_plan_terms_and_random_file_name(self):
        campaign = self.submitted_campaign(
            spots=[self.hosted.spot, self.listed.spot], daily_budget="100", max_views="300"
        )
        self.assertEqual(campaign.review_status, "PENDING")
        self.assertEqual(campaign.status, "DRAFT")
        self.assertEqual(campaign.plan.total_budget, Decimal("500"))
        self.assertEqual(campaign.plan.daily_budget, Decimal("100"))
        self.assertEqual(campaign.plan.max_views, 300)
        ad = campaign.ads.get()
        self.assertEqual(ad.status, "PENDING")
        self.assertNotIn("my ad", ad.media_file.name)
        placements = {p.asset_id: p for p in ad.placements.all()}
        for placement in placements.values():
            self.assertEqual(placement.status, "PENDING")
            self.assertFalse(placement.serving_enabled)
        self.assertEqual(placements[self.hosted.pk].terms.rate_per_view, Decimal("0.50"))
        listed_terms = placements[self.listed.pk].terms
        self.assertEqual(listed_terms.rate_per_view, Decimal("0.80"))
        self.assertEqual(listed_terms.beneficiary, self.rival)
        self.assertEqual(listed_terms.owner_share_percent, Decimal("60.00"))

    def test_customer_cannot_book_private_spots_or_unknown_ones(self):
        for spot in (self.mine.spot, self.private_other.spot):
            response = self.submit(spots=[spot])
            self.assertEqual(response.status_code, 200)
            self.assertIn("spots", response.context["form"].errors)
        self.assertFalse(Campaign.objects.filter(name="Diwali sale").exists())

    def test_customer_cannot_open_the_locations_page(self):
        self.client.force_login(self.users["customer"])
        self.assertEqual(self.client.get(reverse("portal_locations", args=["customer"])).status_code, 403)

    def test_owner_can_book_own_and_company_spots_but_not_other_owners(self):
        campaign = self.submitted_campaign(role="owner", spots=[self.mine.spot, self.hosted.spot])
        terms = {p.asset_id: p.terms for p in campaign.ads.get().placements.all()}
        self.assertTrue(terms[self.mine.pk].free_own_spot)
        self.assertEqual(terms[self.mine.pk].rate_per_view, 0)
        self.assertFalse(terms[self.hosted.pk].free_own_spot)
        response = self.submit(role="owner", name="Second", spots=[self.listed.spot])
        self.assertIn("spots", response.context["form"].errors)

    def test_invalid_uploads_and_links_are_rejected_without_writes(self):
        bad = SimpleUploadedFile("a.png", b"nope", content_type="image/png")
        response = self.submit(media_file=bad)
        self.assertIn("media_file", response.context["form"].errors)
        response = self.submit(target_url="javascript:alert(1)")
        self.assertIn("target_url", response.context["form"].errors)
        self.assertFalse(Campaign.objects.exists())

    def test_paid_spots_need_a_budget_and_daily_budget_cannot_exceed_total(self):
        self.assertIn("total_budget", self.submit(total_budget="").context["form"].errors)
        response = self.submit(total_budget="50", daily_budget="80")
        self.assertIn("daily_budget", response.context["form"].errors)
        response = self.submit(total_budget="0")
        self.assertEqual(response.status_code, 200)

    def test_old_poster_url_redirects_to_the_new_form(self):
        self.client.force_login(self.users["customer"])
        response = self.client.get(reverse("portal_campaign_create", args=["customer"]))
        self.assertRedirects(response, reverse("portal_ad_create", args=["customer"]))

    def test_plan_campaign_limit_is_enforced(self):
        self.plan.max_campaigns = 1
        self.plan.save()
        self.submitted_campaign()
        response = self.submit(name="Another")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Campaign.objects.count(), 1)

    # -- review and serving -------------------------------------------------

    def test_unapproved_ads_are_never_served(self):
        self.submitted_campaign()
        with self.assertRaises(AdServeError):
            serve_ad_for_asset("hosted", visitor_token="v1", request_meta=FAS)

    def test_rejected_ads_are_never_served(self):
        campaign = self.submitted_campaign()
        services.reject_submission(campaign, self.users["manager"], "Not allowed")
        with self.assertRaises(AdServeError):
            serve_ad_for_asset("hosted", visitor_token="v1", request_meta=FAS)

    def test_manager_approval_makes_the_ad_live_and_serves_the_same_ad(self):
        campaign = self.submitted_campaign()
        self.client.force_login(self.users["manager"])
        response = self.client.post(
            reverse("portal_submissions", args=["manager"]),
            {"campaign_id": campaign.pk, "action": "approve"},
        )
        self.assertEqual(response.status_code, 302)
        campaign.refresh_from_db()
        self.assertEqual(campaign.review_status, "APPROVED")
        payload = serve_ad_for_asset("hosted", visitor_token="v1", request_meta=FAS)
        self.assertEqual(payload["ad_id"], campaign.ads.get().pk)

    def test_rejecting_needs_a_reason(self):
        campaign = self.submitted_campaign()
        self.client.force_login(self.users["manager"])
        self.client.post(reverse("portal_submissions", args=["manager"]), {"campaign_id": campaign.pk, "action": "reject"})
        campaign.refresh_from_db()
        self.assertEqual(campaign.review_status, "PENDING")

    def test_an_ad_without_a_subscription_is_not_served(self):
        campaign = self.submitted_campaign()
        self.go_live(campaign)
        UserSubscription.objects.filter(user=self.users["customer"]).delete()
        with self.assertRaises(AdServeError):
            serve_ad_for_asset("hosted", visitor_token="v1", request_meta=FAS)

    def test_max_views_stops_delivery(self):
        campaign = self.submitted_campaign(max_views="2")
        self.go_live(campaign)
        serve_ad_for_asset("hosted", visitor_token="a", request_meta=FAS)
        serve_ad_for_asset("hosted", visitor_token="b", request_meta=FAS)
        with self.assertRaises(AdServeError):
            serve_ad_for_asset("hosted", visitor_token="c", request_meta=FAS)

    def test_daily_and_total_budget_stop_delivery(self):
        campaign = self.submitted_campaign(total_budget="10", daily_budget="1")
        self.go_live(campaign)
        serve_ad_for_asset("hosted", visitor_token="a", request_meta=FAS)  # 0.50
        serve_ad_for_asset("hosted", visitor_token="b", request_meta=FAS)  # 1.00 spent today
        with self.assertRaises(AdServeError):
            serve_ad_for_asset("hosted", visitor_token="c", request_meta=FAS)

    def test_pool_rotates_between_advertisers(self):
        first = self.submitted_campaign(name="First")
        self.go_live(first)
        second = self.submitted_campaign(name="Second")
        self.go_live(second)
        shown = {serve_ad_for_asset("hosted", visitor_token=f"v{i}", request_meta=FAS)["campaign_id"] for i in range(4)}
        self.assertEqual(shown, {first.pk, second.pk})

    # -- billing and earnings -----------------------------------------------

    def test_views_are_billed_per_user_and_the_listed_owner_earns_a_share(self):
        campaign = self.submitted_campaign(spots=[self.listed.spot], total_budget="100")
        self.go_live(campaign)
        serve_ad_for_asset("rival-bakery", visitor_token="a", request_meta=FAS)
        serve_ad_for_asset("rival-bakery", visitor_token="b", request_meta=FAS)
        bill_pending_events()
        wallet = Wallet.objects.get(user=self.users["customer"])
        self.assertEqual(wallet.balance, Decimal("998.40"))  # 2 views x 0.80
        self.assertEqual(OwnerAccount.objects.get(user=self.rival).balance, Decimal("0.9600"))  # 60% of 1.60
        bill_pending_events()  # running again must not pay twice
        self.assertEqual(OwnerAccount.objects.get(user=self.rival).balance, Decimal("0.9600"))

    def test_owner_views_on_their_own_spot_are_free_but_still_need_a_subscription(self):
        campaign = self.submitted_campaign(role="owner", spots=[self.mine.spot], total_budget="0")
        self.go_live(campaign)
        Wallet.objects.filter(user=self.users["owner"]).update(balance=Decimal("0"))
        serve_ad_for_asset("owner-shop", visitor_token="a", request_meta=FAS)
        bill_pending_events()
        self.assertEqual(Wallet.objects.get(user=self.users["owner"]).balance, Decimal("0"))
        self.assertEqual(AdEventLog.objects.get().billing_status, "BILLED")
        UserSubscription.objects.filter(user=self.users["owner"]).update(status="EXPIRED")
        with self.assertRaises(AdServeError):
            serve_ad_for_asset("owner-shop", visitor_token="b", request_meta=FAS)

    def test_requests_without_the_gateway_payload_and_repeat_views_are_not_billed(self):
        campaign = self.submitted_campaign()
        self.go_live(campaign)
        serve_ad_for_asset("hosted", visitor_token="a", request_meta={})
        serve_ad_for_asset("hosted", visitor_token="b", request_meta=FAS)
        serve_ad_for_asset("hosted", visitor_token="b", request_meta=FAS)
        states = list(AdEventLog.objects.order_by("id").values_list("billing_status", "billable_amount"))
        self.assertEqual(states[0], ("SKIPPED", Decimal("0.0000")))
        self.assertEqual(states[1], ("PENDING", Decimal("0.5000")))
        self.assertEqual(states[2], ("SKIPPED", Decimal("0.0000")))

    def test_admin_changes_to_rates_apply_to_new_bookings(self):
        conf = MarketplaceSettings.load()
        conf.company_rate_per_view = Decimal("1.25")
        conf.save()
        campaign = self.submitted_campaign()
        self.assertEqual(campaign.ads.get().placements.get().terms.rate_per_view, Decimal("1.25"))

    def test_a_per_spot_rate_override_wins(self):
        self.hosted.spot.rate_override = Decimal("0.20")
        self.hosted.spot.save()
        campaign = self.submitted_campaign()
        self.assertEqual(campaign.ads.get().placements.get().terms.rate_per_view, Decimal("0.20"))

    # -- withdrawals --------------------------------------------------------

    def test_withdrawal_flow(self):
        account = OwnerAccount.objects.create(user=self.users["owner"], balance=Decimal("800"))
        with self.assertRaises(services.MarketplaceError):
            services.request_withdrawal(self.users["owner"], Decimal("100"), "UPI x")  # below minimum
        with self.assertRaises(services.MarketplaceError):
            services.request_withdrawal(self.users["owner"], Decimal("900"), "UPI x")  # above balance
        withdrawal = services.request_withdrawal(self.users["owner"], Decimal("600"), "UPI owner@bank")
        account.refresh_from_db()
        self.assertEqual(account.balance, Decimal("200"))
        services.process_withdrawal(withdrawal.pk, self.users["admin"], paid=False, note="bad details")
        account.refresh_from_db()
        self.assertEqual(account.balance, Decimal("800"))
        with self.assertRaises(services.MarketplaceError):
            services.process_withdrawal(withdrawal.pk, self.users["admin"], paid=True)
        withdrawal = services.request_withdrawal(self.users["owner"], Decimal("500"), "UPI owner@bank")
        services.process_withdrawal(withdrawal.pk, self.users["admin"], paid=True, note="ref 1")
        self.assertEqual(Withdrawal.objects.get(pk=withdrawal.pk).status, "PAID")
        account.refresh_from_db()
        self.assertEqual(account.balance, Decimal("300"))

    def test_owner_pages_render_and_withdrawal_form_works(self):
        OwnerAccount.objects.create(user=self.users["owner"], balance=Decimal("700"))
        self.client.force_login(self.users["owner"])
        self.assertEqual(self.client.get(reverse("portal_earnings", args=["owner"])).status_code, 200)
        response = self.client.post(
            reverse("portal_earnings", args=["owner"]), {"amount": "600", "payout_details": "UPI owner@bank"}
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Withdrawal.objects.get().status, "REQUESTED")

    # -- subscriptions and wallet -------------------------------------------

    def test_subscribing_charges_the_wallet_and_needs_enough_funds(self):
        user = get_user_model().objects.create_user("newbie")
        user.groups.add(Group.objects.get(name="Client"))
        with self.assertRaises(services.MarketplaceError):
            services.subscribe(user, self.plan)
        services.credit_wallet(user, Decimal("250"), self.users["admin"], "ref")
        sub = services.subscribe(user, self.plan)
        self.assertTrue(sub.is_valid_subscription())
        self.assertEqual(Wallet.objects.get(user=user).balance, Decimal("150"))

    def test_billing_page_lists_plans_for_advertisers_and_owners(self):
        for role in ("customer", "owner"):
            self.client.force_login(self.users[role])
            self.assertContains(self.client.get(reverse("portal_billing", args=[role])), "Basic")

    # -- locations ----------------------------------------------------------

    def test_owner_lists_a_spot_and_manager_approval_makes_it_bookable_at_the_higher_rate(self):
        self.client.force_login(self.users["owner"])
        response = self.client.post(
            reverse("portal_locations", args=["owner"]),
            {"form": "list", "list-asset_id": self.mine.pk, "list-town": self.munnar.pk},
        )
        self.assertEqual(response.status_code, 302)
        req = LocationRequest.objects.get()
        self.assertEqual(req.status, "PENDING")
        self.assertEqual(self.submit(spots=[self.mine.spot]).status_code, 200)  # not bookable yet
        services.review_location_request(req, self.users["manager"], "approve")
        self.mine.spot.refresh_from_db()
        self.assertEqual(self.mine.spot.mode, SpotProfile.MODE_LISTED)
        campaign = self.submitted_campaign(spots=[self.mine.spot])
        self.assertEqual(campaign.ads.get().placements.get().terms.rate_per_view, Decimal("0.80"))

    def test_owner_cannot_list_someone_elses_spot(self):
        self.client.force_login(self.users["owner"])
        response = self.client.post(
            reverse("portal_locations", args=["owner"]),
            {"form": "list", "list-asset_id": self.private_other.pk, "list-town": self.kochi.pk},
        )
        self.assertEqual(response.status_code, 404)
        self.assertFalse(LocationRequest.objects.exists())

    def test_install_request_flow_creates_the_owners_spot(self):
        self.client.force_login(self.users["owner"])
        response = self.client.post(
            reverse("portal_locations", args=["owner"]),
            {
                "form": "install",
                "new-name": "New shop",
                "new-town": self.kochi.pk,
                "new-address": "MG Road",
                "new-contact_phone": "9999999999",
                "new-notes": "",
            },
        )
        self.assertEqual(response.status_code, 302)
        req = LocationRequest.objects.get()
        manager = self.users["manager"]
        services.review_location_request(req, manager, "approve")
        services.review_location_request(req, manager, "start_install")
        services.review_location_request(req, manager, "complete")
        req.refresh_from_db()
        self.assertEqual(req.status, "COMPLETED")
        self.assertEqual(req.asset.partner, self.users["owner"])
        self.assertEqual(req.asset.spot.town, self.kochi)
        self.assertEqual(req.asset.spot.mode, SpotProfile.MODE_PRIVATE)

    # -- permissions --------------------------------------------------------

    def test_pages_are_limited_to_the_right_roles(self):
        cases = [
            ("customer", "portal_submissions", 403),
            ("owner", "portal_settings", 403),
            ("manager", "portal_settings", 403),
            ("customer", "portal_earnings", 403),
            ("admin", "portal_ad_create", 403),
            ("manager", "portal_withdrawals", 403),
            ("manager", "portal_submissions", 200),
            ("manager", "portal_location_requests", 200),
            ("admin", "portal_settings", 200),
            ("admin", "portal_withdrawals", 200),
            ("admin", "portal_wallets", 200),
            ("admin", "portal_spots", 200),
            ("customer", "portal_ad_create", 200),
            ("owner", "portal_ad_create", 200),
            ("owner", "portal_earnings", 200),
        ]
        for role, name, status in cases:
            self.client.force_login(self.users[role])
            self.assertEqual(self.client.get(reverse(name, args=[role])).status_code, status, (role, name))

    def test_posting_admin_actions_as_other_roles_does_nothing(self):
        self.client.force_login(self.users["owner"])
        response = self.client.post(reverse("portal_wallets", args=["owner"]), {"username": "owner", "amount": "999"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(Wallet.objects.get(user=self.users["owner"]).balance, Decimal("1000"))

    def test_admin_can_save_pricing_and_plans(self):
        self.client.force_login(self.users["admin"])
        url = reverse("portal_settings", args=["admin"])
        form = self.client.get(url).context["form"]
        data = {f"s-{name}": form[name].value() for name in form.fields if form[name].value() is not None}
        data["s-company_rate_per_view"] = "0.75"
        data["s-require_authentic_device"] = "on"
        data.update({"p-TOTAL_FORMS": "1", "p-INITIAL_FORMS": "1", "p-MIN_NUM_FORMS": "0", "p-MAX_NUM_FORMS": "1000"})
        data.update({"p-0-id": self.plan.pk, "p-0-name": "Basic", "p-0-monthly_price": "150", "p-0-max_campaigns": "5",
                     "p-0-max_ads": "5", "p-0-is_active": "on"})
        response = self.client.post(url, data)
        self.assertEqual(response.status_code, 302, getattr(response, "context", None) and response.context["form"].errors)
        self.assertEqual(MarketplaceSettings.load().company_rate_per_view, Decimal("0.75"))
        self.plan.refresh_from_db()
        self.assertEqual(self.plan.monthly_price, Decimal("150"))

    def test_rates_with_sub_paisa_precision_are_refused(self):
        from .forms import SettingsForm

        form = SettingsForm({"company_rate_per_view": "0.555"}, instance=MarketplaceSettings.load())
        self.assertFalse(form.is_valid())
        self.assertIn("company_rate_per_view", form.errors)

    def test_admin_adds_funds_to_a_wallet(self):
        self.client.force_login(self.users["admin"])
        response = self.client.post(
            reverse("portal_wallets", args=["admin"]),
            {"username": "customer", "amount": "250", "reference": "UPI-1"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Wallet.objects.get(user=self.users["customer"]).balance, Decimal("1250"))

    # -- device authentication ----------------------------------------------

    def test_device_endpoints_require_a_valid_key_and_only_list_approved_ads(self):
        client = Client()
        self.assertEqual(client.get("/device/v1/manifest/").status_code, 401)
        self.assertEqual(client.get("/device/v1/manifest/", HTTP_AUTHORIZATION="Bearer wsd_00000000_bad").status_code, 401)

        device, token = services.issue_device_token(self.hosted)
        self.assertNotIn(token, device.token_hash)
        auth = {"HTTP_AUTHORIZATION": f"Bearer {token}"}
        self.assertEqual(client.get("/device/v1/ping/", **auth).status_code, 200)

        campaign = self.submitted_campaign()
        self.assertEqual(client.get("/device/v1/manifest/", **auth).json()["ads"], [])
        self.go_live(campaign)
        ads = client.get("/device/v1/manifest/", **auth).json()["ads"]
        self.assertEqual([a["ad_id"] for a in ads], [campaign.ads.get().pk])

    def test_a_spots_key_cannot_read_another_spots_ads_and_revoked_keys_stop_working(self):
        campaign = self.submitted_campaign()
        self.go_live(campaign)
        _, other_token = services.issue_device_token(self.mine)
        client = Client()
        response = client.get("/device/v1/manifest/", HTTP_AUTHORIZATION=f"Bearer {other_token}")
        self.assertEqual(response.json()["ads"], [])
        self.client.force_login(self.users["admin"])
        self.client.post(reverse("portal_device_revoke", args=["admin", self.mine.spot.pk]))
        self.assertEqual(client.get("/device/v1/ping/", HTTP_AUTHORIZATION=f"Bearer {other_token}").status_code, 401)

    def test_rotating_a_key_invalidates_the_old_one(self):
        _, old = services.issue_device_token(self.hosted)
        _, new = services.issue_device_token(self.hosted)
        client = Client()
        self.assertEqual(client.get("/device/v1/ping/", HTTP_AUTHORIZATION=f"Bearer {old}").status_code, 401)
        self.assertEqual(client.get("/device/v1/ping/", HTTP_AUTHORIZATION=f"Bearer {new}").status_code, 200)
        self.assertEqual(SpotDevice.objects.filter(asset=self.hosted).count(), 1)

    def test_device_login_attempts_are_rate_limited(self):
        client = Client()
        codes = [client.get("/device/v1/ping/", HTTP_AUTHORIZATION="Bearer wsd_aaaaaaaa_x").status_code for _ in range(14)]
        self.assertEqual(codes[0], 401)
        self.assertEqual(codes[-1], 429)

    # -- click redirect -----------------------------------------------------

    def test_click_redirect_never_leaves_for_non_web_schemes(self):
        campaign = self.submitted_campaign()
        self.go_live(campaign)
        ad = campaign.ads.get()
        serve_ad_for_asset("hosted", visitor_token="x", request_meta=FAS)
        session = AdServeSession.objects.get()
        Ad.objects.filter(pk=ad.pk).update(target_url="javascript:alert(1)")
        response = Client().get(f"/ad-click/{session.session_id}/")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/")
        Ad.objects.filter(pk=ad.pk).update(target_url="https://example.com/ok")
        self.assertEqual(Client().get(f"/ad-click/{session.session_id}/")["Location"], "https://example.com/ok")
