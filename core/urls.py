#core/urls.py
from django.contrib import admin
from django.urls import include, path
from .views import login_view, logout_view

urlpatterns = [
    path("", include("website.urls")),
    path("secure-django-admin/", admin.site.urls),
    path("login/", login_view, name="login"),
    path("logout/", logout_view, name="logout"),
]