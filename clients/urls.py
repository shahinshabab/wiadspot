from django.urls import include, path
from .views import home

urlpatterns = [
    path("", home, name="clients_home"),
    path("", include("config.auth_urls")),
]