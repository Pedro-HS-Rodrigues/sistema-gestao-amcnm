from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from gestao.seguranca import LoginComBloqueioView

urlpatterns = [
    path("entrar/", LoginComBloqueioView.as_view(), name="login"),
    path("sair/", auth_views.LogoutView.as_view(), name="logout"),
    path("admin/", admin.site.urls),
    path("", include("gestao.urls")),
]
