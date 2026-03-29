from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.shortcuts import redirect, render
from .role_utils import get_user_role


PORTAL_ROLE_MAP = {
    "admin": "Admin",
    "ads": "Manager",
    "clients": "Client",
    "partner": "Partner",
}


PORTAL_HOME_MAP = {
    "admin": "admin_home",
    "ads": "ads_home",
    "clients": "clients_home",
    "partner": "partner_home",
}


def get_portal_from_host(request):
    host = request.get_host().split(":")[0].lower()

    if host.startswith("admin."):
        return "admin"
    elif host.startswith("ads."):
        return "ads"
    elif host.startswith("clients."):
        return "clients"
    elif host.startswith("partner."):
        return "partner"

    return None


def login_view(request):
    if request.user.is_authenticated:
        return redirect_user_by_host(request, request.user)

    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "").strip()

        user = authenticate(request, username=username, password=password)

        if user is None:
            messages.error(request, "Invalid username or password.")
            return render(request, "auth/login.html")

        login(request, user)
        return redirect_user_by_host(request, user)

    return render(request, "auth/login.html")


def redirect_user_by_host(request, user):
    portal = get_portal_from_host(request)
    user_role = get_user_role(user)

    if portal is None:
        messages.error(request, "Unknown portal.")
        logout(request)
        return redirect("login")

    allowed_role = PORTAL_ROLE_MAP.get(portal)

    if user_role == allowed_role:
        return redirect(PORTAL_HOME_MAP[portal])

    messages.error(request, f"You do not have access to the {portal} portal.")
    logout(request)
    return redirect("login")


def logout_view(request):
    logout(request)
    return redirect("login")