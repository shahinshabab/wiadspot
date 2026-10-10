from django.urls import set_script_prefix

from .host_routing import (
    is_development_host,
    path_mode,
    split_workspace_path,
    workspace_role,
)


class SubdomainURLRoutingMiddleware:
    """Resolve FAS before ERP routing without altering authentication state.

    The workspace comes from the subdomain, or from a leading /client/,
    /owner/, /manager/ or /admin/ path segment when ROUTING_MODE is "path".
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.workspace_role = workspace_role(request)
        if path_mode():
            prefix, _, remaining = split_workspace_path(request.path_info)
            if prefix:
                # Route as if mounted at the root, but build URLs with the prefix.
                request.path_info = remaining
                set_script_prefix("/" + prefix + "/")
        request.development_workspace = (
            is_development_host(request) and not request.workspace_role
        )
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
