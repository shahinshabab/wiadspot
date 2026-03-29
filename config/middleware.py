from django.urls import set_urlconf
from .host_routing import HOST_URLCONF_MAP


class SubdomainURLRoutingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        host = request.get_host().split(":")[0].lower()
        request.urlconf = HOST_URLCONF_MAP.get(host, "config.urls")
        set_urlconf(request.urlconf)

        response = self.get_response(request)
        set_urlconf(None)
        return response