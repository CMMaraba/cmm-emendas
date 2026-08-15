from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path
from django.views.generic import RedirectView

urlpatterns = [
    path("", RedirectView.as_view(url="/emendas/", permanent=False)),
    path("emendas/admin/", admin.site.urls),
    path(
        "emendas/login/",
        auth_views.LoginView.as_view(template_name="registration/login.html"),
        name="login",
    ),
    path("emendas/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path(
        "emendas/senha/alterar/",
        auth_views.PasswordChangeView.as_view(template_name="registration/password_change.html"),
        name="password_change",
    ),
    path(
        "emendas/senha/alterada/",
        auth_views.PasswordChangeDoneView.as_view(template_name="registration/password_change_done.html"),
        name="password_change_done",
    ),
    path("emendas/painel/", include("apps.emendas.urls")),
    path("emendas/", include("apps.transparencia.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
