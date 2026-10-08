"""Expose existing review tools without adding or modifying FAS endpoints."""

from django.urls import path
from functools import wraps
from ads import views
from .portal_views import authorize, dashboard


def manager_view(view):
    @wraps(view)
    def guarded(request, *args, **kwargs):
        response = authorize(request, "manager")
        return response or view(request, *args, **kwargs)

    return guarded


app_name = "ads"
urlpatterns = [
    path("", dashboard, {"role": "manager"}, name="home"),
    path("reviews/", manager_view(views.review_queue), name="review_queue"),
    path("campaigns/", manager_view(views.campaign_list), name="campaign_list"),
    path(
        "campaign/<int:pk>/<str:action>/",
        manager_view(views.campaign_review),
        name="campaign_review",
    ),
    path("ad/<int:pk>/<str:action>/", manager_view(views.ad_review), name="ad_review"),
    path(
        "placement/<int:pk>/<str:action>/",
        manager_view(views.placement_review),
        name="placement_review",
    ),
    path("reports/", manager_view(views.performance_report), name="performance_report"),
]
