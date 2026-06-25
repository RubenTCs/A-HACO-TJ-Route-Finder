from django.urls import path
from . import views

urlpatterns = [
    # =======================================================
    # region Views
    # =======================================================

    path("", views.about, name="about"),
    path("cari-rute/", views.index, name="index"),
    path("log/", views.log, name="log"),
    path("user-guide/", views.user_guide, name="user_guide"),

    # =======================================================
    # endregion
    # =======================================================

    # =======================================================
    # region API
    # =======================================================

    path("api/getHalteList", views.getHalteList, name="getHalteList"),
    # =======================================================
    # endregion
    # =======================================================

]