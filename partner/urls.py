from django.urls import include, path
from .views import home

urlpatterns = [
    path("", home, name="partner_home"),
    path("", include("config.auth_urls")),
]