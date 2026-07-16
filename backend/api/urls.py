from django.urls import path

from . import views

urlpatterns = [
    path("health/", views.health, name="health"),
    path("places/", views.places, name="places"),
    path("routes/", views.routes, name="routes"),
    path("compromised/", views.compromised, name="compromised"),
    path("graph/", views.network, name="graph"),
    path("path/", views.path, name="path"),
]
