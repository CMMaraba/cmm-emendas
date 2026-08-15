from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import connection, models, transaction
from django.db.models import Max, Q
from django.utils import timezone

from apps.orcamento.models import (
    Entidade,
    Exercicio,
    Faixa,
    FuncaoGoverno,
    OrgaoExecutor,
    ProgramaPPA,
    SubfuncaoGoverno,
    UnidadeGestora,
    resolver_classificacao_funcional,
)
from apps.parlamento.models import Bancada, Partido, Vereador

try:
    from simple_history.models import HistoricalRecords
except ImportError:  # biblioteca opcional em ambientes de teste isolados
    HistoricalRecords = None


class CategoriaEconomica(models.TextChoices):
    INVESTIMENTO = "investimento", "Investimento"
    CUSTEIO = "custeio", "Custeio"


class TipoTransferencia(models.TextChoices):
    FINALIDADE_DEFINIDA = "Finalidade Definida", "Finalidade Definida"
    TRANSFERENCIA_ESPECIAL = "Transferência Especial", "Transferência Especial"


# Sigla usada no código da emenda (ex.: "FD" em "2026.EPIMI.FD.001") — não é gravada no
# banco, só usada para montar o código no momento da publicação.
SIGLA_TIPO_TRANSFERENCIA = {
    TipoTransferencia.FINALIDADE_DEFINIDA: "FD",
    TipoTransferencia.TRANSFERENCIA_ESPECIAL: "TE",
}


