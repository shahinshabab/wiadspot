from django.urls import path

from . import device_api, views

# Workspace pages; mounted next to the existing portal/<role>/ routes.
urlpatterns = [
    path("portal/<slug:role>/ads/new/", views.ad_create, name="portal_ad_create"),
    path("portal/<slug:role>/earnings/", views.owner_earnings, name="portal_earnings"),
    path("portal/<slug:role>/submissions/", views.submissions, name="portal_submissions"),
    path("portal/<slug:role>/location-requests/", views.location_requests, name="portal_location_requests"),
    path("portal/<slug:role>/settings/", views.admin_settings, name="portal_settings"),
    path("portal/<slug:role>/withdrawals/", views.admin_withdrawals, name="portal_withdrawals"),
    path("portal/<slug:role>/wallets/", views.admin_wallets, name="portal_wallets"),
    path("portal/<slug:role>/spots/", views.admin_spots, name="portal_spots"),
    path("portal/<slug:role>/spots/<int:pk>/", views.admin_spot_edit, name="portal_spot_edit"),
    path("portal/<slug:role>/spots/<int:pk>/revoke/", views.admin_device_revoke, name="portal_device_revoke"),
]

# Machine endpoints for the spots themselves; reachable on any host.
device_urlpatterns = [
    path("device/v1/ping/", device_api.ping, name="device_ping"),
    path("device/v1/manifest/", device_api.manifest, name="device_manifest"),
]
