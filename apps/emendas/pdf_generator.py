"""Geração do PDF oficial da emenda impositiva.

Port de app/emendas/pdf_generator.py do sistema legado (cmm-emendas / mdmassa), com a
diferença central de que nenhum valor de exercício (RCL, percentuais, nº de vereadores,
datas de reserva, texto legal) fica escrito no código: tudo vem do Exercicio/Faixa/Emenda
vigentes, para que o formulário continue correto quando esses valores mudarem ano a ano.
"""

import io
import os
from decimal import Decimal

from django.conf import settings
from PyPDF2 import PdfReader, PdfWriter
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

PAGE_W, PAGE_H = A4
MARGIN_L = 40
MARGIN_R = 40
MARGIN_T = 50
MARGIN_B = 50
CONTENT_W = PAGE_W - MARGIN_L - MARGIN_R
INDENT = 20

FS_TITLE = 14
FS_NORMAL = 12
FS_OBS = 11
FS_BOX = 12

VALUES_RIGHT_X = MARGIN_L + CONTENT_W

MESES_PT = [
    "", "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
]

_FONTS_REGISTERED = False


def leading(font_size, extra=4.0):
    return font_size + extra


def register_local_fonts():
    global _FONTS_REGISTERED
    if _FONTS_REGISTERED:
        return

    candidatos = [
        os.path.join(settings.BASE_DIR, "static", "fonts"),
        "/usr/share/fonts/truetype/liberation",  # layout Debian/Ubuntu (servidor de produção)
        "/usr/share/fonts/liberation",  # layout Arch/Fedora
    ]
    arquivos = {
        "Arial": ["Arial.ttf", "LiberationSans-Regular.ttf"],
        "Arial-Bold": ["Arial-Bold.ttf", "LiberationSans-Bold.ttf"],
        "Arial-Italic": ["Arial-Italic.ttf", "LiberationSans-Italic.ttf"],
        "Arial-BoldItalic": ["Arial-BoldItalic.ttf", "LiberationSans-BoldItalic.ttf"],
    }
    for nome_fonte, opcoes in arquivos.items():
        for pasta in candidatos:
            for arquivo in opcoes:
                caminho = os.path.join(pasta, arquivo)
                if os.path.exists(caminho):
                    try:
                        pdfmetrics.registerFont(TTFont(nome_fonte, caminho))
                    except Exception:
                        pass
                    break
            else:
                continue
            break
    _FONTS_REGISTERED = True


def set_font(c, bold=False, italic=False, size=FS_NORMAL):
    if bold and italic:
        c.setFont("Arial-BoldItalic", size)
    elif bold:
        c.setFont("Arial-Bold", size)
    elif italic:
        c.setFont("Arial-Italic", size)
    else:
        c.setFont("Arial", size)


def draw_header(c):
    logo_path = os.path.join(settings.BASE_DIR, "static", "images", "logo.png")
    if os.path.exists(logo_path):
        logo_w, logo_h = 160, 75
        logo_x = (PAGE_W - logo_w) / 2
        logo_y = PAGE_H - MARGIN_T - 50
        c.drawImage(logo_path, logo_x, logo_y, width=logo_w, height=logo_h, preserveAspectRatio=True, mask="auto")


def draw_underlined_section_title(c, text, x, y, size=FS_NORMAL):
    set_font(c, size=size)
    c.drawString(x, y, text)
    text_w = c.stringWidth(text, "Arial", size)
    c.line(x, y - 2, x + text_w, y - 2)


def draw_checkbox(c, x, y, size=12, checked=False):
    original_width = c._lineWidth
    c.setLineWidth(1.5)
    c.rect(x, y, size, size)
    if checked:
        c.line(x, y, x + size, y + size)
        c.line(x + size, y, x, y + size)
    c.setLineWidth(original_width)


def draw_checkbox_item(c, x, y, label, checked, font_size=FS_NORMAL, cb_size=12):
    text_center_y = y + font_size * 0.4
    cb_y = text_center_y - cb_size / 2
    draw_checkbox(c, x, cb_y, size=cb_size, checked=checked)
    set_font(c, size=font_size)
    c.drawString(x + cb_size + 5, y, label)


