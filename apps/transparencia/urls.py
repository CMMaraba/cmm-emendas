from django.urls import path

from . import views

app_name = "transparencia"

urlpatterns = [
    path("", views.tabela_publica, name="tabela_publica"),
    path("exportar/<str:formato>/<int:faixa_id>/", views.exportar, name="exportar"),
    path("api/v1/emendas/", views.api_emendas, name="api_emendas"),
    path("emenda/<int:pk>/pdf/", views.emenda_pdf, name="emenda_pdf"),
]
