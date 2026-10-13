"""Private workspaces do not mount the public website."""

from django.conf import settings
from django.conf.urls.static import static
from django.urls import include, path
from marketplace.urls import urlpatterns as marketplace_patterns
from . import management_urls, portal_views

urlpatterns = [
    path("", portal_views.workspace_home, name="workspace_home"),
    path("accounts/login/", portal_views.account_login, name="account_login"),
    path("accounts/logout/", portal_views.account_logout, name="account_logout"),
    path("login/", portal_views.account_login, name="login"),
    path("logout/", portal_views.account_logout, name="logout"),
    path("portal/<slug:role>/", portal_views.dashboard, name="portal_dashboard"),
    path("portal/<slug:role>/campaigns/", portal_views.campaigns_page, name="portal_campaigns"),
    path("portal/<slug:role>/locations/", portal_views.locations_page, name="portal_locations"),
    path("portal/<slug:role>/billing/", portal_views.billing_page, name="portal_billing"),
    path("portal/<slug:role>/profile/", portal_views.profile_page, name="portal_profile"),
    path(
        "portal/<slug:role>/campaigns/new/",
        portal_views.create_campaign,
        name="portal_campaign_create",
    ),
    *marketplace_patterns,
    path("management/", include("core.management_urls")),
    path("management/", include((management_urls.urlpatterns, None))),
]
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