def _quebrar_linhas(c, text, width, font_name, font_size):
    words = text.split()
    lines, current = [], ""
    for word in words:
        test = (current + " " + word).strip()
        if c.stringWidth(test, font_name, font_size) <= width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def wrapped_text_height(c, text, width, font_name, font_size, line_h):
    return len(_quebrar_linhas(c, text, width, font_name, font_size)) * line_h


def draw_wrapped_text(c, text, x, y, width, font_name, font_size, line_h):
    c.setFont(font_name, font_size)
    for line in _quebrar_linhas(c, text, width, font_name, font_size):
        c.drawString(x, y, line)
        y -= line_h
    return y


def underline_field(c, x, y, width):
    c.line(x, y - 2, x + width, y - 2)


def format_brl(value):
    return f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def build_page1(c, data):
    y = PAGE_H - MARGIN_T
    draw_header(c)
    y -= 60

    is_coletiva = data["is_coletiva"]
    titulo_tipo = "COLETIVAS" if is_coletiva else "INDIVIDUAIS"

    set_font(c, bold=True, size=FS_TITLE)
    c.drawCentredString(PAGE_W / 2, y, f"EMENDAS IMPOSITIVAS {titulo_tipo} AO ORÇAMENTO DO")
    y -= leading(FS_TITLE)
    c.drawCentredString(PAGE_W / 2, y, f"EXERCÍCIO DE {data['exercicio_ano']}")
    y -= leading(FS_TITLE, 10)

    ld = leading(FS_NORMAL)
    set_font(c, size=FS_NORMAL)

    c.drawString(MARGIN_L, y, f"Vereador: {data['vereador_exibicao']}")
    if is_coletiva:
        c.drawString(PAGE_W / 2, y, f"Partido: {data['partido_sigla']}")
    y -= ld

    value_rows = [
        (f"Valor da Receita Corrente Líquida do Exercício de {data['ano_referencia_rcl']}", data["receita_corrente_liquida_str"]),
        (data["label_emendas"], data["valor_emendas_str"]),
        (f"Valor total das emendas - {data['num_vereadores']} vereadores", data["valor_total_emendas_str"]),
    ]
    if data.get("extra_valor_str"):
        value_rows.append((data["extra_valor_label"], data["extra_valor_str"]))

    max_val_w = max(c.stringWidth(str(val), "Arial", FS_NORMAL) for _, val in value_rows)
    r_column_x = VALUES_RIGHT_X - max_val_w - 35

    for label, val in value_rows:
        label_w = c.stringWidth(str(label), "Arial", FS_NORMAL)
        dots_start = MARGIN_L + label_w + 3
        dots_end = r_column_x - 3
        dot_w = c.stringWidth(".", "Arial", FS_NORMAL)
        dots = "." * int((dots_end - dots_start) / dot_w) if dot_w > 0 and dots_end > dots_start else " "
        c.drawString(MARGIN_L, y, str(label) + " " + dots)
        c.drawString(r_column_x, y, "R$")
        c.drawRightString(VALUES_RIGHT_X, y, str(val))
        y -= ld

    if is_coletiva:
        set_font(c, italic=True, size=FS_OBS)
        c.drawString(MARGIN_L, y, "obs: multiplicar o valor pelo número de vereadores que compõem a bancada")
        y -= leading(FS_OBS, 12)
    else:
        y -= 8

    draw_underlined_section_title(c, "ÁREA DE APLICAÇÃO CONTEMPLADA", MARGIN_L, y, size=FS_NORMAL)
    y -= leading(FS_NORMAL, 10)

    area_marcada = data["area_marcada"]
    col_w = CONTENT_W / 2
    row_h = leading(FS_NORMAL)

    areas = data["areas_disponiveis"]
    half = (len(areas) + 1) // 2
    col1, col2 = areas[:half], areas[half:]

    start_y = y
    for i, area in enumerate(col1):
        draw_checkbox_item(c, MARGIN_L + INDENT, start_y - i * row_h, area, area == area_marcada, font_size=FS_NORMAL)
    for i, area in enumerate(col2):
        draw_checkbox_item(c, MARGIN_L + col_w + INDENT, start_y - i * row_h, area, area == area_marcada, font_size=FS_NORMAL)

    y = start_y - max(len(col1), len(col2)) * row_h
    y -= row_h - 5

    draw_underlined_section_title(c, "UNIDADE GESTORA VINCULADA", MARGIN_L, y, size=FS_NORMAL)
    y -= leading(FS_NORMAL, 10)

    ug_marcada = data["unidade_gestora_marcada"]
    for ug in data["unidades_gestoras_disponiveis"]:
        draw_checkbox_item(c, MARGIN_L + INDENT, y, ug, ug == ug_marcada, font_size=FS_NORMAL)
        y -= row_h
    y -= 10

    draw_underlined_section_title(c, "DESCRIÇÃO EMENDA IMPOSITIVA PROPOSTA", MARGIN_L, y, size=FS_NORMAL)
    y -= 10

    descricao = data["descricao_emenda"] or "Sem descrição"
    padding = 20
    inner_w = CONTENT_W - 20
    lh_box = leading(FS_BOX)
    text_h = wrapped_text_height(c, descricao, inner_w, "Arial", FS_BOX, lh_box)
    box_h = max(text_h + 30, 50)

    original_line_width = c._lineWidth
    c.setLineWidth(1.5)
    c.rect(MARGIN_L, y - box_h, CONTENT_W, box_h)
    c.setLineWidth(original_line_width)

    draw_wrapped_text(c, descricao, MARGIN_L + padding, y - padding - 2, inner_w, "Arial", FS_BOX, lh_box)
    y -= box_h + 5
    return y


