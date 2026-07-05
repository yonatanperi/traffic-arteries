from django.urls import path

from . import views

urlpatterns = [
    path("places/", views.places, name="places"),
    path("routes/", views.routes, name="routes"),
    path("graph/", views.network, name="graph"),
    path("path/", views.path, name="path"),
]
