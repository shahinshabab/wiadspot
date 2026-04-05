from django.urls import path
from .views import (
    landing,
    landing_articles,
    landing_article_read,
    landing_contact,
    landing_about,
    landing_career,
)

urlpatterns = [
    path("", landing, name="landing"),
    path("articles/", landing_articles, name="landing_articles"),
    path("articles/read/<slug:slug>/", landing_article_read, name="landing_article_read"),
    path("contact/", landing_contact, name="landing_contact"),
    path("about/", landing_about, name="landing_about"),
    path("career/", landing_career, name="landing_career")
]