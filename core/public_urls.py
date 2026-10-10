from django.urls import include, path
from . import public_views

urlpatterns = [
    path("", include("website.urls")),
    path("accounts/login/", public_views.sign_in, name="account_login"),
    path("login/", public_views.sign_in, name="login"),
    path("portal/<slug:role>/", public_views.workspace_redirect),
    path(
        "portal/<slug:role>/campaigns/new/",
        public_views.workspace_redirect,
        {"action": "campaigns/new"},
    ),
    path("management/", public_views.manager_redirect),
    path("management/<path:path>", public_views.manager_redirect),
    path("", include("core.fas_urls")),
]
