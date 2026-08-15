"""Semeia os catálogos e o exercício de 2026 a partir dos dados públicos hoje em
https://maraba.pa.leg.br/emendas/. Idempotente: pode ser rodado mais de uma vez."""

from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.orcamento.models import Exercicio, Faixa, FuncaoGoverno, UnidadeGestora
from apps.parlamento.models import Bancada, Partido, Vereador

AREAS = [
    "Administração", "Habitação",
    "Agricultura", "Indústria",
    "Assistência Social", "Infraestrutura e Logística",
    "Ciência e Tecnologia", "Judiciária",
    "Comércio e Serviços", "Legislativa",
    "Comunicações", "Organização Agrária",
    "Cultura", "Previdência Social",
    "Defesa Nacional", "Relações Exteriores",
    "Desporto e Lazer", "Saúde",
    "Direitos da Cidadania", "Saneamento",
    "Encargos Especiais", "Segurança Pública",
    "Educação", "Trabalho",
    "Energia", "Transporte",
    "Essencial à Justiça", "Urbanismo",
    "Gestão Ambiental", "Outros (especificar) – evento religioso",
]

UNIDADES_GESTORAS = [
    ("Prefeitura Administração Direta", False),
    ("Prefeitura Administração Indireta (SSAM)", False),
    ("Prefeitura Administração Indireta (Fundação Casa da Cultura)", False),
    ("Prefeitura Administração Indireta (SDU)", False),
    ("Prefeitura Administração Indireta (IPASEMAR)", False),
    ("Entidade Privada Sem Fins Lucrativos", True),
]

# (nome parlamentar, sigla do partido)
VEREADORES_2026 = [
    ("Aerton Grande", "União Brasil"),
    ("Cabo Rodrigo", "PL"),
    ("Cristina Mutran", "MDB"),
    ("Dato do Ônibus", "União Brasil"),
    ("Dean Guimarães", "PSD"),
    ("Fernando Henrique", "PL"),
    ("Ilker Moraes", "MDB"),
    ("Jimmyson Pacheco", "PL"),
    ("Jocenilson Silva", "PSD"),
    ("Maiana Stringari", "PDT"),
    ("Marcelo Alves", "PT"),
    ("Márcio do São Félix", "PSDB"),
    ("Marcos Andrade", "PSD"),
    ("Marcos Paulo", "PDT"),
    ("Orlando Elias", "PSB"),
    ("Pastor Ronisteu", "PL"),
    ("Pedrinho Correa", "DEM"),
    ("Priscila Veloso", "PSD"),
    ("Ronaldo da 33", "PDT"),
    ("Ubirajara Sompré", "MDB"),
    ("Vanda Américo", "União Brasil"),
]

# Coordenador conhecido a partir da ata pública da bancada; demais partidos ficam sem
# coordenador definido automaticamente — corrigir depois via admin se necessário.
COORDENADORES_CONHECIDOS = {"MDB": "Ilker Moraes"}


class Command(BaseCommand):
    help = "Semeia partidos, vereadores, bancadas, catálogos e o exercício de 2026."

    @transaction.atomic
    def handle(self, *args, **options):
        self._seed_areas()
        self._seed_unidades_gestoras()
        siglas = self._seed_partidos()
        vereadores = self._seed_vereadores(siglas)
        exercicio = self._seed_exercicio()
        self._seed_bancadas(exercicio, siglas, vereadores)
        self.stdout.write(self.style.SUCCESS("Catálogos e exercício de 2026 semeados com sucesso."))

    def _seed_areas(self):
        for i, nome in enumerate(AREAS):
            FuncaoGoverno.objects.get_or_create(nome=nome, defaults={"ordem": i})
        self.stdout.write(f"  Funções de governo: {len(AREAS)} verificadas.")

    def _seed_unidades_gestoras(self):
        for i, (nome, exige_doc) in enumerate(UNIDADES_GESTORAS):
            UnidadeGestora.objects.update_or_create(
                nome=nome, defaults={"exige_documentacao_entidade": exige_doc, "ordem": i}
            )
        self.stdout.write(f"  Unidades gestoras: {len(UNIDADES_GESTORAS)} verificadas.")

    def _seed_partidos(self):
        siglas = {sigla for _, sigla in VEREADORES_2026}
        objetos = {}
        for sigla in siglas:
            objetos[sigla], _ = Partido.objects.get_or_create(sigla=sigla)
        self.stdout.write(f"  Partidos: {len(siglas)} verificados.")
        return objetos

    def _seed_vereadores(self, partidos):
        vereadores = {}
        for nome, sigla in VEREADORES_2026:
            vereador, _ = Vereador.objects.get_or_create(
                nome_parlamentar=nome, defaults={"partido": partidos[sigla]}
            )
            if vereador.partido_id != partidos[sigla].id:
                vereador.partido = partidos[sigla]
                vereador.save(update_fields=["partido"])
            vereadores[nome] = vereador
        self.stdout.write(f"  Vereadores: {len(vereadores)} verificados.")
        return vereadores

    def _seed_exercicio(self):
        exercicio, criado = Exercicio.objects.get_or_create(
            ano=2026,
            defaults={
                "municipio": "Marabá",
                "rcl_exercicio_anterior": Decimal("1476254579.40"),
                "ano_referencia_rcl": 2024,
                "numero_vereadores": 21,
                "situacao": Exercicio.Situacao.ABERTO,
            },
        )
        if criado:
            faixas = [
                {
                    "nome": "Emendas Coletivas 1,00%",
                    "modalidade": Faixa.Modalidade.COLETIVA,
                    "percentual_rcl": Decimal("1.00"),
                    "sigla_codigo": "EPIMB",
                    "ordem": 0,
                },
                {
                    "nome": "Emendas Individuais 1,55%",
                    "modalidade": Faixa.Modalidade.INDIVIDUAL,
                    "percentual_rcl": Decimal("1.55"),
                    "sigla_codigo": "EPIMI155",
                    "percentual_minimo_outras_funcoes": Decimal("50.00"),
                    "ordem": 1,
                },
                {
                    "nome": "Emendas Individuais 2,00%",
                    "modalidade": Faixa.Modalidade.INDIVIDUAL,
                    "percentual_rcl": Decimal("2.00"),
                    "sigla_codigo": "EPIMI200",
                    "percentual_minimo_outras_funcoes": Decimal("50.00"),
                    "ordem": 2,
                },
            ]
            for dados in faixas:
                Faixa.objects.create(exercicio=exercicio, **dados)
            self.stdout.write("  Exercício 2026 criado com 3 faixas.")
        else:
            self.stdout.write("  Exercício 2026 já existia — mantido como estava.")
        return exercicio

    def _seed_bancadas(self, exercicio, partidos, vereadores):
        por_partido = {}
        for nome, sigla in VEREADORES_2026:
            por_partido.setdefault(sigla, []).append(nome)

        for sigla, nomes in por_partido.items():
            coordenador_nome = COORDENADORES_CONHECIDOS.get(sigla, nomes[0])
            bancada, criada = Bancada.objects.get_or_create(
                partido=partidos[sigla],
                exercicio=exercicio,
                defaults={"coordenador": vereadores[coordenador_nome]},
            )
            bancada.membros.set([vereadores[n] for n in nomes])
        self.stdout.write(f"  Bancadas 2026: {len(por_partido)} verificadas.")
