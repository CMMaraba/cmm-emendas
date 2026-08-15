from django.contrib import admin

from .models import Emenda, EmendaDocumento


class EmendaDocumentoInline(admin.TabularInline):
    model = EmendaDocumento
    extra = 0


@admin.register(Emenda)
class EmendaAdmin(admin.ModelAdmin):
    list_display = ("codigo", "autor_nome", "partido", "faixa", "situacao", "valor_previsto")
    list_filter = ("exercicio", "faixa", "situacao", "partido")
    search_fields = ("codigo", "autor_vereador__nome_parlamentar", "codigo_legado")
    readonly_fields = (
        "numero", "codigo", "codigo_legado", "municipio", "partido", "modalidade",
        "tipo_transferencia", "valor_previsto", "criado_em", "atualizado_em",
    )
    autocomplete_fields = ("autor_vereador", "autor_bancada", "funcao_governo", "unidade_gestora", "orgao_executor", "entidade")
    inlines = [EmendaDocumentoInline]


@admin.register(EmendaDocumento)
class EmendaDocumentoAdmin(admin.ModelAdmin):
    list_display = ("emenda", "descricao", "enviado_em")
