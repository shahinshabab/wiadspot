from django.urls import include, path
from .views import home, fas, ad_click_redirect

urlpatterns = [
    path("", home, name="ads_home"),
    path("", include("config.auth_urls")),
    path("fas/<str:assetid>/", fas, name="fas"),
    path("fas/<str:assetid>/<str:username>/", fas, name="fas_with_user"),
    path("ad/click/<uuid:session_id>/", ad_click_redirect, name="fas_ad_click"),
]

