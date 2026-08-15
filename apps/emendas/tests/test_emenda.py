from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.emendas.models import CategoriaEconomica, Emenda, TipoTransferencia


def _criar_emenda(exercicio, faixa, funcao_governo, unidade_gestora, criada_por, autor_kwargs,
                   orgao_executor=None, entidade=None, valor_investimento=Decimal("10000")):
    emenda = Emenda(
        exercicio=exercicio, faixa=faixa, funcao_governo=funcao_governo, unidade_gestora=unidade_gestora,
        orgao_executor=orgao_executor, entidade=entidade, acao_orcamentaria="Descrição de teste",
        objeto_despesa="Objeto de teste", categoria_economica=CategoriaEconomica.INVESTIMENTO,
        valor_investimento=valor_investimento, valor_custeio=Decimal("0"),
        criada_por=criada_por, situacao=Emenda.Situacao.RASCUNHO, **autor_kwargs,
    )
    emenda.full_clean(exclude=["numero", "codigo", "municipio", "partido", "modalidade", "tipo_transferencia"])
    emenda.save()
    return emenda


@pytest.mark.django_db
class TestTetoEsaldo:
    def test_teto_individual_155_bate_com_valor_legal_conhecido(self, faixa_individual_155):
        # Valor de referência publicado no formulário oficial de 2026.
        assert faixa_individual_155.teto_por_vereador().quantize(Decimal("0.01")) == Decimal("1089616.48")

    def test_teto_coletivo_multiplica_pelo_numero_de_membros_da_bancada(self, faixa_coletiva, bancada_mdb):
        teto_unitario = faixa_coletiva.teto_por_vereador()
        assert faixa_coletiva.teto_para(bancada_mdb) == teto_unitario * bancada_mdb.num_membros

    def test_saldo_inicial_igual_ao_teto(self, faixa_individual_155, vereador_a):
        saldo = faixa_individual_155.saldo_de(vereador_a)
        assert saldo["usado"] == Decimal("0")
        assert saldo["saldo"] == saldo["teto"]

    def test_saldo_desconta_emendas_em_rascunho(
        self, exercicio, faixa_individual_155, vereador_a, funcao_governo, unidade_gestora_direta,
        orgao_executor, usuario_gabinete_a,
    ):
        _criar_emenda(
            exercicio, faixa_individual_155, funcao_governo, unidade_gestora_direta, usuario_gabinete_a,
            {"autor_vereador": vereador_a}, orgao_executor=orgao_executor, valor_investimento=Decimal("100000"),
        )
        saldo = faixa_individual_155.saldo_de(vereador_a)
        assert saldo["usado"] == Decimal("100000")
        assert saldo["saldo"] == saldo["teto"] - Decimal("100000")

    def test_emendas_devolvidas_nao_contam_no_saldo(
        self, exercicio, faixa_individual_155, vereador_a, funcao_governo, unidade_gestora_direta,
        orgao_executor, usuario_gabinete_a, usuario_tecnico,
    ):
        emenda = _criar_emenda(
            exercicio, faixa_individual_155, funcao_governo, unidade_gestora_direta, usuario_gabinete_a,
            {"autor_vereador": vereador_a}, orgao_executor=orgao_executor, valor_investimento=Decimal("100000"),
        )
        emenda.enviar()
        emenda.devolver(usuario_tecnico, "Ajustar objeto da despesa.")
        saldo = faixa_individual_155.saldo_de(vereador_a)
        assert saldo["usado"] == Decimal("0")


@pytest.mark.django_db
class TestEnvioBloqueiaEstouro:
    def test_envio_bloqueado_quando_ultrapassa_teto(
        self, exercicio, faixa_coletiva, bancada_mdb, funcao_governo, unidade_gestora_direta,
        orgao_executor, usuario_tecnico,
    ):
        teto = faixa_coletiva.teto_para(bancada_mdb).quantize(Decimal("0.01"))
        emenda = _criar_emenda(
            exercicio, faixa_coletiva, funcao_governo, unidade_gestora_direta, usuario_tecnico,
            {"autor_bancada": bancada_mdb}, orgao_executor=orgao_executor, valor_investimento=teto + Decimal("1"),
        )
        with pytest.raises(ValidationError):
            emenda.enviar()
        emenda.refresh_from_db()
        assert emenda.situacao == Emenda.Situacao.RASCUNHO

    def test_envio_permitido_dentro_do_teto(
        self, exercicio, faixa_coletiva, bancada_mdb, funcao_governo, unidade_gestora_direta,
        orgao_executor, usuario_tecnico,
    ):
        teto = faixa_coletiva.teto_para(bancada_mdb).quantize(Decimal("0.01"))
        emenda = _criar_emenda(
            exercicio, faixa_coletiva, funcao_governo, unidade_gestora_direta, usuario_tecnico,
            {"autor_bancada": bancada_mdb}, orgao_executor=orgao_executor, valor_investimento=teto - Decimal("1"),
        )
        emenda.enviar()
        assert emenda.situacao == Emenda.Situacao.ENVIADA
        assert emenda.enviada_em is not None


