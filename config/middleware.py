from .host_routing import is_development_host, workspace_role


class SubdomainURLRoutingMiddleware:
    """Resolve FAS before ERP routing without altering authentication state."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
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
