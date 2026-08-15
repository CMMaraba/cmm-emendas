import csv
import json

from django.core.paginator import Paginator
from django.db.models import Q, Sum
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse

from apps.emendas.models import Emenda
from apps.emendas.pdf_generator import gerar_pdf_emenda
from apps.orcamento.models import Exercicio, Faixa

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
    doc_url = ""
    if emenda.documentacao_entidade or (emenda.autor_bancada_id and emenda.autor_bancada.ata) or emenda.anexos.exists():
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
    exercicio = Exercicio.atual()
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

    return render(request, "transparencia/tabela_publica.html", {"exercicio": exercicio, "abas": abas, "colunas": COLUNAS})


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
        return _exportar_pdf_tabela(faixa, emendas, nome_base)

    raise Http404("Formato de exportação inválido.")


def _exportar_pdf_tabela(faixa, emendas, nome_base):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.units import cm
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
    from reportlab.lib.styles import getSampleStyleSheet

    response = HttpResponse(content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{nome_base}.pdf"'

    doc = SimpleDocTemplate(response, pagesize=landscape(A4), topMargin=1 * cm, bottomMargin=1 * cm)
    estilos = getSampleStyleSheet()
    cabecalho = [Paragraph(f"<b>{c}</b>", estilos["Normal"]) for c in
                 ["Nº", "Código", "Vereador", "Partido", "Órgão Executor / OSC", "Objeto da Despesa", "Valor Previsto (R$)"]]
    dados = [cabecalho]
    for e in emendas:
        dados.append([
            str(e.numero), e.codigo, e.autor_nome, e.partido.sigla, e.destino_nome,
            Paragraph(e.objeto_despesa[:200], estilos["Normal"]),
            f"{e.valor_previsto:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."),
        ])
    tabela = Table(dados, repeatRows=1)
    tabela.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#512f0d")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    doc.build([tabela])
    return response


def api_emendas(request):
    exercicio = Exercicio.atual()
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
    buffer = gerar_pdf_emenda(emenda)
    response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="{emenda.codigo}.pdf"'
    return response