def build_page2(c, data):
    y = PAGE_H - MARGIN_T
    draw_header(c)
    y -= 75

    valor_estimado_str = data["valor_previsto_str"]

    set_font(c, size=FS_NORMAL)
    label_ve = "VALOR ESTIMADO PARA A EMENDA  - R$ "
    c.drawString(MARGIN_L, y, label_ve)
    xv = MARGIN_L + c.stringWidth(label_ve, "Arial", FS_NORMAL)
    if valor_estimado_str:
        c.drawString(xv, y, valor_estimado_str)
        underline_field(c, xv, y, c.stringWidth(valor_estimado_str, "Arial", FS_NORMAL))
    else:
        underline_field(c, xv, y, 100)
    y -= leading(FS_NORMAL, 10)

    set_font(c, size=FS_OBS)
    y = draw_wrapped_text(c, f"- {data['observacao_legal']}", MARGIN_L, y, CONTENT_W, "Arial", FS_OBS, leading(FS_OBS))
    y -= 35

    set_font(c, size=FS_NORMAL)
    c.drawCentredString(PAGE_W / 2, y, data["data_assinatura_str"])
    y -= 60

    sig_w = 275
    c.line(PAGE_W / 2 - sig_w / 2, y, PAGE_W / 2 + sig_w / 2, y)
    y -= leading(FS_NORMAL)
    if data["is_coletiva"]:
        c.drawCentredString(PAGE_W / 2, y, f"Vereador: {data['vereador_exibicao']}, {data['partido_sigla']}")
    else:
        c.drawCentredString(PAGE_W / 2, y, f"Vereador {data['vereador_exibicao']}")
    y -= 75

    inner_pad = 18
    box_h = 250
    box_top = y

    original_line_width = c._lineWidth
    c.setLineWidth(1.5)
    c.rect(MARGIN_L, box_top - box_h, CONTENT_W, box_h)
    c.setLineWidth(original_line_width)

    iy = box_top - inner_pad
    draw_underlined_section_title(
        c, "USO DO SETOR TÉCNICO DA CÂMARA MUNICIPAL DE MARABÁ", MARGIN_L + inner_pad, iy, size=FS_NORMAL
    )
    iy -= leading(FS_NORMAL, 8)

    set_font(c, size=FS_NORMAL)
    lbl_cf = "Classificação Funcional Programática: "
    c.drawString(MARGIN_L + inner_pad, iy, lbl_cf)
    xc = MARGIN_L + inner_pad + c.stringWidth(lbl_cf, "Arial", FS_NORMAL)
    classificacao = data["classificacao_funcional"]
    if classificacao:
        c.drawString(xc, iy, classificacao)
    else:
        underline_field(c, xc, iy, CONTENT_W - 2 * inner_pad - c.stringWidth(lbl_cf, "Arial", FS_NORMAL))
    iy -= 95

    lbl_v = "Valor: R$ "
    total_w = c.stringWidth(lbl_v, "Arial", FS_NORMAL) + 80
    xv_start = ((PAGE_W / 2) + 100) - total_w / 2
    c.drawString(xv_start, iy, lbl_v)
    xvt = xv_start + c.stringWidth(lbl_v, "Arial", FS_NORMAL)
    if valor_estimado_str:
        c.drawString(xvt, iy, valor_estimado_str)
        underline_field(c, xvt, iy, c.stringWidth(valor_estimado_str, "Arial", FS_NORMAL))
    else:
        underline_field(c, xvt, iy, 80)
    iy -= 27

    lbl_res = "Emenda Impositiva Reservada em "
    c.drawString(MARGIN_L + inner_pad, iy, lbl_res)
    xr = MARGIN_L + inner_pad + c.stringWidth(lbl_res, "Arial", FS_NORMAL)
    underline_padding = 5

    for parte in (data["dia_reserva_str"], "/", data["mes_reserva_str"], "/", data["ano_reserva_str"]):
        if parte == "/":
            c.drawString(xr, iy, "/")
            xr += c.stringWidth("/", "Arial", FS_NORMAL) + 2
            continue
        tamanho = c.stringWidth(parte, "Arial", FS_NORMAL) + underline_padding * 2
        c.drawString(xr + (tamanho - c.stringWidth(parte, "Arial", FS_NORMAL)) / 2, iy, parte)
        underline_field(c, xr, iy, tamanho)
        xr += tamanho + 2
    iy -= 67

    sig2_w = 275
    c.line(PAGE_W / 2 - sig2_w / 2, iy, PAGE_W / 2 + sig2_w / 2, iy)

    return box_top - box_h


