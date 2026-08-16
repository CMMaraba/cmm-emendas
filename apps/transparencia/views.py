import csv
import json

from django.core.paginator import Paginator
from django.db.models import Q, Sum
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse

from apps.emendas.models import Emenda
from apps.emendas.pdf_generator import gerar_pdf_emenda
from apps.orcamento.models import Exercicio, Faixa, resolver_exercicio_selecionado

COLUNAS = [
    "Nº", "Código", "Ano", "Município", "Vereador", "Partido Político",
    "Documentos da Emenda", "Modalidade", "Tipo de Transferência", "Vinculação Orçamentária",
    "Função de Governo", "Subfunção de Governo", "Programa PPA", "Objetivos do Programa do PPA",
    "Ação Orçamentária", "Objeto da Despesa", "Órgão Executor / OSC", "Categoria Econômica",
    "Valor Previsto (R$)", "Valor de Custeio (R$)", "Valor de Investimento (R$)",
]


def _publicadas(faixa=None, exercicio=None):
    qs = Emenda.objects.filter(situacao=Emenda.Situacao.PUBLICADA).select_related(
        "faixa", "autor_vereador", "autor_bancada", "autor_bancada__partido", "partido",
        "funcao_governo", "subfuncao_governo", "programa_ppa", "orgao_executor", "entidade",
    )
    if faixa:
        qs = qs.filter(faixa=faixa)
    if exercicio:
        qs = qs.filter(exercicio=exercicio)
    return qs.order_by("numero")


def _linha(emenda, request):
    # Toda emenda publicada tem o formulário oficial disponível (gerado na publicação,
    # com ata/documentação da entidade mesclada quando houver) — não só quando há anexo.
    doc_url = request.build_absolute_uri(reverse("transparencia:emenda_pdf", args=[emenda.pk]))
    return [
        emenda.numero,
        emenda.codigo,
        emenda.exercicio.ano,
        emenda.municipio,
        emenda.autor_nome,
        emenda.partido.sigla,
        doc_url,
        emenda.get_modalidade_display(),
        emenda.tipo_transferencia,
        emenda.vinculacao_orcamentaria,
        emenda.funcao_governo.nome if emenda.funcao_governo_id else "",
        emenda.subfuncao_governo.nome if emenda.subfuncao_governo_id else "",
        emenda.programa_ppa.nome if emenda.programa_ppa_id else "",
        emenda.programa_ppa.objetivos if emenda.programa_ppa_id else "",
        emenda.acao_orcamentaria,
        emenda.objeto_despesa,
        emenda.destino_nome,
        emenda.get_categoria_economica_display(),
        float(emenda.valor_previsto),
        float(emenda.valor_custeio),
        float(emenda.valor_investimento),
    ]


def tabela_publica(request):
    exercicios = list(Exercicio.objects.order_by("-ano"))
    exercicio = resolver_exercicio_selecionado(request, exercicios)
    abas = []
    if exercicio:
        for faixa in exercicio.faixas.filter(ativa=True):
            qs = _publicadas(faixa=faixa, exercicio=exercicio)
            termo = request.GET.get(f"q_{faixa.pk}", "").strip()
            if termo:
                qs = qs.filter(
                    Q(autor_vereador__nome_parlamentar__icontains=termo)
                    | Q(autor_bancada__partido__sigla__icontains=termo)
                    | Q(partido__sigla__icontains=termo)
                    | Q(codigo__icontains=termo)
                    | Q(orgao_executor__nome__icontains=termo)
                    | Q(entidade__nome__icontains=termo)
                    | Q(objeto_despesa__icontains=termo)
                )
            paginator = Paginator(qs, 25)
            pagina = paginator.get_page(request.GET.get(f"pagina_{faixa.pk}"))
            total = qs.aggregate(total=Sum("valor_previsto"))["total"] or 0
            abas.append({"faixa": faixa, "pagina": pagina, "termo": termo, "total": total, "quantidade": qs.count()})

    # Qual aba deve estar ativa ao carregar a página: a marcada em "_aba" (mandada pelos
    # links de paginação e pelo formulário de busca de cada faixa), com fallback pra
    # primeira — sem isso, qualquer clique em "página 2" ou "Filtrar" de uma aba que não
    # seja a primeira reabria a página sempre na primeira aba.
    aba_ativa_pk = request.GET.get("_aba")
    aba_ativa_pk = int(aba_ativa_pk) if aba_ativa_pk and aba_ativa_pk.isdigit() else None
    pks_disponiveis = [aba["faixa"].pk for aba in abas]
    if aba_ativa_pk not in pks_disponiveis:
        aba_ativa_pk = pks_disponiveis[0] if pks_disponiveis else None
    for aba in abas:
        aba["ativa"] = aba["faixa"].pk == aba_ativa_pk

    return render(request, "transparencia/tabela_publica.html", {
        "exercicio": exercicio, "exercicios": exercicios, "abas": abas, "colunas": COLUNAS,
    })


