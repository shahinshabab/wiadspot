from django.urls import include, path
from .views import home

urlpatterns = [
    path("", include("config.auth_urls")),
    path("", home, name="admin_home"),
]