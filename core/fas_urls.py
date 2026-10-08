"""Captive-portal aliases reuse the existing pool and OTP implementation."""

from django.conf import settings
from django.conf.urls.static import static
from django.urls import path
from ads.views import fas, ad_click_redirect

urlpatterns = [
    path("fas/", fas, name="fas_gateway"),
    path("fas/<int:assetid>/", fas, name="fas"),
    path("wiadspot/fas/", fas, name="wiadspot_fas_gateway"),
    path("wiadspot/fas/<int:assetid>/", fas, name="wiadspot_fas"),
    path("ad-click/<uuid:session_id>/", ad_click_redirect, name="fas_ad_click"),
    path(
        "wiadspot/ad-click/<uuid:session_id>/",
        ad_click_redirect,
        name="wiadspot_fas_ad_click",
    ),
]
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
