from django.contrib import admin

from .models import Bancada, Partido, Perfil, Vereador


@admin.register(Partido)
class PartidoAdmin(admin.ModelAdmin):
    list_display = ("sigla", "nome", "ativo")
    list_filter = ("ativo",)
    search_fields = ("sigla", "nome")


@admin.register(Vereador)
class VereadorAdmin(admin.ModelAdmin):
    list_display = ("nome_parlamentar", "partido", "ativo")
    list_filter = ("partido", "ativo")
    search_fields = ("nome_parlamentar", "nome_civil")
    autocomplete_fields = ("partido",)


@admin.register(Bancada)
class BancadaAdmin(admin.ModelAdmin):
    list_display = ("partido", "exercicio", "coordenador", "num_membros")
    list_filter = ("exercicio", "partido")
    search_fields = ("partido__sigla", "partido__nome")
    autocomplete_fields = ("partido", "coordenador")
    filter_horizontal = ("membros",)


@admin.register(Perfil)
class PerfilAdmin(admin.ModelAdmin):
    list_display = ("user", "papel", "vereador", "partido")
    list_filter = ("papel",)
    search_fields = ("user__username", "user__first_name", "user__last_name")
    autocomplete_fields = ("vereador", "partido", "user")
