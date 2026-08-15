from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model

from apps.orcamento.models import Entidade, Exercicio, Faixa, FuncaoGoverno, UnidadeGestora
from apps.parlamento.models import Bancada, Partido, Perfil, Vereador


@pytest.fixture
def exercicio(db):
    return Exercicio.objects.create(
        ano=2026,
        rcl_exercicio_anterior=Decimal("1476254579.40"),
        ano_referencia_rcl=2024,
        numero_vereadores=21,
        situacao=Exercicio.Situacao.ABERTO,
    )


@pytest.fixture
def faixa_coletiva(exercicio):
    return Faixa.objects.create(
        exercicio=exercicio, nome="Emendas Coletivas 1,00%", modalidade=Faixa.Modalidade.COLETIVA,
        percentual_rcl=Decimal("1.00"), sigla_codigo="EPIMB", ordem=0,
    )


@pytest.fixture
def faixa_individual_155(exercicio):
    return Faixa.objects.create(
        exercicio=exercicio, nome="Emendas Individuais 1,55%", modalidade=Faixa.Modalidade.INDIVIDUAL,
        percentual_rcl=Decimal("1.55"), sigla_codigo="EPIMI155",
        percentual_minimo_outras_funcoes=Decimal("50.00"), ordem=1,
    )


@pytest.fixture
def faixa_individual_200(exercicio):
    return Faixa.objects.create(
        exercicio=exercicio, nome="Emendas Individuais 2,00%", modalidade=Faixa.Modalidade.INDIVIDUAL,
        percentual_rcl=Decimal("2.00"), sigla_codigo="EPIMI200",
        percentual_minimo_outras_funcoes=Decimal("50.00"), ordem=2,
    )


@pytest.fixture
def partido_mdb(db):
    return Partido.objects.create(sigla="MDB", nome="Movimento Democrático Brasileiro")


@pytest.fixture
def partido_pl(db):
    return Partido.objects.create(sigla="PL", nome="Partido Liberal")


@pytest.fixture
def vereador_a(partido_mdb):
    return Vereador.objects.create(nome_parlamentar="Fulano de Tal", partido=partido_mdb)


@pytest.fixture
def vereador_b(partido_pl):
    return Vereador.objects.create(nome_parlamentar="Beltrano da Silva", partido=partido_pl)


@pytest.fixture
def bancada_mdb(exercicio, partido_mdb, vereador_a):
    outro = Vereador.objects.create(nome_parlamentar="Sicrano Souza", partido=partido_mdb)
    bancada = Bancada.objects.create(partido=partido_mdb, exercicio=exercicio, coordenador=vereador_a)
    bancada.membros.set([vereador_a, outro])
    return bancada


@pytest.fixture
def funcao_governo(db):
    return FuncaoGoverno.objects.create(nome="Assistência Social", ordem=1, codigo="08")


@pytest.fixture
def subfuncao_governo(funcao_governo):
    from apps.orcamento.models import SubfuncaoGoverno

    return SubfuncaoGoverno.objects.create(funcao=funcao_governo, nome="Assistência Comunitária", codigo="244")


@pytest.fixture
def unidade_gestora_direta(db):
    return UnidadeGestora.objects.create(nome="Prefeitura Administração Direta", exige_documentacao_entidade=False)


@pytest.fixture
def unidade_gestora_entidade(db):
    return UnidadeGestora.objects.create(nome="Entidade Privada Sem Fins Lucrativos", exige_documentacao_entidade=True)


@pytest.fixture
def entidade(db):
    return Entidade.objects.create(nome="Instituto Exemplo")


@pytest.fixture
def orgao_executor(unidade_gestora_direta):
    from apps.orcamento.models import OrgaoExecutor

    return OrgaoExecutor.objects.create(nome="Secretaria Municipal de Saúde", unidade_gestora=unidade_gestora_direta)


@pytest.fixture
def usuario_gabinete_a(vereador_a):
    user = get_user_model().objects.create_user(username="gabinete_a", password="senha-teste-123")
    Perfil.objects.create(user=user, papel=Perfil.Papel.GABINETE, vereador=vereador_a)
    return user


@pytest.fixture
def usuario_gabinete_b(vereador_b):
    user = get_user_model().objects.create_user(username="gabinete_b", password="senha-teste-123")
    Perfil.objects.create(user=user, papel=Perfil.Papel.GABINETE, vereador=vereador_b)
    return user


@pytest.fixture
def usuario_tecnico(db):
    user = get_user_model().objects.create_user(username="tecnico", password="senha-teste-123")
    Perfil.objects.create(user=user, papel=Perfil.Papel.TECNICO)
    return user
