#core/urls.py
from django.urls import path, include
from .views import (
    home,
    fas,
    ad_click_redirect,
    review_queue,
    campaign_list,
    campaign_review,
    ad_review,
    placement_review,
    performance_report,
)

app_name = "ads"

urlpatterns = [
    path("", include("core.auth_urls")),

    path("", home, name="home"),
    path("reviews/", review_queue, name="review_queue"),
    path("campaigns/", campaign_list, name="campaign_list"),
    path("campaign/<int:pk>/<str:action>/", campaign_review, name="campaign_review"),
    path("ad/<int:pk>/<str:action>/", ad_review, name="ad_review"),
    path("placement/<int:pk>/<str:action>/", placement_review, name="placement_review"),
    path("reports/performance/", performance_report, name="performance_report"),

    path("fas/<int:assetid>/", fas, name="fas"),
    path("ad-click/<uuid:session_id>/", ad_click_redirect, name="ad_click_redirect"),
]