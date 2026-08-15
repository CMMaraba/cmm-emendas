"""Semeia dados públicos oficiais que faltavam nos catálogos:

1. Códigos de Função (2 dígitos) e Subfunção (3 dígitos) de Governo, conforme o Anexo
   da Portaria MOG nº 42/1999 (Ministério da Fazenda / Tesouro Nacional) — a mesma
   classificação usada por União, Estados, DF e Municípios, reproduzida em
   https://conteudo.tesouro.gov.br/manuais/ . Usados para calcular automaticamente a
   função/subfunção a partir da Classificação Funcional Programática (rubrica) digitada
   pelo setor técnico.
2. Órgãos executores (secretarias, autarquias, fundação e procuradoria) da estrutura
   administrativa da Prefeitura Municipal de Marabá, conforme
   https://maraba.pa.gov.br/secretarias/ (informação pública).

Idempotente: pode ser rodado mais de uma vez sem duplicar nem apagar dados existentes —
só cadastra o que ainda não existe e completa códigos que estavam em branco.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.orcamento.models import FuncaoGoverno, OrgaoExecutor, SubfuncaoGoverno, UnidadeGestora

# (código da função, nome oficial): [(código da subfunção, nome oficial), ...]
FUNCOES_SUBFUNCOES = {
    ("01", "Legislativa"): [("031", "Ação Legislativa"), ("032", "Controle Externo")],
    ("02", "Judiciária"): [("061", "Ação Judiciária"), ("062", "Defesa do Interesse Público no Processo Judiciário")],
    ("03", "Essencial à Justiça"): [("091", "Defesa da Ordem Jurídica"), ("092", "Representação Judicial e Extrajudicial")],
    ("04", "Administração"): [
        ("121", "Planejamento e Orçamento"), ("122", "Administração Geral"),
        ("123", "Administração Financeira"), ("124", "Controle Interno"),
        ("125", "Normatização e Fiscalização"), ("126", "Tecnologia da Informação"),
        ("127", "Ordenamento Territorial"), ("128", "Formação de Recursos Humanos"),
        ("129", "Administração de Receitas"), ("130", "Administração de Concessões"),
        ("131", "Comunicação Social"),
    ],
    ("05", "Defesa Nacional"): [("151", "Defesa Aérea"), ("152", "Defesa Naval"), ("153", "Defesa Terrestre")],
    ("06", "Segurança Pública"): [("181", "Policiamento"), ("182", "Defesa Civil"), ("183", "Informação e Inteligência")],
    ("07", "Relações Exteriores"): [("211", "Relações Diplomáticas"), ("212", "Cooperação Internacional")],
    ("08", "Assistência Social"): [
        ("241", "Assistência ao Idoso"), ("242", "Assistência ao Portador de Deficiência"),
        ("243", "Assistência à Criança e ao Adolescente"), ("244", "Assistência Comunitária"),
    ],
    ("09", "Previdência Social"): [
        ("271", "Previdência Básica"), ("272", "Previdência do Regime Estatutário"),
        ("273", "Previdência Complementar"), ("274", "Previdência Especial"),
    ],
    ("10", "Saúde"): [
        ("301", "Atenção Básica"), ("302", "Assistência Hospitalar e Ambulatorial"),
        ("303", "Suporte Profilático e Terapêutico"), ("304", "Vigilância Sanitária"),
        ("305", "Vigilância Epidemiológica"), ("306", "Alimentação e Nutrição"),
    ],
    ("11", "Trabalho"): [
        ("331", "Proteção e Benefícios ao Trabalhador"), ("332", "Relações de Trabalho"),
        ("333", "Empregabilidade"), ("334", "Fomento ao Trabalho"),
    ],
    ("12", "Educação"): [
        ("361", "Ensino Fundamental"), ("362", "Ensino Médio"), ("363", "Ensino Profissional"),
        ("364", "Ensino Superior"), ("365", "Educação Infantil"),
        ("366", "Educação de Jovens e Adultos"), ("367", "Educação Especial"), ("368", "Educação Básica"),
    ],
    ("13", "Cultura"): [("391", "Patrimônio Histórico, Artístico e Arqueológico"), ("392", "Difusão Cultural")],
    ("14", "Direitos da Cidadania"): [
        ("421", "Custódia e Reintegração Social"),
        ("422", "Direitos Individuais, Coletivos e Difusos"),
        ("423", "Assistência aos Povos Indígenas"),
    ],
    ("15", "Urbanismo"): [("451", "Infra-estrutura Urbana"), ("452", "Serviços Urbanos"), ("453", "Transportes Coletivos Urbanos")],
    ("16", "Habitação"): [("481", "Habitação Rural"), ("482", "Habitação Urbana")],
    ("17", "Saneamento"): [("511", "Saneamento Básico Rural"), ("512", "Saneamento Básico Urbano")],
    ("18", "Gestão Ambiental"): [
        ("541", "Preservação e Conservação Ambiental"), ("542", "Controle Ambiental"),
        ("543", "Recuperação de Áreas Degradadas"), ("544", "Recursos Hídricos"), ("545", "Meteorologia"),
    ],
    ("19", "Ciência e Tecnologia"): [
        ("571", "Desenvolvimento Científico"), ("572", "Desenvolvimento Tecnológico e Engenharia"),
        ("573", "Difusão do Conhecimento Científico e Tecnológico"),
    ],
    ("20", "Agricultura"): [
        ("605", "Abastecimento"), ("606", "Extensão Rural"), ("607", "Irrigação"),
        ("608", "Promoção da Produção Agropecuária"), ("609", "Defesa Agropecuária"),
    ],
    ("21", "Organização Agrária"): [("631", "Reforma Agrária"), ("632", "Colonização")],
    ("22", "Indústria"): [
        ("661", "Promoção Industrial"), ("662", "Produção Industrial"), ("663", "Mineração"),
        ("664", "Propriedade Industrial"), ("665", "Normalização e Qualidade"),
    ],
    ("23", "Comércio e Serviços"): [
        ("691", "Promoção Comercial"), ("692", "Comercialização"), ("693", "Comércio Exterior"),
        ("694", "Serviços Financeiros"), ("695", "Turismo"),
    ],
    ("24", "Comunicações"): [("721", "Comunicações Postais"), ("722", "Telecomunicações")],
    ("25", "Energia"): [
        ("751", "Conservação de Energia"), ("752", "Energia Elétrica"),
        ("753", "Combustíveis Minerais"), ("754", "Biocombustíveis"),
    ],
    ("26", "Transporte"): [
        ("781", "Transporte Aéreo"), ("782", "Transporte Rodoviário"), ("783", "Transporte Ferroviário"),
        ("784", "Transporte Hidroviário"), ("785", "Transportes Especiais"),
    ],
    ("27", "Desporto e Lazer"): [("811", "Desporto de Rendimento"), ("812", "Desporto Comunitário"), ("813", "Lazer")],
    ("28", "Encargos Especiais"): [
        ("841", "Refinanciamento da Dívida Interna"), ("842", "Refinanciamento da Dívida Externa"),
        ("843", "Serviço da Dívida Interna"), ("844", "Serviço da Dívida Externa"),
        ("845", "Outras Transferências"), ("846", "Outros Encargos Especiais"),
        ("847", "Transferências para a Educação Básica"),
    ],
}

# Nomes que já existiam sem "Municipal" (padronização pedida em 15/08/2026) e a
# Superintendência que ganhou a sigla no nome — mapeamento aplicado antes do
# get_or_create abaixo, para RENOMEAR o registro já existente em vez de duplicá-lo.
RENOMEIA_ORGAOS = {
    "Secretaria de Assistência Social, Proteção e Assuntos Comunitários":
        "Secretaria Municipal de Assistência Social, Proteção e Assuntos Comunitários",
    "Secretaria de Comunicação Social": "Secretaria Municipal de Comunicação Social",
    "Secretaria de Mineração, Indústria, Comércio, Ciência e Tecnologia":
        "Secretaria Municipal de Mineração, Indústria, Comércio, Ciência e Tecnologia",
    "Secretaria de Planejamento": "Secretaria Municipal de Planejamento",
    "Superintendência de Desenvolvimento Urbano de Marabá":
        "Superintendência de Desenvolvimento Urbano de Marabá (SDU)",
}

# (nome do órgão, sigla, nome da UnidadeGestora a que pertence)
ORGAOS_MARABA = [
    ("Gabinete do Prefeito", "", "Prefeitura Administração Direta"),
    ("Procuradoria Geral do Município", "PROGEM", "Prefeitura Administração Direta"),
    ("Controladoria Geral do Município", "CGM", "Prefeitura Administração Direta"),
    ("Secretaria Municipal de Administração", "SEMAD", "Prefeitura Administração Direta"),
    ("Secretaria Municipal de Agricultura", "SEAGRI", "Prefeitura Administração Direta"),
    ("Secretaria Municipal de Assistência Social, Proteção e Assuntos Comunitários", "SEASPAC", "Prefeitura Administração Direta"),
    ("Secretaria Municipal de Comunicação Social", "SECOM", "Prefeitura Administração Direta"),
    ("Secretaria Municipal de Cultura", "SECULT", "Prefeitura Administração Direta"),
    ("Departamento Municipal de Trânsito Urbano (DMTU)", "DMTU", "Prefeitura Administração Direta"),
    ("Secretaria Municipal de Educação", "SEMED", "Prefeitura Administração Direta"),
    ("Secretaria Municipal de Esporte e Lazer", "SEMEL", "Prefeitura Administração Direta"),
    ("Secretaria Municipal de Finanças", "SEFIN", "Prefeitura Administração Direta"),
    ("Secretaria Municipal de Gestão Fazendária", "SEGFAZ", "Prefeitura Administração Direta"),
    ("Secretaria Municipal de Meio Ambiente", "SEMMA", "Prefeitura Administração Direta"),
    ("Secretaria Municipal de Mineração, Indústria, Comércio, Ciência e Tecnologia", "SICOM", "Prefeitura Administração Direta"),
    ("Secretaria Municipal de Saúde", "SMS", "Prefeitura Administração Direta"),
    ("Secretaria Municipal de Segurança Institucional", "SMSI", "Prefeitura Administração Direta"),
    ("Secretaria Municipal de Planejamento", "SEPLAN", "Prefeitura Administração Direta"),
    ("Secretaria Municipal de Turismo", "SEMTUR", "Prefeitura Administração Direta"),
    ("Secretaria Municipal de Viação e Obras Públicas", "SEVOP", "Prefeitura Administração Direta"),
    ("Fundação Casa da Cultura", "FCCM", "Prefeitura Administração Indireta (Fundação Casa da Cultura)"),
    (
        "Instituto de Previdência Social dos Servidores Públicos do Município de Marabá",
        "IPASEMAR",
        "Prefeitura Administração Indireta (IPASEMAR)",
    ),
    ("Serviço de Saneamento Ambiental de Marabá", "SSAM", "Prefeitura Administração Indireta (SSAM)"),
    (
        "Superintendência de Desenvolvimento Urbano de Marabá (SDU)",
        "SDU",
        "Prefeitura Administração Indireta (SDU)",
    ),
]


class Command(BaseCommand):
    help = "Semeia códigos oficiais de função/subfunção de governo e órgãos executores públicos de Marabá."

    @transaction.atomic
    def handle(self, *args, **options):
        funcoes_criadas = funcoes_atualizadas = 0
        subfuncoes_criadas = subfuncoes_atualizadas = 0
        for (codigo_funcao, nome_funcao), subfuncoes in FUNCOES_SUBFUNCOES.items():
            funcao = FuncaoGoverno.objects.filter(nome=nome_funcao).first()
            if funcao is None:
                funcao = FuncaoGoverno.objects.create(nome=nome_funcao, codigo=codigo_funcao)
                funcoes_criadas += 1
            elif funcao.codigo != codigo_funcao:
                funcao.codigo = codigo_funcao
                funcao.save(update_fields=["codigo"])
                funcoes_atualizadas += 1

            for codigo_subfuncao, nome_subfuncao in subfuncoes:
                subfuncao = SubfuncaoGoverno.objects.filter(funcao=funcao, nome=nome_subfuncao).first()
                if subfuncao is None:
                    SubfuncaoGoverno.objects.create(funcao=funcao, nome=nome_subfuncao, codigo=codigo_subfuncao)
                    subfuncoes_criadas += 1
                elif subfuncao.codigo != codigo_subfuncao:
                    subfuncao.codigo = codigo_subfuncao
                    subfuncao.save(update_fields=["codigo"])
                    subfuncoes_atualizadas += 1

        orgaos_renomeados = 0
        for nome_antigo, nome_novo in RENOMEIA_ORGAOS.items():
            orgaos_renomeados += OrgaoExecutor.objects.filter(nome=nome_antigo).update(nome=nome_novo)

        orgaos_criados = 0
        for nome, sigla, nome_unidade in ORGAOS_MARABA:
            unidade = UnidadeGestora.objects.filter(nome=nome_unidade).first()
            if unidade is None:
                self.stdout.write(self.style.WARNING(
                    f"Unidade gestora '{nome_unidade}' não encontrada — pulando órgão '{nome}'."
                ))
                continue
            _, criado = OrgaoExecutor.objects.get_or_create(
                nome=nome, unidade_gestora=unidade, defaults={"ativo": True}
            )
            if criado:
                orgaos_criados += 1

        self.stdout.write(self.style.SUCCESS(
            f"Funções: {funcoes_criadas} criadas, {funcoes_atualizadas} com código atualizado. "
            f"Subfunções: {subfuncoes_criadas} criadas, {subfuncoes_atualizadas} com código atualizado. "
            f"Órgãos executores: {orgaos_criados} criados, {orgaos_renomeados} renomeados."
        ))