class Emenda(models.Model):
    class Situacao(models.TextChoices):
        RASCUNHO = "rascunho", "Rascunho"
        ENVIADA = "enviada", "Enviada"
        EM_CONFERENCIA = "em_conferencia", "Em conferência"
        PUBLICADA = "publicada", "Publicada"
        DEVOLVIDA = "devolvida", "Devolvida para ajuste"

    # --- Automático ---
    exercicio = models.ForeignKey(Exercicio, verbose_name="Exercício", on_delete=models.PROTECT, related_name="emendas")
    faixa = models.ForeignKey(Faixa, verbose_name="Faixa", on_delete=models.PROTECT, related_name="emendas")
    numero = models.PositiveIntegerField(
        "Nº", editable=False, null=True, blank=True,
        help_text="Atribuído pelo sistema só na publicação, depois que o setor técnico define o Tipo de Transferência.",
    )
    codigo = models.CharField(
        "Código", max_length=50, editable=False, null=True, blank=True, default=None,
        help_text="Atribuído pelo sistema só na publicação, depois que o setor técnico define o Tipo de Transferência.",
    )
    codigo_legado = models.CharField("Código no sistema legado", max_length=50, blank=True, editable=False)
    municipio = models.CharField("Município", max_length=100, editable=False)
    autor_vereador = models.ForeignKey(
        Vereador, verbose_name="Vereador", on_delete=models.PROTECT, related_name="emendas", null=True, blank=True
    )
    autor_bancada = models.ForeignKey(
        Bancada, verbose_name="Bancada", on_delete=models.PROTECT, related_name="emendas", null=True, blank=True
    )
    proponente = models.ForeignKey(
        Vereador, verbose_name="Vereador proponente", on_delete=models.PROTECT,
        related_name="emendas_propostas", null=True, blank=True,
        help_text=(
            "Apenas para emendas coletivas: qual vereador da bancada propôs esta emenda "
            "específica (pode ser diferente do coordenador, que só assina a ata)."
        ),
    )
    partido = models.ForeignKey(Partido, verbose_name="Partido Político", on_delete=models.PROTECT, related_name="emendas", editable=False)
    modalidade = models.CharField("Modalidade", max_length=12, choices=Faixa.Modalidade.choices, editable=False)
    tipo_transferencia = models.CharField(
        "Tipo de Transferência", max_length=100, choices=TipoTransferencia.choices, blank=True,
        help_text="Definido pelo setor técnico na conferência — usado para gerar o número/código da emenda na publicação.",
    )

    # --- Gabinete / bancada (mérito) ---
    funcao_governo = models.ForeignKey(
        FuncaoGoverno, verbose_name="Função de Governo", on_delete=models.PROTECT,
        related_name="emendas", null=True, blank=True,
        help_text="Calculada automaticamente pelo setor técnico a partir da Vinculação Orçamentária.",
    )
    unidade_gestora = models.ForeignKey(
        UnidadeGestora, verbose_name="Unidade Gestora Vinculada", on_delete=models.PROTECT, related_name="emendas"
    )
    orgao_executor = models.ForeignKey(
        OrgaoExecutor, verbose_name="Órgão Executor", on_delete=models.PROTECT,
        related_name="emendas", null=True, blank=True,
    )
    entidade = models.ForeignKey(
        Entidade, verbose_name="Entidade (OSC)", on_delete=models.PROTECT,
        related_name="emendas", null=True, blank=True,
    )
    acao_orcamentaria = models.TextField(
        "Ação Orçamentária",
        help_text=(
            "O que será feito com o valor da emenda, em termos orçamentários — a atividade "
            "ou o programa que será custeado. Ex.: 'Apoio a atividades desenvolvidas pela "
            "Seaspac'. Este texto alimenta a coluna 'Ação Orçamentária' da tabela pública."
        ),
    )
    objeto_despesa = models.TextField(
        "Objeto da Despesa",
        help_text=(
            "O que exatamente será adquirido, contratado ou executado com o valor da "
            "emenda — de forma específica. Ex.: 'Apoio a atividades desenvolvidas pela "
            "Seaspac na assistência a famílias em situação de vulnerabilidade social'."
        ),
    )
    categoria_economica = models.CharField(
        "Categoria Econômica", max_length=20, choices=CategoriaEconomica.choices
    )
    valor_custeio = models.DecimalField("Valor de Custeio (R$)", max_digits=14, decimal_places=2, default=Decimal("0"))
    valor_investimento = models.DecimalField("Valor de Investimento (R$)", max_digits=14, decimal_places=2, default=Decimal("0"))
    valor_previsto = models.DecimalField("Valor Previsto (R$)", max_digits=14, decimal_places=2, editable=False, default=Decimal("0"))
    documentacao_entidade = models.FileField(
        "Documentos da Emenda (PDF da entidade de destino)",
        upload_to="documentos_emendas/%Y/", blank=True, null=True,
    )

    # --- Setor técnico ---
    vinculacao_orcamentaria = models.CharField(
        "Vinculação Orçamentária", max_length=150, blank=True,
        help_text="Classificação Funcional Programática. Ex.: 13 01. 08 244 5003 8.500",
    )
    subfuncao_governo = models.ForeignKey(
        SubfuncaoGoverno, verbose_name="Subfunção de Governo", on_delete=models.PROTECT,
        related_name="emendas", null=True, blank=True,
    )
    programa_ppa = models.ForeignKey(
        ProgramaPPA, verbose_name="Programa PPA", on_delete=models.PROTECT,
        related_name="emendas", null=True, blank=True,
    )
    data_reserva = models.DateField("Data da reserva orçamentária", null=True, blank=True)

    # --- Controle ---
    situacao = models.CharField("Situação", max_length=20, choices=Situacao.choices, default=Situacao.RASCUNHO)
    criada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="Criada por", on_delete=models.PROTECT, related_name="emendas_criadas"
    )
    conferida_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, verbose_name="Conferida por", on_delete=models.PROTECT,
        related_name="emendas_conferidas", null=True, blank=True,
    )
    enviada_em = models.DateTimeField(null=True, blank=True)
    publicada_em = models.DateTimeField(null=True, blank=True)
    motivo_devolucao = models.TextField("Motivo da devolução", blank=True)
    pdf_gerado = models.FileField("PDF gerado", upload_to="emendas/pdf/%Y/", blank=True, null=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    if HistoricalRecords is not None:
        history = HistoricalRecords()

    class Meta:
        verbose_name = "Emenda"
        verbose_name_plural = "Emendas"
        ordering = ["exercicio", "faixa", "numero"]
        # Só o código é travado por unicidade. O "numero" sozinho NÃO pode ter unique
        # constraint aqui: as 689 emendas importadas do legado têm numero repetido entre
        # as faixas de 1,55% e 2,00% (cada uma tinha seu próprio contador reiniciando do
        # zero) — exatamente o histórico que gerou os "289 códigos duplicados" do
        # sistema antigo. A proteção contra duplicidade de verdade é o código (sempre
        # único, calculado atomicamente em _atribuir_numero_codigo) e a query, também
        # atômica, que soma 1 ao maior "numero" já usado por modalidade+tipo.
        unique_together = [("exercicio", "codigo")]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(autor_vereador__isnull=False, autor_bancada__isnull=True)
                    | Q(autor_vereador__isnull=True, autor_bancada__isnull=False)
                ),
                name="emenda_autor_exclusivo",
            ),
        ]

    def __str__(self):
        return f"{self.codigo} — {self.autor_nome}"

    # --- Derivações ---
    @property
    def autor(self):
        return self.autor_vereador or self.autor_bancada

    @property
    def autor_nome(self):
        if self.autor_vereador_id:
            return self.autor_vereador.nome_parlamentar
        if self.autor_bancada_id:
            if self.proponente_id:
                return self.proponente.nome_parlamentar
            return f"Bancada {self.autor_bancada.partido.sigla}"
        return "—"

    @property
    def destino(self):
        return self.entidade or self.orgao_executor

    @property
    def destino_nome(self):
        return self.destino.nome if self.destino else "—"

    @property
    def exige_documentacao(self):
        return bool(self.unidade_gestora_id and self.unidade_gestora.exige_documentacao_entidade)

    @property
    def documentacao_satisfeita(self):
        # A entidade pode já ter documentação própria cadastrada (Entidade.documentacao,
        # mantida pelo setor técnico) — nesse caso o vereador/bancada não precisa reenviar
        # o mesmo PDF por emenda (ver EmendaForm/emenda_form.html: o campo de upload fica
        # desabilitado quando a entidade selecionada já tem documentação).
        if self.documentacao_entidade:
            return True
        return bool(self.entidade_id and self.entidade.documentacao)

    def clean(self):
        errors = {}
        if bool(self.autor_vereador_id) == bool(self.autor_bancada_id):
            errors["autor_vereador"] = "Informe exatamente um autor: vereador OU bancada."
        if self.faixa_id:
            if self.faixa.modalidade == Faixa.Modalidade.INDIVIDUAL and not self.autor_vereador_id:
                errors["autor_vereador"] = "Faixas individuais exigem um vereador como autor."
            if self.faixa.modalidade == Faixa.Modalidade.COLETIVA and not self.autor_bancada_id:
                errors["autor_bancada"] = "Faixas coletivas exigem uma bancada como autora."
            if self.faixa.modalidade == Faixa.Modalidade.INDIVIDUAL and self.proponente_id:
                errors["proponente"] = "O proponente só se aplica a emendas coletivas."
        if self.autor_bancada_id and self.proponente_id:
            if not self.autor_bancada.membros.filter(pk=self.proponente_id).exists():
                errors["proponente"] = "O proponente deve ser um dos membros da bancada."
        if self.unidade_gestora_id and self.unidade_gestora.exige_documentacao_entidade:
            if not self.entidade_id:
                errors["entidade"] = "Esta unidade gestora exige selecionar a entidade de destino."
        elif self.orgao_executor_id is None and self.unidade_gestora_id:
            errors["orgao_executor"] = "Selecione o órgão executor."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.valor_previsto = (self.valor_custeio or Decimal("0")) + (self.valor_investimento or Decimal("0"))
        if self.pk is None:
            self.municipio = self.municipio or self.exercicio.municipio
            self.modalidade = self.faixa.modalidade
            if self.autor_vereador_id:
                self.partido = self.autor_vereador.partido
            elif self.autor_bancada_id:
                self.partido = self.autor_bancada.partido
        # numero/codigo NÃO são atribuídos aqui: só na publicação, depois que o setor
        # técnico define o Tipo de Transferência (ver publicar() e
        # _atribuir_numero_codigo()) — o número não pode ser calculado/sugerido
        # automaticamente para o vereador, é uma decisão do setor técnico.
        super().save(*args, **kwargs)

    def _atribuir_numero_codigo(self):
        """Chamado só por publicar(): monta "{ano}.EPIM{I|B}.{FD|TE}.{nº:03d}" pegando o
        próximo número disponível entre TODAS as faixas da mesma modalidade e do mesmo
        Tipo de Transferência no exercício — não por faixa/percentual, para não repetir
        o bug do legado de códigos duplicados entre faixas de percentuais diferentes."""
        sigla_modalidade = "I" if self.modalidade == Faixa.Modalidade.INDIVIDUAL else "B"
        sigla_tipo = SIGLA_TIPO_TRANSFERENCIA.get(self.tipo_transferencia, "")
        qs = Emenda.objects.filter(
            exercicio_id=self.exercicio_id,
            modalidade=self.modalidade,
            tipo_transferencia=self.tipo_transferencia,
        )
        if connection.vendor == "postgresql":
            qs = qs.select_for_update()
        ultimo = qs.aggregate(Max("numero"))["numero__max"] or 0
        self.numero = ultimo + 1
        self.codigo = f"{self.exercicio.ano}.EPIM{sigla_modalidade}.{sigla_tipo}.{self.numero:03d}"

    # --- Workflow ---
    def pode_editar(self):
        return self.situacao in (self.Situacao.RASCUNHO, self.Situacao.DEVOLVIDA)

    def enviar(self):
        if not self.pode_editar():
            raise ValidationError("Esta emenda não pode ser enviada no estado atual.")
        if self.exige_documentacao and not self.documentacao_satisfeita:
            raise ValidationError("A documentação da entidade de destino é obrigatória para este destino.")
        saldo = self.faixa.saldo_de(self.autor)
        if saldo["saldo"] < 0:
            raise ValidationError(
                "O envio está bloqueado: o limite da faixa foi ultrapassado. Ajuste os valores antes de enviar."
            )
        self.situacao = self.Situacao.ENVIADA
        self.enviada_em = timezone.now()
        self.save()

    def iniciar_conferencia(self, usuario):
        if self.situacao != self.Situacao.ENVIADA:
            raise ValidationError("Só é possível iniciar a conferência de emendas enviadas.")
        self.situacao = self.Situacao.EM_CONFERENCIA
        self.conferida_por = usuario
        self.save()

    def publicar(self, usuario):
        if self.situacao not in (self.Situacao.ENVIADA, self.Situacao.EM_CONFERENCIA):
            raise ValidationError("Só é possível publicar emendas enviadas ou em conferência.")
        if not self.vinculacao_orcamentaria:
            raise ValidationError("Informe a vinculação orçamentária antes de publicar.")
        if not self.tipo_transferencia:
            raise ValidationError("Selecione o Tipo de Transferência antes de publicar.")
        funcao, subfuncao = resolver_classificacao_funcional(self.vinculacao_orcamentaria)
        if not funcao or not subfuncao:
            raise ValidationError(
                "Não foi possível identificar a função/subfunção de governo a partir da "
                "Vinculação Orçamentária informada. Confira o código digitado."
            )
        with transaction.atomic():
            self.funcao_governo = funcao
            self.subfuncao_governo = subfuncao
            if not self.codigo:
                self._atribuir_numero_codigo()
            self.situacao = self.Situacao.PUBLICADA
            self.conferida_por = usuario
            self.publicada_em = timezone.now()
            self.save()

    def devolver(self, usuario, motivo):
        # Inclui PUBLICADA de propósito: o Vereador pode querer alterar algo depois de
        # publicada, ou a Prefeitura pode recusar e mandar corrigir. Devolver tira a
        # emenda da tabela pública imediatamente (só PUBLICADA aparece lá) e libera de
        # volta o saldo da faixa (DEVOLVIDA não entra em Faixa.saldo_de()). O código já
        # atribuído (self.codigo) é preservado — ao publicar de novo, _atribuir_numero_
        # codigo() não roda outra vez porque o código já existe.
        if self.situacao not in (self.Situacao.ENVIADA, self.Situacao.EM_CONFERENCIA, self.Situacao.PUBLICADA):
            raise ValidationError("Só é possível devolver emendas enviadas, em conferência ou publicadas.")
        if not motivo:
            raise ValidationError("Informe o motivo da devolução.")
        self.situacao = self.Situacao.DEVOLVIDA
        self.conferida_por = usuario
        self.motivo_devolucao = motivo
        self.save()


class EmendaDocumento(models.Model):
    """Anexos adicionais, para quando a documentação da entidade vem em mais de um PDF."""

    emenda = models.ForeignKey(Emenda, verbose_name="Emenda", on_delete=models.CASCADE, related_name="anexos")
    arquivo = models.FileField("Arquivo (PDF)", upload_to="emendas/anexos/%Y/")
    descricao = models.CharField("Descrição", max_length=200, blank=True)
    ordem = models.PositiveIntegerField("Ordem", default=0)
    enviado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Anexo da emenda"
        verbose_name_plural = "Anexos da emenda"
        ordering = ["emenda", "ordem"]

    def __str__(self):
        return self.descricao or self.arquivo.name
