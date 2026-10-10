from django.urls import set_script_prefix

from .host_routing import (
    SUBDOMAIN_ROLES,
    is_development_host,
    is_ip_host,
    split_ip_workspace,
    workspace_role,
)


class SubdomainURLRoutingMiddleware:
    """Resolve FAS before ERP routing without altering authentication state."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if is_ip_host(request):
            # IP access: /client/, /owner/, ... replace the subdomains.
            name, prefix, rest = split_ip_workspace(request.path_info)
            request.workspace_role = SUBDOMAIN_ROLES.get(name)
            if prefix:
                request.path_info = rest
                request.path = prefix + rest
            # reverse() and redirect() now emit /owner/... style URLs.
            set_script_prefix(request.META.get("SCRIPT_NAME", "").rstrip("/") + prefix + "/")
        else:
            request.workspace_role = workspace_role(request)
        request.development_workspace = is_development_host(request)
        if request.path_info.startswith(
            ("/fas/", "/wiadspot/fas/", "/ad-click/", "/wiadspot/ad-click/")
        ):
            request.urlconf = "core.fas_urls"
        elif request.development_workspace:
            request.urlconf = "core.urls"
        elif request.workspace_role == "admin":
            request.urlconf = "core.admin_urls"
        elif request.workspace_role == "manager":
            request.urlconf = "core.manager_urls"
        elif request.workspace_role:
            request.urlconf = "core.workspace_urls"
        else:
            request.urlconf = "core.public_urls"
        return self.get_response(request)
