# core/urls.py
from django.contrib import admin
from django.urls import include, path
from .views import login_view, logout_view
from . import portal_views
from django.conf import settings
from django.conf.urls.static import static
from . import management_urls

urlpatterns = [
    # Existing manager templates use both plain and ads-prefixed URL names.
    path("management/", include("core.management_urls")),
    path("management/", include((management_urls.urlpatterns, None))),
    path("accounts/login/", portal_views.account_login, name="account_login"),
    path("accounts/logout/", portal_views.account_logout, name="account_logout"),
    path("portal/<slug:role>/", portal_views.dashboard, name="portal_dashboard"),
    path(
        "portal/<slug:role>/campaigns/new/",
        portal_views.create_campaign,
        name="portal_campaign_create",
    ),
    path("", include("website.urls")),
    path("secure-django-admin/", admin.site.urls),
    path("login/", login_view, name="login"),
    path("logout/", logout_view, name="logout"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
