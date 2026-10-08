# config/middleware.py

from django.conf import settings
from .host_routing import HOST_URLCONF_MAP


class SubdomainURLRoutingMiddleware:
    """
    Switch urlconf dynamically based on request host.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        host = request.get_host().lower()

        # fallback to main site
        if request.path_info.startswith(("/accounts/", "/portal/", "/management/")):
            request.urlconf = settings.ROOT_URLCONF
        else:
            request.urlconf = HOST_URLCONF_MAP.get(host, settings.ROOT_URLCONF)

        response = self.get_response(request)
        return response
