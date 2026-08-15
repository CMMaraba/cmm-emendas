from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Sum

from apps.parlamento.models import Bancada, Vereador


class Exercicio(models.Model):
    class Situacao(models.TextChoices):
        ABERTO = "aberto", "Aberto"
        ENCERRADO = "encerrado", "Encerrado"

    ano = models.PositiveIntegerField("Ano", unique=True)
    municipio = models.CharField("Município", max_length=100, default="Marabá")
    rcl_exercicio_anterior = models.DecimalField(
        "Receita Corrente Líquida do exercício anterior (R$)", max_digits=16, decimal_places=2
    )
    ano_referencia_rcl = models.PositiveIntegerField(
        "Ano de referência da RCL", help_text="Ex.: para o exercício de 2026, a RCL é a de 2024."
    )
    numero_vereadores = models.PositiveIntegerField("Número de vereadores da Casa")
    prazo_envio = models.DateField("Prazo para envio das emendas", null=True, blank=True)
    base_legal = models.TextField(
        "Base legal (rodapé das exportações)",
        blank=True,
        default=(
            "Base Legal: Art. 147-A e 147-B da Lei Orgânica do Município de Marabá | "
            "Vedada destinação para pessoal."
        ),
    )
    observacao_legal_formulario = models.TextField(
        "Observação legal impressa no formulário (página 2)",
        blank=True,
        default=(
            "Deverá ser observado o estabelecido na Lei Complementar Municipal Nº 23/2025, "
            "no que se refere à destinação das emendas impositivas."
        ),
    )
    situacao = models.CharField("Situação", max_length=10, choices=Situacao.choices, default=Situacao.ABERTO)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Exercício orçamentário"
        verbose_name_plural = "Exercícios orçamentários"
        ordering = ["-ano"]

    def __str__(self):
        return f"Exercício {self.ano}"

    @classmethod
    def atual(cls):
        return cls.objects.filter(situacao=cls.Situacao.ABERTO).order_by("-ano").first()

    def clonar_para(self, novo_ano):
        """Abre um novo exercício copiando RCL, nº de vereadores e faixas do atual."""
        novo = Exercicio.objects.create(
            ano=novo_ano,
            municipio=self.municipio,
            rcl_exercicio_anterior=self.rcl_exercicio_anterior,
            ano_referencia_rcl=self.ano_referencia_rcl,
            numero_vereadores=self.numero_vereadores,
            base_legal=self.base_legal,
            situacao=Exercicio.Situacao.ABERTO,
        )
        for faixa in self.faixas.all():
            Faixa.objects.create(
                exercicio=novo,
                nome=faixa.nome,
                modalidade=faixa.modalidade,
                percentual_rcl=faixa.percentual_rcl,
                sigla_codigo=faixa.sigla_codigo,
                tipo_transferencia=faixa.tipo_transferencia,
                rotulo_transferencia=faixa.rotulo_transferencia,
                ordem=faixa.ordem,
                ativa=faixa.ativa,
            )
        return novo


class Faixa(models.Model):
    class Modalidade(models.TextChoices):
        INDIVIDUAL = "individual", "Individual"
        COLETIVA = "coletiva", "Bancada/Coletiva"

    exercicio = models.ForeignKey(
        Exercicio, verbose_name="Exercício", on_delete=models.CASCADE, related_name="faixas"
    )
    nome = models.CharField("Nome", max_length=150, help_text='Ex.: "Emendas Individuais 1,55%"')
    modalidade = models.CharField("Modalidade", max_length=12, choices=Modalidade.choices)
    percentual_rcl = models.DecimalField(
        "Percentual da RCL",
        max_digits=6,
        decimal_places=4,
        help_text="Ex.: 1.5500 para 1,55%",
        validators=[MinValueValidator(Decimal("0.0001")), MaxValueValidator(Decimal("100"))],
    )
    sigla_codigo = models.CharField("Sigla do código", max_length=10, help_text="Ex.: EPIMI, EPIMB")
    tipo_transferencia = models.CharField("Tipo de transferência", max_length=100, default="Finalidade Definida")
    rotulo_transferencia = models.CharField(
        "Rótulo do tipo de transferência", max_length=10, default="FD", help_text='Coluna "RP" do PDF.'
    )
    percentual_minimo_outras_funcoes = models.DecimalField(
        "Percentual mínimo para outras funções",
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text=(
            "Ex.: 50.00 quando a legislação exige reservar parte do teto individual para "
            "funções fora da destinação principal. Deixe em branco se não se aplicar a esta faixa."
        ),
    )
    ordem = models.PositiveIntegerField("Ordem de exibição", default=0)
    ativa = models.BooleanField("Ativa", default=True)

    class Meta:
        verbose_name = "Faixa de emenda"
        verbose_name_plural = "Faixas de emenda"
        unique_together = [("exercicio", "sigla_codigo")]
        ordering = ["exercicio", "ordem", "nome"]

    def __str__(self):
        return f"{self.nome} ({self.exercicio.ano})"

    def teto_por_vereador(self):
        rcl = self.exercicio.rcl_exercicio_anterior
        num_vereadores = self.exercicio.numero_vereadores or 1
        bruto = (rcl * self.percentual_rcl / Decimal("100")) / Decimal(num_vereadores)
        # Arredonda a centavos: é um valor orçamentário, não deve carregar dízima que
        # gere "estouros de limite" de meio centavo por ruído de arredondamento.
        return bruto.quantize(Decimal("0.01"))

    def teto_para(self, autor):
        """`autor` é um Vereador (faixa individual) ou uma Bancada (faixa coletiva)."""
        base = self.teto_por_vereador()
        if self.modalidade == self.Modalidade.COLETIVA:
            if isinstance(autor, Bancada):
                return base * autor.num_membros
            return Decimal("0")
        if isinstance(autor, Vereador):
            return base
        return Decimal("0")

    def saldo_de(self, autor):
        """Retorna {'teto', 'usado', 'saldo'} considerando rascunho/enviada/em conferência/publicada."""
        from apps.emendas.models import Emenda

        teto = self.teto_para(autor)
        qs = Emenda.objects.filter(
            faixa=self,
            situacao__in=[
                Emenda.Situacao.RASCUNHO,
                Emenda.Situacao.ENVIADA,
                Emenda.Situacao.EM_CONFERENCIA,
                Emenda.Situacao.PUBLICADA,
            ],
        )
        if self.modalidade == self.Modalidade.INDIVIDUAL:
            qs = qs.filter(autor_vereador=autor)
        else:
            qs = qs.filter(autor_bancada=autor)
        usado = qs.aggregate(total=Sum("valor_previsto"))["total"] or Decimal("0")
        return {"teto": teto, "usado": usado, "saldo": teto - usado}


