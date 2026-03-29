from django.urls import include, path
from .views import home

urlpatterns = [
    path("", home, name="ads_home"),
    path("", include("config.auth_urls")),
]