from django.urls import path
from . import views

urlpatterns = [
    # Views
    path("", views.index, name="index"),

    # API
    path("api/getHalteList", views.getHalteList, name="getHalteList" )
]