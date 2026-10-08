from config.host_routing import site_address, sign_in_address


def site_links(request):
    return {
        "public_site_url": site_address(request),
        "client_login_url": sign_in_address(request, "customer"),
        "owner_login_url": sign_in_address(request, "owner"),
        "workspace_host_role": getattr(request, "workspace_role", None),
    }
