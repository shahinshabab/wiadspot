"""Trusted workspace addresses; ports do not change the selected channel."""

from django.conf import settings

ROLE_SUBDOMAINS = {
    "customer": "client",
    "owner": "owner",
    "manager": "manager",
    "admin": "admin",
}
SUBDOMAIN_ROLES = {host: role for role, host in ROLE_SUBDOMAINS.items()}
# Preserve existing bookmarks and gateway hosts.
SUBDOMAIN_ROLES.update(clients="customer", partner="owner", ads="manager")
DEVELOPMENT_HOSTS = {"localhost", "127.0.0.1", "testserver"}


def hostname(request):
    return request.get_host().split(":", 1)[0].lower()


def workspace_role(request):
    host = hostname(request)
    for domain in ("wiadspot.com", "wiadspot.local"):
        suffix = "." + domain
        if host.endswith(suffix):
            return SUBDOMAIN_ROLES.get(host[: -len(suffix)])
    return None


def is_development_host(request):
    return settings.DEBUG and hostname(request) in DEVELOPMENT_HOSTS


def site_address(request, role=None):
    """Return fixed destinations, never a user-supplied next URL."""
    host = hostname(request)
    if is_development_host(request):
        return request.build_absolute_uri("/").rstrip("/")
    local = host == "wiadspot.local" or host.endswith(".wiadspot.local")
    domain = "wiadspot.local" if local else "wiadspot.com"
    port = request.get_host().partition(":")[2]
    if local and port and port not in ("80", "443"):
        domain += ":" + port
    prefix = ROLE_SUBDOMAINS[role] + "." if role else ""
    return ("http" if local else "https") + "://" + prefix + domain


def sign_in_address(request, role):
    address = site_address(request, role) + "/accounts/login/"
    if is_development_host(request):
        address += "?role=" + role
    return address