class UnidadeGestora(models.Model):
    nome = models.CharField("Nome", max_length=200, unique=True)
    exige_documentacao_entidade = models.BooleanField(
        "Exige documentação da entidade de destino",
        default=False,
        help_text="Marcar apenas para 'Entidade Privada Sem Fins Lucrativos'.",
    )
    ordem = models.PositiveIntegerField("Ordem de exibição", default=0)

    class Meta:
        verbose_name = "Unidade gestora"
        verbose_name_plural = "Unidades gestoras"
        ordering = ["ordem", "nome"]

    def __str__(self):
        return self.nome


class OrgaoExecutor(models.Model):
    nome = models.CharField("Nome", max_length=200)
    unidade_gestora = models.ForeignKey(
        UnidadeGestora, verbose_name="Unidade gestora", on_delete=models.PROTECT, related_name="orgaos"
    )
    ativo = models.BooleanField("Ativo", default=True)

    class Meta:
        verbose_name = "Órgão executor"
        verbose_name_plural = "Órgãos executores"
        unique_together = [("nome", "unidade_gestora")]
        ordering = ["nome"]

    def __str__(self):
        return self.nome


class Entidade(models.Model):
    """OSC / entidade privada sem fins lucrativos destinatária de emenda."""

    nome = models.CharField("Nome", max_length=200, unique=True)
    cnpj = models.CharField("CNPJ", max_length=20, blank=True)
    documentacao = models.FileField(
        "Documentação da entidade (PDF)", upload_to="entidades/documentacao/%Y/", blank=True, null=True
    )
    validade_documentacao = models.DateField("Validade da documentação", null=True, blank=True)
    ativa = models.BooleanField("Ativa", default=True)
    observacoes = models.TextField("Observações", blank=True)

    class Meta:
        verbose_name = "Entidade"
        verbose_name_plural = "Entidades"
        ordering = ["nome"]

    def __str__(self):
        return self.nome


class FuncaoGoverno(models.Model):
    codigo = models.CharField("Código", max_length=10, blank=True)
    nome = models.CharField("Nome", max_length=100, unique=True)
    ordem = models.PositiveIntegerField("Ordem no PDF (checkbox)", default=0)

    class Meta:
        verbose_name = "Função de governo"
        verbose_name_plural = "Funções de governo"
        ordering = ["ordem", "nome"]

    def __str__(self):
        return self.nome


class SubfuncaoGoverno(models.Model):
    funcao = models.ForeignKey(
        FuncaoGoverno, verbose_name="Função de governo", on_delete=models.PROTECT, related_name="subfuncoes"
    )
    codigo = models.CharField("Código", max_length=10, blank=True)
    nome = models.CharField("Nome", max_length=150)

    class Meta:
        verbose_name = "Subfunção de governo"
        verbose_name_plural = "Subfunções de governo"
        unique_together = [("funcao", "nome")]
        ordering = ["funcao", "nome"]

    def __str__(self):
        return f"{self.nome} ({self.funcao.nome})"


class ProgramaPPA(models.Model):
    exercicio = models.ForeignKey(
        Exercicio, verbose_name="Exercício", on_delete=models.CASCADE, related_name="programas_ppa"
    )
    codigo = models.CharField("Código", max_length=50)
    nome = models.CharField("Nome do programa", max_length=300)
    objetivos = models.TextField("Objetivos do programa")

    class Meta:
        verbose_name = "Programa do PPA"
        verbose_name_plural = "Programas do PPA"
        unique_together = [("exercicio", "codigo")]
        ordering = ["exercicio", "codigo"]

    def __str__(self):
        return f"{self.codigo} — {self.nome}"
