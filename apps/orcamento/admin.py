from django.contrib import admin
from django.utils.html import format_html

from .models import (
    Entidade,
    Exercicio,
    Faixa,
    FuncaoGoverno,
    OrgaoExecutor,
    ProgramaPPA,
    SubfuncaoGoverno,
    UnidadeGestora,
)


class FaixaInline(admin.TabularInline):
    model = Faixa
    extra = 0
    fields = (
        "nome",
        "modalidade",
        "percentual_rcl",
        "sigla_codigo",
        "rotulo_transferencia",
        "percentual_minimo_outras_funcoes",
        "ordem",
        "ativa",
        "teto_por_vereador_fmt",
    )
    readonly_fields = ("teto_por_vereador_fmt",)

    @admin.display(description="Teto por vereador")
    def teto_por_vereador_fmt(self, obj):
        if not obj.pk:
            return "—"
        valor = obj.teto_por_vereador()
        return format_html("R$ {}", f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))


@admin.register(Exercicio)
class ExercicioAdmin(admin.ModelAdmin):
    list_display = ("ano", "rcl_exercicio_anterior", "numero_vereadores", "situacao")
    list_filter = ("situacao",)
    inlines = [FaixaInline]
    actions = ["abrir_proximo_exercicio"]

    @admin.action(description="Clonar exercício selecionado para o ano seguinte")
    def abrir_proximo_exercicio(self, request, queryset):
        for exercicio in queryset:
            novo_ano = exercicio.ano + 1
            if Exercicio.objects.filter(ano=novo_ano).exists():
                self.message_user(request, f"O exercício {novo_ano} já existe — ignorado.")
                continue
            exercicio.clonar_para(novo_ano)
            self.message_user(request, f"Exercício {novo_ano} criado a partir de {exercicio.ano}.")


@admin.register(UnidadeGestora)
class UnidadeGestoraAdmin(admin.ModelAdmin):
    list_display = ("nome", "exige_documentacao_entidade", "ordem")
    list_editable = ("ordem",)
    search_fields = ("nome",)


@admin.register(OrgaoExecutor)
class OrgaoExecutorAdmin(admin.ModelAdmin):
    list_display = ("nome", "unidade_gestora", "ativo")
    list_filter = ("unidade_gestora", "ativo")
    search_fields = ("nome",)
    autocomplete_fields = ("unidade_gestora",)


@admin.register(Entidade)
class EntidadeAdmin(admin.ModelAdmin):
    list_display = ("nome", "cnpj", "ativa", "validade_documentacao")
    list_filter = ("ativa",)
    search_fields = ("nome", "cnpj")


@admin.register(FuncaoGoverno)
class FuncaoGovernoAdmin(admin.ModelAdmin):
    list_display = ("nome", "codigo", "ordem")
    list_editable = ("ordem",)
    search_fields = ("nome",)


@admin.register(SubfuncaoGoverno)
class SubfuncaoGovernoAdmin(admin.ModelAdmin):
    list_display = ("nome", "funcao", "codigo")
    list_filter = ("funcao",)
    search_fields = ("nome",)
    autocomplete_fields = ("funcao",)


@admin.register(ProgramaPPA)
class ProgramaPPAAdmin(admin.ModelAdmin):
    list_display = ("codigo", "nome", "exercicio")
    list_filter = ("exercicio",)
    search_fields = ("codigo", "nome")
