"""Keep the original manager paths as aliases on the manager/ads hosts."""

from django.urls import include, path
from .workspace_urls import urlpatterns as workspace_patterns
from . import management_urls

urlpatterns = [
    *workspace_patterns,
    path("", include((management_urls.urlpatterns, "legacy_ads"))),
]
