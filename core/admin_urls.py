from django.contrib import admin
from django.urls import path
from .workspace_urls import urlpatterns as workspace_patterns

urlpatterns = [*workspace_patterns, path("secure-django-admin/", admin.site.urls)]
