from django.urls import include, path
from .views import home

urlpatterns = [
    path("", include("core.auth_urls")),
    path("", home, name="admin_home"),
]