def exportar(request, formato, faixa_id):
    faixa = get_object_or_404(Faixa, pk=faixa_id)
    emendas = list(_publicadas(faixa=faixa, exercicio=faixa.exercicio))
    linhas = [_linha(e, request) for e in emendas]
    nome_base = f"emendas_{faixa.sigla_codigo}_{faixa.exercicio.ano}"

    if formato == "csv":
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="{nome_base}.csv"'
        writer = csv.writer(response)
        writer.writerow(COLUNAS)
        writer.writerows(linhas)
        return response

    if formato == "json":
        dados = [dict(zip(COLUNAS, linha)) for linha in linhas]
        return JsonResponse(dados, safe=False, json_dumps_params={"ensure_ascii": False, "indent": 2})

    if formato == "xlsx":
        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        ws.title = faixa.nome[:31]
        ws.append(COLUNAS)
        for linha in linhas:
            ws.append(linha)
        response = HttpResponse(
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        response["Content-Disposition"] = f'attachment; filename="{nome_base}.xlsx"'
        wb.save(response)
        return response

    if formato == "pdf":
        return _exportar_pdf_tabela(faixa, linhas, nome_base)

    raise Http404("Formato de exportação inválido.")


# Índices (na mesma ordem de COLUNAS) que recebem tratamento especial no PDF de
# exportação: centralizados, monetários (formatação BRL + alinhados à direita), e o link
# clicável de "Documentos da Emenda" (que na exportação vira só "PDF", não a URL inteira).
_PDF_INDICES_CENTRALIZADOS = {0, 2, 5, 6}
_PDF_INDICES_MONETARIOS = {18, 19, 20}
_PDF_INDICE_DOCUMENTO = 6

# Ação Orçamentária, Objeto da Despesa e Objetivos do Programa do PPA podem ter parágrafos
# inteiros (texto livre digitado pelo vereador/técnico) — numa coluna estreita isso gera
# uma linha mais alta que a própria página e derruba a geração do PDF (LayoutError). CSV/
# JSON/XLSX continuam com o texto completo; só o PDF trunca, como prévia. "Programa PPA"
# devia ser só um nome curto, mas na prática vem com o mesmo texto longo — limite mais
# apertado, já que essa coluna é estreita por natureza (o texto completo se repete em
# "Objetivos do Programa do PPA", ao lado).
_PDF_INDICES_TEXTO_LONGO = {13, 14, 15}
_PDF_LIMITE_TEXTO_LONGO = 280
_PDF_INDICE_PROGRAMA_PPA = 12
_PDF_LIMITE_PROGRAMA_PPA = 90

# Largura de cada coluna no PDF, em pontos (mesma ordem de COLUNAS) — valores absolutos,
# não proporcionais: a página do PDF é dimensionada a partir da SOMA dessas larguras (ver
# _exportar_pdf_tabela), então aumentar uma coluna aqui alarga a página, não espreme as
# outras. "Objetivos do Programa do PPA" (índice 13) recebe 3x o espaço das demais
# colunas de texto livre, a pedido explícito — é sempre o campo mais longo.
_PDF_LARGURAS_COLUNAS = [
    12, 56, 25, 34, 43, 28, 34, 43, 43, 37,
    34, 42, 40, 148, 46, 46, 28, 37, 35, 35, 37,
]


def _exportar_pdf_tabela(faixa, linhas, nome_base):
    import os

    from django.conf import settings
    from django.utils import timezone
    from django.utils.html import escape
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_RIGHT
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{nome_base}.pdf"'

    # A página não é mais presa a A4: a largura vem da soma das colunas (ver
    # _PDF_LARGURAS_COLUNAS) + margens — se uma coluna crescer, a página alarga, em vez
    # de espremer as outras. A altura continua a de uma A4 paisagem.
    margem = 1 * cm
    largura_colunas = sum(_PDF_LARGURAS_COLUNAS)
    largura_pagina = largura_colunas + 2 * margem
    altura_pagina = landscape(A4)[1]

    doc = SimpleDocTemplate(
        response, pagesize=(largura_pagina, altura_pagina),
        topMargin=margem, bottomMargin=margem, leftMargin=margem, rightMargin=margem,
    )
    estilos = getSampleStyleSheet()
    marrom = colors.HexColor("#512f0d")

    estilo_titulo = ParagraphStyle("TituloExportacao", parent=estilos["Normal"], fontName="Helvetica-Bold", fontSize=12, textColor=marrom, leading=15)
    estilo_subtitulo = ParagraphStyle("SubtituloExportacao", parent=estilos["Normal"], fontName="Helvetica-Bold", fontSize=10, textColor=marrom, leading=13)
    estilo_meta = ParagraphStyle("MetaExportacao", parent=estilos["Normal"], fontName="Helvetica", fontSize=8, textColor=colors.grey, leading=10)
    estilo_cabecalho_col = ParagraphStyle("CabecalhoColuna", parent=estilos["Normal"], fontName="Helvetica-Bold", fontSize=6.5, textColor=colors.white, alignment=TA_CENTER, leading=8)
    estilo_celula = ParagraphStyle("CelulaExportacao", parent=estilos["Normal"], fontName="Helvetica", fontSize=6, leading=7.5)
    estilo_celula_centro = ParagraphStyle("CelulaCentro", parent=estilo_celula, alignment=TA_CENTER)
    estilo_celula_valor = ParagraphStyle("CelulaValor", parent=estilo_celula, alignment=TA_RIGHT)

    # --- Cabeçalho: logo + nome do órgão + o que foi exportado ---
    agora_local = timezone.localtime(timezone.now())
    textos_cabecalho = [
        Paragraph("CÂMARA MUNICIPAL DE MARABÁ", estilo_titulo),
        Paragraph(f"Emendas Impositivas — {escape(faixa.nome)}", estilo_subtitulo),
        Paragraph(
            f"Exercício {faixa.exercicio.ano} &middot; {len(linhas)} emenda(s) publicada(s) "
            f"&middot; Exportado em {agora_local:%d/%m/%Y %H:%M}",
            estilo_meta,
        ),
    ]
    elementos = []
    logo_path = os.path.join(settings.BASE_DIR, "static", "images", "logo.png")
    if os.path.exists(logo_path):
        largura_logo, altura_logo = 130, 61
        cabecalho_tbl = Table(
            [[Image(logo_path, width=largura_logo, height=altura_logo, kind="proportional"), textos_cabecalho]],
            colWidths=[largura_logo + 10, doc.width - largura_logo - 10],
        )
        cabecalho_tbl.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN", (0, 0), (0, 0), "CENTER"),
        ]))
        elementos.append(cabecalho_tbl)
    else:
        elementos.extend(textos_cabecalho)
    elementos.append(Spacer(1, 12))

    # --- Tabela de dados: todas as colunas, mesma fonte em toda a tabela ---
    def formatar_valor(valor):
        return f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    cabecalho = [Paragraph(coluna, estilo_cabecalho_col) for coluna in COLUNAS]
    dados = [cabecalho]
    for linha in linhas:
        celulas = []
        for indice, valor in enumerate(linha):
            if indice == _PDF_INDICE_DOCUMENTO:
                texto = f'<link href="{valor}" color="#512f0d">PDF</link>' if valor else "—"
                celulas.append(Paragraph(texto, estilo_celula_centro))
            elif indice in _PDF_INDICES_MONETARIOS:
                celulas.append(Paragraph(formatar_valor(valor), estilo_celula_valor))
            elif indice in _PDF_INDICES_CENTRALIZADOS:
                celulas.append(Paragraph(escape(str(valor)) if valor not in (None, "") else "—", estilo_celula_centro))
            else:
                texto = str(valor) if valor not in (None, "") else "—"
                limite = (
                    _PDF_LIMITE_PROGRAMA_PPA if indice == _PDF_INDICE_PROGRAMA_PPA
                    else _PDF_LIMITE_TEXTO_LONGO if indice in _PDF_INDICES_TEXTO_LONGO
                    else None
                )
                if limite and len(texto) > limite:
                    texto = texto[:limite].rstrip() + "…"
                celulas.append(Paragraph(escape(texto), estilo_celula))
        dados.append(celulas)

    tabela = Table(dados, colWidths=_PDF_LARGURAS_COLUNAS, repeatRows=1)
    tabela.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), marrom),
        ("VALIGN", (0, 0), (-1, 0), "MIDDLE"),
        ("VALIGN", (0, 1), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7f5f2")]),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
    ]))
    elementos.append(tabela)

    doc.build(elementos)
    return response


