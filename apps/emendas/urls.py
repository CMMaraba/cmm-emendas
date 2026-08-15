from django.urls import path

from . import views

app_name = "emendas"

urlpatterns = [
    path("", views.painel_home, name="painel_home"),
    path("emenda/nova/<int:faixa_id>/", views.emenda_form, name="emenda_nova"),
    path("emenda/<int:pk>/editar/", views.emenda_form, name="emenda_editar"),
    path("emenda/<int:pk>/enviar/", views.emenda_enviar, name="emenda_enviar"),
    path("conferencia/", views.conferencia_lista, name="conferencia_lista"),
    path("conferencia/<int:pk>/", views.conferencia_detalhe, name="conferencia_detalhe"),
    path("cadastros/", views.cadastros_home, name="cadastros_home"),
    path("configuracao/", views.configuracao_home, name="configuracao_home"),
]