@pytest.mark.django_db
class TestDocumentacaoObrigatoria:
    def test_entidade_obrigatoria_quando_unidade_gestora_exige(
        self, exercicio, faixa_individual_155, vereador_a, funcao_governo, unidade_gestora_entidade,
        usuario_gabinete_a,
    ):
        with pytest.raises(ValidationError):
            _criar_emenda(
                exercicio, faixa_individual_155, funcao_governo, unidade_gestora_entidade, usuario_gabinete_a,
                {"autor_vereador": vereador_a},
            )

    def test_envio_bloqueado_sem_pdf_quando_unidade_gestora_exige(
        self, exercicio, faixa_individual_155, vereador_a, funcao_governo, unidade_gestora_entidade,
        entidade, usuario_gabinete_a,
    ):
        emenda = _criar_emenda(
            exercicio, faixa_individual_155, funcao_governo, unidade_gestora_entidade, usuario_gabinete_a,
            {"autor_vereador": vereador_a}, entidade=entidade, valor_investimento=Decimal("1000"),
        )
        with pytest.raises(ValidationError):
            emenda.enviar()


@pytest.mark.django_db
class TestWorkflow:
    def test_fluxo_completo_ate_publicacao(
        self, exercicio, faixa_individual_155, vereador_a, funcao_governo, subfuncao_governo, unidade_gestora_direta,
        orgao_executor, usuario_gabinete_a, usuario_tecnico,
    ):
        emenda = _criar_emenda(
            exercicio, faixa_individual_155, funcao_governo, unidade_gestora_direta, usuario_gabinete_a,
            {"autor_vereador": vereador_a}, orgao_executor=orgao_executor, valor_investimento=Decimal("1000"),
        )
        emenda.enviar()
        emenda.iniciar_conferencia(usuario_tecnico)
        assert emenda.situacao == Emenda.Situacao.EM_CONFERENCIA

        with pytest.raises(ValidationError):
            emenda.publicar(usuario_tecnico)  # falta vinculacao_orcamentaria

        emenda.vinculacao_orcamentaria = "13 01. 08 244 5003 8.500"
        with pytest.raises(ValidationError):
            emenda.publicar(usuario_tecnico)  # falta tipo_transferencia

        emenda.tipo_transferencia = TipoTransferencia.FINALIDADE_DEFINIDA
        emenda.publicar(usuario_tecnico)
        assert emenda.situacao == Emenda.Situacao.PUBLICADA
        assert emenda.publicada_em is not None
        assert emenda.conferida_por == usuario_tecnico
        assert emenda.codigo == "2026.EPIMI.FD.001"
        assert emenda.funcao_governo.nome == "Assistência Social"
        assert emenda.subfuncao_governo.nome == "Assistência Comunitária"

    def test_devolucao_permite_reedicao(
        self, exercicio, faixa_individual_155, vereador_a, funcao_governo, unidade_gestora_direta,
        orgao_executor, usuario_gabinete_a, usuario_tecnico,
    ):
        emenda = _criar_emenda(
            exercicio, faixa_individual_155, funcao_governo, unidade_gestora_direta, usuario_gabinete_a,
            {"autor_vereador": vereador_a}, orgao_executor=orgao_executor, valor_investimento=Decimal("1000"),
        )
        emenda.enviar()
        emenda.devolver(usuario_tecnico, "Corrigir o objeto da despesa.")
        assert emenda.situacao == Emenda.Situacao.DEVOLVIDA
        assert emenda.pode_editar()


