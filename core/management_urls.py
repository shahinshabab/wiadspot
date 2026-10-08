"""Expose existing review tools without adding or modifying FAS endpoints."""

from django.urls import path
from ads import views
from .portal_views import dashboard

app_name = "ads"
urlpatterns = [
    path("", dashboard, {"role": "manager"}, name="home"),
    path("reviews/", views.review_queue, name="review_queue"),
    path("campaigns/", views.campaign_list, name="campaign_list"),
    path(
        "campaign/<int:pk>/<str:action>/", views.campaign_review, name="campaign_review"
    ),
    path("ad/<int:pk>/<str:action>/", views.ad_review, name="ad_review"),
    path(
        "placement/<int:pk>/<str:action>/",
        views.placement_review,
        name="placement_review",
    ),
    path("reports/", views.performance_report, name="performance_report"),
]
