"""Public pages, workspace hosts and the real ad pool remain independent."""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import resolve
from django.http import HttpResponse
from unittest.mock import patch
from ads.models import (
    Ad,
    AdEventLog,
    AdServeSession,
    Asset,
    Campaign,
    MetricPricing,
    Placement,
)
from ads.views import fas
from website.models import ContactMessage
from .portal_views import ROLES

HOSTS = {
    "customer": "client.wiadspot.com",
    "owner": "owner.wiadspot.com",
    "manager": "manager.wiadspot.com",
    "admin": "admin.wiadspot.com",
}


@override_settings(DEBUG=True)
class ChannelRoutingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.users = {}
        for role, details in ROLES.items():
            user = get_user_model().objects.create_user(
                role, password="channel-test-password"
            )
            user.groups.add(Group.objects.create(name=details["group"]))
            cls.users[role] = user
        cls.asset = Asset.objects.create(
            name="Gateway café",
            code="gateway-cafe",
            owner_type="ADMIN",
            admin=cls.users["admin"],
        )
        campaign = Campaign.objects.create(
            name="Live pool campaign",
            owner=cls.users["admin"],
            status="ACTIVE",
            review_status="APPROVED",
        )
        cls.ad = Ad.objects.create(
            campaign=campaign,
            owner=cls.users["admin"],
            title="Pool poster",
            ad_type="IMAGE",
            status="APPROVED",
            media_file="ads/pool-poster.png",
            target_url="https://example.com/poster",
        )
        Placement.objects.create(
            asset=cls.asset,
            ad=cls.ad,
            status="APPROVED",
            serving_enabled=True,
            approved_by=cls.users["admin"],
        )
        MetricPricing.objects.create(name="Test pricing", is_active=True)

    def test_public_pages_and_articles_have_two_workspaces(self):
        for path in (
            "/",
            "/about/",
            "/contact/",
            "/articles/",
            "/career/",
            "/articles/read/captive-portal-101/",
        ):
            with self.subTest(path=path):
                response = self.client.get(path, HTTP_HOST="wiadspot.com")
                self.assertEqual(response.status_code, 200)
                self.assertContains(
                    response, 'href="https://client.wiadspot.com/accounts/login/"'
                )
                self.assertContains(
                    response, 'href="https://owner.wiadspot.com/accounts/login/"'
                )
                self.assertNotContains(response, 'href="https://manager.wiadspot.com')
                self.assertNotContains(response, 'href="https://admin.wiadspot.com')
        self.assertEqual(
            self.client.get(
                "/articles/read/missing/", HTTP_HOST="wiadspot.com"
            ).status_code,
            404,
        )

    def test_public_sign_in_chooses_destination_without_accepting_credentials(self):
        self.assertContains(
            self.client.get("/accounts/login/", HTTP_HOST="wiadspot.com"),
            "Choose your account",
        )
        for role, host in HOSTS.items():
            response = self.client.get(
                "/accounts/login/",
                {"role": role, "next": "https://evil.example"},
                HTTP_HOST="wiadspot.com",
            )
            self.assertEqual(response.url, f"https://{host}/accounts/login/")
        self.assertEqual(
            self.client.post(
                "/accounts/login/",
                {
                    "role": "admin",
                    "username": "admin",
                    "password": "channel-test-password",
                },
                HTTP_HOST="wiadspot.com",
            ).status_code,
            405,
        )
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_public_private_links_redirect_to_the_correct_workspace(self):
        response = self.client.get("/portal/owner/", HTTP_HOST="wiadspot.com")
        self.assertEqual(response.url, "https://owner.wiadspot.com/portal/owner/")
        response = self.client.get("/management/reviews/", HTTP_HOST="wiadspot.com")
        self.assertEqual(
            response.url, "https://manager.wiadspot.com/management/reviews/"
        )
        self.assertEqual(
            self.client.post(
                "/management/reviews/", HTTP_HOST="wiadspot.com"
            ).status_code,
            405,
        )
        self.assertEqual(
            self.client.get(
                "/secure-django-admin/", HTTP_HOST="wiadspot.com"
            ).status_code,
            404,
        )

    def test_all_workspaces_require_sign_in_at_the_root(self):
        for role, host in HOSTS.items():
            response = self.client.get("/", HTTP_HOST=host)
            self.assertEqual(response.status_code, 302)
            self.assertTrue(response.url.startswith("/accounts/login/"))
            response = self.client.get("/accounts/login/", HTTP_HOST=host)
            self.assertEqual(response.context["role"], role)
            self.assertContains(response, "Back to website")
            self.assertContains(response, 'href="https://wiadspot.com/contact/"')
            self.assertNotContains(response, 'class="role-chooser"')
            self.assertEqual(
                self.client.get("/about/", HTTP_HOST=host).status_code, 404
            )

    def test_legacy_manager_paths_stay_protected_on_manager_hosts(self):
        for host in (HOSTS["manager"], "ads.wiadspot.com"):
            self.assertEqual(
                self.client.get("/reviews/", HTTP_HOST=host).status_code, 302
            )
        self.client.force_login(self.users["manager"])
        for host in (HOSTS["manager"], "ads.wiadspot.com"):
            self.assertEqual(
                self.client.get("/reviews/", HTTP_HOST=host).status_code, 200
            )
        self.assertEqual(
            self.client.get("/reviews/", HTTP_HOST=HOSTS["customer"]).status_code, 404
        )

    def test_role_switches_in_url_form_and_manager_routes_are_denied(self):
        self.users["customer"].groups.add(Group.objects.get(name="Manager"))
        self.client.force_login(self.users["customer"])
        for path in (
            "/portal/manager/",
            "/management/",
            "/management/reviews/",
            "/accounts/login/?role=admin",
        ):
            self.assertEqual(
                self.client.get(path, HTTP_HOST=HOSTS["customer"]).status_code, 403
            )
        response = self.client.post(
            "/accounts/login/",
            {"role": "admin", "username": "admin", "password": "channel-test-password"},
            HTTP_HOST=HOSTS["customer"],
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            self.client.session["_auth_user_id"], str(self.users["customer"].pk)
        )

    def test_each_role_can_sign_in_and_wrong_users_cannot(self):
        for role, host in HOSTS.items():
            client = Client()
            response = client.post(
                "/accounts/login/",
                {"username": role, "password": "channel-test-password"},
                HTTP_HOST=host,
            )
            self.assertEqual(response.url, f"/portal/{role}/")
            self.assertEqual(client.get("/", HTTP_HOST=host).status_code, 200)
            wrong = "owner" if role == "customer" else "customer"
            client = Client()
            response = client.post(
                "/accounts/login/",
                {"username": wrong, "password": "channel-test-password"},
                HTTP_HOST=host,
            )
            self.assertContains(response, "credentials or account type are incorrect")
            self.assertNotIn("_auth_user_id", client.session)

    def test_copied_cookie_cannot_change_workspace_even_for_multirole_user(self):
        self.users["customer"].groups.add(Group.objects.get(name="Admin"))
        self.client.post(
            "/accounts/login/",
            {"username": "customer", "password": "channel-test-password"},
            HTTP_HOST=HOSTS["customer"],
        )
        self.assertEqual(
            self.client.get("/portal/admin/", HTTP_HOST=HOSTS["admin"]).status_code, 403
        )
        self.assertEqual(
            self.client.get(
                "/portal/customer/", HTTP_HOST=HOSTS["customer"]
            ).status_code,
            200,
        )

    def test_public_browsing_and_wrong_workspace_leave_existing_session_unchanged(self):
        self.client.post(
            "/accounts/login/",
            {"username": "customer", "password": "channel-test-password"},
            HTTP_HOST=HOSTS["customer"],
        )
        session = dict(self.client.session)
        self.assertEqual(
            self.client.get("/", HTTP_HOST="wiadspot.com").status_code, 200
        )
        self.assertEqual(
            self.client.get("/portal/owner/", HTTP_HOST=HOSTS["owner"]).status_code, 403
        )
        self.assertEqual(dict(self.client.session), session)

    def test_logout_is_post_only_and_returns_to_public_site(self):
        self.client.force_login(self.users["owner"])
        self.assertEqual(
            self.client.get("/logout/", HTTP_HOST=HOSTS["owner"]).status_code, 405
        )
        response = self.client.post("/accounts/logout/", HTTP_HOST=HOSTS["owner"])
        self.assertEqual(response.url, "https://wiadspot.com/")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_local_subdomains_keep_the_current_port_and_legacy_aliases(self):
        response = self.client.get("/", HTTP_HOST="wiadspot.local:8010")
        self.assertContains(
            response, "http://owner.wiadspot.local:8010/accounts/login/"
        )
        for host, role in (
            ("clients.wiadspot.local:8010", "customer"),
            ("partner.wiadspot.com", "owner"),
            ("ads.wiadspot.com", "manager"),
        ):
            self.assertEqual(
                self.client.get("/accounts/login/", HTTP_HOST=host).context["role"],
                role,
            )

    @override_settings(DEBUG=False, SESSION_COOKIE_SECURE=True, CSRF_COOKIE_SECURE=True)
    def test_production_cookies_are_host_only_secure_and_csrf_is_same_origin(self):
        client = Client(enforce_csrf_checks=True)
        response = client.get(
            "/accounts/login/", HTTP_HOST=HOSTS["customer"], secure=True
        )
        token = response.cookies["csrftoken"].value
        self.assertEqual(response.cookies["csrftoken"]["domain"], "")
        self.assertTrue(response.cookies["csrftoken"]["secure"])
        data = {
            "username": "customer",
            "password": "channel-test-password",
            "csrfmiddlewaretoken": token,
        }
        self.assertEqual(
            client.post(
                "/accounts/login/",
                data,
                HTTP_HOST=HOSTS["customer"],
                HTTP_ORIGIN="https://owner.wiadspot.com",
                secure=True,
            ).status_code,
            403,
        )
        self.assertEqual(
            client.post(
                "/accounts/login/",
                data,
                HTTP_HOST=HOSTS["customer"],
                HTTP_ORIGIN="https://wiadspot.com",
                secure=True,
            ).status_code,
            403,
        )
        response = client.post(
            "/accounts/login/",
            data,
            HTTP_HOST=HOSTS["customer"],
            HTTP_ORIGIN="https://client.wiadspot.com",
            secure=True,
        )
        self.assertEqual(response.status_code, 302)
        cookie = response.cookies["sessionid"]
        self.assertEqual(cookie["domain"], "")
        self.assertTrue(cookie["secure"])
        self.assertTrue(cookie["httponly"])
        self.assertEqual(
            client.get("/accounts/login/", HTTP_HOST="localhost", secure=True)
            .context["request"]
            .urlconf,
            "core.public_urls",
        )

    def test_real_pool_serves_without_login_and_under_every_erp_role(self):
        count = 0
        for role in (None, *HOSTS):
            client = Client()
            if role:
                client.force_login(self.users[role])
            session = dict(client.session)
            for host in ("wiadspot.com", *HOSTS.values()):
                for path in (
                    f"/fas/{self.asset.pk}/",
                    f"/wiadspot/fas/{self.asset.pk}/",
                    "/fas/",
                    "/wiadspot/fas/",
                ):
                    with self.subTest(role=role, host=host, path=path):
                        response = client.get(
                            path,
                            {"gatewayname": self.asset.code, "tok": "gateway-visitor"},
                            HTTP_HOST=host,
                        )
                        self.assertEqual(response.status_code, 200)
                        self.assertTemplateUsed(response, "fas/login.html")
                        self.assertEqual(
                            response.context["ad_payload"]["ad_id"], self.ad.pk
                        )
                        self.assertEqual(
                            AdServeSession.objects.latest("served_at").visitor_token,
                            "gateway-visitor",
                        )
                        self.assertEqual(dict(client.session), session)
                        count += 1
        self.assertEqual(AdServeSession.objects.count(), count)
        self.assertEqual(
            AdEventLog.objects.filter(event_type="IMPRESSION").count(), count
        )

    def test_fas_aliases_point_to_the_original_view_and_dispatch_authmon(self):
        for prefix in ("/fas/", "/wiadspot/fas/"):
            path = f"{prefix}{self.asset.pk}/"
            self.assertIs(resolve(path, urlconf="core.fas_urls").func, fas)
            # Verify routing delegation without changing the existing AuthMon code.
            with patch(
                "ads.views.handle_authmon_inline",
                return_value=HttpResponse("gateway response"),
            ) as authmon:
                response = self.client.get(
                    path, {"auth_get": "dump"}, HTTP_HOST=HOSTS["owner"]
                )
                self.assertEqual(response.content, b"gateway response")
                self.assertEqual(authmon.call_args.args[1], self.asset.pk)

    def test_pool_click_alias_records_event_without_erp_login(self):
        self.client.get(
            f"/wiadspot/fas/{self.asset.pk}/",
            {"tok": "gateway-visitor"},
            HTTP_HOST="wiadspot.com",
        )
        session = AdServeSession.objects.get()
        response = self.client.get(
            f"/wiadspot/ad-click/{session.session_id}/", HTTP_HOST="wiadspot.com"
        )
        self.assertEqual(response.url, "https://example.com/poster")
        self.assertEqual(AdEventLog.objects.filter(event_type="CLICK").count(), 1)

    def test_contact_validation_returns_errors_instead_of_crashing(self):
        cache.clear()
        data = {
            "name": "Visitor",
            "email": "visitor@example.com",
            "message": "https://spam.example",
            "website": "",
        }
        self.assertContains(
            self.client.post("/contact/", data, HTTP_HOST="wiadspot.com"),
            "Please remove links",
        )
        data.update(message="Hello WiadSpot", website="spam")
        self.assertContains(
            self.client.post("/contact/", data, HTTP_HOST="wiadspot.com"),
            "Spam detected",
        )
        self.assertEqual(ContactMessage.objects.count(), 0)
        data["website"] = ""
        self.assertEqual(
            self.client.post("/contact/", data, HTTP_HOST="wiadspot.com").status_code,
            302,
        )
        self.assertEqual(ContactMessage.objects.count(), 1)
        cache.clear()