def api_emendas(request):
    exercicios = list(Exercicio.objects.order_by("-ano"))
    exercicio = resolver_exercicio_selecionado(request, exercicios)
    faixa_sigla = request.GET.get("faixa")
    qs = _publicadas(exercicio=exercicio)
    if faixa_sigla:
        qs = qs.filter(faixa__sigla_codigo=faixa_sigla)

    paginator = Paginator(qs.order_by("faixa", "numero"), 50)
    pagina = paginator.get_page(request.GET.get("page"))
    resultados = [dict(zip(COLUNAS, _linha(e, request))) for e in pagina.object_list]

    return JsonResponse({
        "count": paginator.count,
        "num_pages": paginator.num_pages,
        "page": pagina.number,
        "results": resultados,
    }, json_dumps_params={"ensure_ascii": False})


def emenda_pdf(request, pk):
    emenda = get_object_or_404(Emenda, pk=pk)
    if emenda.situacao != Emenda.Situacao.PUBLICADA and not request.user.is_authenticated:
        raise Http404("Emenda não publicada.")

    # Emenda publicada já tem o "documento físico" congelado no momento da publicação
    # (Emenda._gerar_pdf_oficial) — serve esse arquivo, não gera de novo. Só gera ao vivo
    # para pré-visualização de emenda ainda não publicada (setor técnico, autenticado).
    if emenda.situacao == Emenda.Situacao.PUBLICADA and emenda.pdf_gerado:
        response = HttpResponse(emenda.pdf_gerado.read(), content_type="application/pdf")
    else:
        buffer = gerar_pdf_emenda(emenda)
        response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="{emenda.codigo or emenda.pk}.pdf"'
    return response
