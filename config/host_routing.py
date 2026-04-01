# config/host_routing.py

HOST_URLCONF_MAP = {
    "partner.wiadspot.local:8000": "partner.urls",
    "clients.wiadspot.local:8000": "clients.urls",
    "admin.wiadspot.local:8000": "dashboard_admin.urls",
    "ads.wiadspot.local:8000": "ads.urls",
    "wiadspot.local:8000": "config.urls",
    "www.wiadspot.local:8000": "config.urls",

    # production domains
    "partner.wiadspot.com": "partner.urls",
    "clients.wiadspot.com": "clients.urls",
    "admin.wiadspot.com": "dashboard_admin.urls",
    "ads.wiadspot.com": "ads.urls",
    "wiadspot.com": "config.urls",
    "www.wiadspot.com": "config.urls",
}