@pytest.mark.django_db
class TestCodigoUnico:
    def test_numero_e_codigo_ficam_em_branco_ate_a_publicacao(
        self, exercicio, faixa_individual_155, vereador_a, funcao_governo, unidade_gestora_direta,
        orgao_executor, usuario_gabinete_a,
    ):
        emenda = _criar_emenda(
            exercicio, faixa_individual_155, funcao_governo, unidade_gestora_direta, usuario_gabinete_a,
            {"autor_vereador": vereador_a}, orgao_executor=orgao_executor,
        )
        assert emenda.numero is None
        assert emenda.codigo is None

    def test_numeracao_e_compartilhada_entre_faixas_da_mesma_modalidade_e_tipo(
        self, exercicio, faixa_individual_155, faixa_individual_200, vereador_a, vereador_b, funcao_governo,
        subfuncao_governo, unidade_gestora_direta, orgao_executor, usuario_gabinete_a, usuario_tecnico,
    ):
        # No sistema legado, "2026.EPIMI.FD.001" existia em faixas de percentuais
        # diferentes porque cada uma tinha seu próprio contador reiniciando do zero — o
        # bug que motivou o novo sistema. Aqui o contador é único por modalidade + Tipo
        # de Transferência (definido pelo técnico), então duas emendas de faixas
        # diferentes mas do mesmo tipo recebem números sequenciais sem colidir.
        e1 = _criar_emenda(
            exercicio, faixa_individual_155, funcao_governo, unidade_gestora_direta, usuario_gabinete_a,
            {"autor_vereador": vereador_a}, orgao_executor=orgao_executor,
        )
        e2 = _criar_emenda(
            exercicio, faixa_individual_200, funcao_governo, unidade_gestora_direta, usuario_gabinete_a,
            {"autor_vereador": vereador_b}, orgao_executor=orgao_executor,
        )
        for e in (e1, e2):
            e.vinculacao_orcamentaria = "13 01. 08 244 5003 8.500"
            e.tipo_transferencia = TipoTransferencia.FINALIDADE_DEFINIDA
            e.enviar()
            e.publicar(usuario_tecnico)

        assert e1.codigo == "2026.EPIMI.FD.001"
        assert e2.codigo == "2026.EPIMI.FD.002"

    def test_tipos_de_transferencia_diferentes_tem_contadores_independentes(
        self, exercicio, faixa_individual_155, vereador_a, vereador_b, funcao_governo,
        subfuncao_governo, unidade_gestora_direta, orgao_executor, usuario_gabinete_a, usuario_tecnico,
    ):
        e1 = _criar_emenda(
            exercicio, faixa_individual_155, funcao_governo, unidade_gestora_direta, usuario_gabinete_a,
            {"autor_vereador": vereador_a}, orgao_executor=orgao_executor,
        )
        e2 = _criar_emenda(
            exercicio, faixa_individual_155, funcao_governo, unidade_gestora_direta, usuario_gabinete_a,
            {"autor_vereador": vereador_b}, orgao_executor=orgao_executor,
        )
        e1.vinculacao_orcamentaria = "13 01. 08 244 5003 8.500"
        e2.vinculacao_orcamentaria = "13 01. 08 244 5003 8.500"
        e1.tipo_transferencia = TipoTransferencia.FINALIDADE_DEFINIDA
        e2.tipo_transferencia = TipoTransferencia.TRANSFERENCIA_ESPECIAL
        e1.enviar()
        e2.enviar()
        e1.publicar(usuario_tecnico)
        e2.publicar(usuario_tecnico)

        assert e1.codigo == "2026.EPIMI.FD.001"
        assert e2.codigo == "2026.EPIMI.TE.001"

    def test_publicar_exige_tipo_transferencia(
        self, exercicio, faixa_individual_155, vereador_a, funcao_governo, unidade_gestora_direta,
        orgao_executor, usuario_gabinete_a, usuario_tecnico,
    ):
        emenda = _criar_emenda(
            exercicio, faixa_individual_155, funcao_governo, unidade_gestora_direta, usuario_gabinete_a,
            {"autor_vereador": vereador_a}, orgao_executor=orgao_executor,
        )
        emenda.vinculacao_orcamentaria = "13 01. 08 244 5003 8.500"
        emenda.enviar()
        with pytest.raises(ValidationError):
            emenda.publicar(usuario_tecnico)


@pytest.mark.django_db
class TestIsolamentoEntreGabinetes:
    def test_gabinete_nao_edita_emenda_de_outro_vereador(
        self, client, exercicio, faixa_individual_155, vereador_a, vereador_b, funcao_governo,
        unidade_gestora_direta, orgao_executor, usuario_gabinete_a, usuario_gabinete_b,
    ):
        emenda = _criar_emenda(
            exercicio, faixa_individual_155, funcao_governo, unidade_gestora_direta, usuario_gabinete_a,
            {"autor_vereador": vereador_a}, orgao_executor=orgao_executor,
        )
        client.force_login(usuario_gabinete_b)
        resp = client.get(f"/emendas/painel/emenda/{emenda.pk}/editar/")
        assert resp.status_code == 403

    def test_gabinete_nao_ve_emendas_de_outro_no_painel(
        self, client, exercicio, faixa_individual_155, vereador_a, vereador_b, funcao_governo,
        unidade_gestora_direta, orgao_executor, usuario_gabinete_a, usuario_gabinete_b,
    ):
        _criar_emenda(
            exercicio, faixa_individual_155, funcao_governo, unidade_gestora_direta, usuario_gabinete_a,
            {"autor_vereador": vereador_a}, orgao_executor=orgao_executor,
        )
        client.force_login(usuario_gabinete_b)
        resp = client.get("/emendas/painel/")
        assert resp.status_code == 200
        assert len(resp.context["emendas"]) == 0
