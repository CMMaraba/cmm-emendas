from django.contrib import admin, messages

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
    actions = ["clonar_para_proximo_exercicio"]

    @admin.action(description="Clonar bancada(s) selecionada(s) para o próximo exercício")
    def clonar_para_proximo_exercicio(self, request, queryset):
        # Bancada é um cadastro por exercício (composição/coordenador podem mudar de ano
        # para ano — ver Bancada.Meta.unique_together), então "participar de múltiplos
        # exercícios" não vira um checkbox/M2M: cada ano tem sua própria linha, e esta
        # ação só agiliza criar a linha do próximo ano com a mesma composição do
        # exercício de origem (ficando livre para editar depois, se algo mudou).
        from apps.orcamento.models import Exercicio

        for bancada in queryset:
            proximo_ano = bancada.exercicio.ano + 1
            proximo_exercicio = Exercicio.objects.filter(ano=proximo_ano).first()
            if not proximo_exercicio:
                self.message_user(
                    request,
                    f"Não existe exercício {proximo_ano} cadastrado — crie-o antes de clonar a bancada {bancada.partido.sigla}.",
                    level=messages.WARNING,
                )
                continue
            if Bancada.objects.filter(partido=bancada.partido, exercicio=proximo_exercicio).exists():
                self.message_user(
                    request, f"Bancada {bancada.partido.sigla} já existe em {proximo_ano} — ignorada.", level=messages.WARNING
                )
                continue
            nova = Bancada.objects.create(
                partido=bancada.partido, exercicio=proximo_exercicio, coordenador=bancada.coordenador,
            )
            nova.membros.set(bancada.membros.all())
            self.message_user(request, f"Bancada {bancada.partido.sigla} clonada para {proximo_ano}.")


@admin.register(Perfil)
class PerfilAdmin(admin.ModelAdmin):
    list_display = ("user", "papel", "vereador", "partido")
    list_filter = ("papel",)
    search_fields = ("user__username", "user__first_name", "user__last_name")
    autocomplete_fields = ("vereador", "partido", "user")