def merge_pdfs(pdf_files):
    merger = PdfWriter()
    for item in pdf_files:
        if not item:
            continue
        try:
            if isinstance(item, io.BytesIO):
                item.seek(0)
                reader = PdfReader(item)
            elif hasattr(item, "path") and os.path.exists(item.path):
                reader = PdfReader(item.path)
            elif isinstance(item, str) and os.path.exists(item):
                reader = PdfReader(item)
            else:
                continue
            for page in reader.pages:
                merger.add_page(page)
        except Exception:
            continue

    if len(merger.pages) == 0:
        return None
    output = io.BytesIO()
    merger.write(output)
    output.seek(0)
    return output


def _montar_dados_pdf(emenda):
    from apps.orcamento.models import FuncaoGoverno, UnidadeGestora

    exercicio = emenda.exercicio
    faixa = emenda.faixa
    is_coletiva = emenda.autor_bancada_id is not None

    if is_coletiva:
        bancada = emenda.autor_bancada
        vereador_exibicao = bancada.coordenador.nome_parlamentar
        partido_sigla = bancada.partido.sigla
        teto_autor = faixa.teto_para(bancada)
    else:
        vereador_exibicao = emenda.autor_vereador.nome_parlamentar
        partido_sigla = emenda.autor_vereador.partido.sigla
        teto_autor = faixa.teto_para(emenda.autor_vereador)

    valor_total_faixa = exercicio.rcl_exercicio_anterior * faixa.percentual_rcl / Decimal("100")
    percentual_fmt = f"{faixa.percentual_rcl:.2f}".replace(".", ",")
    label_emendas = f"Valor das emendas {'coletivas' if is_coletiva else 'individuais'} {percentual_fmt}%"

    extra_valor_str = None
    extra_valor_label = None
    if faixa.percentual_minimo_outras_funcoes:
        extra = teto_autor * faixa.percentual_minimo_outras_funcoes / Decimal("100")
        extra_valor_str = format_brl(float(extra))
        extra_valor_label = f"Valor mínimo para outras funções ({faixa.percentual_minimo_outras_funcoes:.0f}%)"

    data_reserva = emenda.data_reserva
    if data_reserva:
        dia_str = f"{data_reserva.day:02d}"
        mes_str = f"{data_reserva.month:02d}"
        ano_str = str(data_reserva.year)
        data_assinatura_str = f"{exercicio.municipio}, {data_reserva.day} de {MESES_PT[data_reserva.month]} de {data_reserva.year}."
    else:
        dia_str = mes_str = ano_str = ""
        data_assinatura_str = f"{exercicio.municipio}, ____ de ____________ de {exercicio.ano}."

    areas = list(FuncaoGoverno.objects.order_by("ordem", "nome").values_list("nome", flat=True))
    unidades = list(UnidadeGestora.objects.order_by("ordem", "nome").values_list("nome", flat=True))

    return {
        "exercicio_ano": exercicio.ano,
        "is_coletiva": is_coletiva,
        "vereador_exibicao": vereador_exibicao,
        "partido_sigla": partido_sigla,
        "receita_corrente_liquida_str": format_brl(float(exercicio.rcl_exercicio_anterior)),
        "ano_referencia_rcl": exercicio.ano_referencia_rcl,
        "num_vereadores": exercicio.numero_vereadores,
        "label_emendas": label_emendas,
        "valor_emendas_str": format_brl(float(valor_total_faixa)),
        "valor_total_emendas_str": format_brl(float(teto_autor)),
        "extra_valor_str": extra_valor_str,
        "extra_valor_label": extra_valor_label,
        "area_marcada": emenda.funcao_governo.nome if emenda.funcao_governo_id else "",
        "areas_disponiveis": areas,
        "unidade_gestora_marcada": emenda.unidade_gestora.nome if emenda.unidade_gestora_id else "",
        "unidades_gestoras_disponiveis": unidades,
        "descricao_emenda": emenda.acao_orcamentaria,
        "valor_previsto_str": format_brl(float(emenda.valor_previsto)) if emenda.valor_previsto else "",
        "observacao_legal": exercicio.observacao_legal_formulario,
        "data_assinatura_str": data_assinatura_str,
        "dia_reserva_str": dia_str,
        "mes_reserva_str": mes_str,
        "ano_reserva_str": ano_str,
        "classificacao_funcional": emenda.vinculacao_orcamentaria,
    }


def gerar_pdf_emenda(emenda):
    """Gera o PDF de 2 páginas e mescla ata da bancada / documentação da entidade, se houver."""
    register_local_fonts()

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    c.setLineWidth(0.5)

    data = _montar_dados_pdf(emenda)

    build_page1(c, data)
    c.showPage()
    c.setLineWidth(0.5)
    build_page2(c, data)
    c.save()
    buffer.seek(0)

    pdfs_to_merge = [buffer]

    if emenda.autor_bancada_id and emenda.autor_bancada.ata:
        pdfs_to_merge.append(emenda.autor_bancada.ata)
    if emenda.entidade_id and emenda.entidade.documentacao:
        pdfs_to_merge.append(emenda.entidade.documentacao)
    for anexo in emenda.anexos.order_by("ordem"):
        if anexo.arquivo:
            pdfs_to_merge.append(anexo.arquivo)

    if len(pdfs_to_merge) > 1:
        mesclado = merge_pdfs(pdfs_to_merge)
        if mesclado:
            return mesclado

    buffer.seek(0)
    return buffer
