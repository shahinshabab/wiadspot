from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET
from config.host_routing import sign_in_address, site_address
from .portal_views import role_details


@require_GET
def sign_in(request):
    role = request.GET.get("role")
    if role:
        role_details(role)
        return redirect(sign_in_address(request, role))
    return render(request, "platform/sign_in_options.html")


@require_GET
def workspace_redirect(request, role, action=""):
    role_details(role)
    suffix = "campaigns/new/" if action == "campaigns/new" else ""
    return redirect(site_address(request, role) + f"/portal/{role}/" + suffix)


@require_GET
def manager_redirect(request, path=""):
    return redirect(site_address(request, "manager") + "/management/" + path)
