from decimal import Decimal

from django import forms

from apps.orcamento.models import Entidade, OrgaoExecutor, ProgramaPPA, UnidadeGestora, resolver_classificacao_funcional

from .models import CategoriaEconomica, Emenda


class EntidadeSelect(forms.Select):
    """Dropdown de entidades com um data-attribute por opção indicando se a entidade já
    tem documentação cadastrada (Entidade.documentacao) — usado pelo JS do formulário
    para desabilitar o upload de PDF por emenda quando já existe documentação no
    cadastro da entidade, evitando reenvio duplicado."""

    def __init__(self, *args, **kwargs):
        self.ids_com_documentacao = set()
        super().__init__(*args, **kwargs)

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        valor = getattr(value, "value", value)
        if valor and int(valor) in self.ids_com_documentacao:
            option["attrs"]["data-tem-documentacao"] = "1"
        return option


class UnidadeGestoraSelect(forms.Select):
    """Marca cada opção com data-exige-entidade — usado pelo JS do formulário para só
    habilitar o dropdown de Entidade (OSC) quando a Unidade Gestora selecionada for a
    que exige documentação de entidade. Sem isso, o vereador podia escolher uma OSC que
    o clean() do formulário descartava silenciosamente (a entidade só é aceita quando a
    unidade gestora exige documentação — ver EmendaForm.clean())."""

    def __init__(self, *args, **kwargs):
        self.ids_exige_entidade = set()
        super().__init__(*args, **kwargs)

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        valor = getattr(value, "value", value)
        if valor and int(valor) in self.ids_exige_entidade:
            option["attrs"]["data-exige-entidade"] = "1"
        return option


class EmendaForm(forms.ModelForm):
    """Formulário do mérito, preenchido pelo gabinete ou pela bancada.

    Função e Subfunção de Governo NÃO entram aqui: são calculadas automaticamente pelo
    setor técnico a partir da Vinculação Orçamentária (rubrica), na conferência
    (ver EmendaConferenciaForm e apps.orcamento.models.resolver_classificacao_funcional).
    """

    unidade_gestora = forms.ModelChoiceField(
        label="Unidade Gestora Vinculada",
        queryset=UnidadeGestora.objects.all(),
        widget=UnidadeGestoraSelect(),
    )
    entidade = forms.ModelChoiceField(
        label="Entidade (OSC)",
        queryset=Entidade.objects.filter(ativa=True).order_by("nome"),
        required=False,
        empty_label="Selecione…",
        widget=EntidadeSelect(),
        help_text="Só pode ser escolhida quando a Unidade Gestora Vinculada for \"Entidade Privada Sem Fins Lucrativos\".",
    )

    class Meta:
        model = Emenda
        fields = [
            "proponente",
            "unidade_gestora",
            "orgao_executor",
            "entidade",
            "acao_orcamentaria",
            "objeto_despesa",
            "categoria_economica",
            "valor_custeio",
            "valor_investimento",
            "documentacao_entidade",
        ]
        widgets = {
            "acao_orcamentaria": forms.Textarea(attrs={"rows": 3}),
            "objeto_despesa": forms.Textarea(attrs={"rows": 3}),
            "valor_custeio": forms.TextInput(attrs={"inputmode": "decimal", "data-mask": "moeda"}),
            "valor_investimento": forms.TextInput(attrs={"inputmode": "decimal", "data-mask": "moeda"}),
        }
        # Faz o Django aceitar/exibir "10.000,00" (formato brasileiro) nesses dois
        # campos em vez de "10000.00" — o JS de máscara em emenda_form.html cuida da
        # formatação visual enquanto o vereador digita.
        localized_fields = ["valor_custeio", "valor_investimento"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["orgao_executor"].queryset = OrgaoExecutor.objects.filter(ativo=True)
        self.fields["orgao_executor"].required = False
        self.fields["entidade"].widget.ids_com_documentacao = set(
            Entidade.objects.filter(ativa=True)
            .exclude(documentacao="")
            .exclude(documentacao__isnull=True)
            .values_list("id", flat=True)
        )
        self.fields["unidade_gestora"].widget.ids_exige_entidade = set(
            UnidadeGestora.objects.filter(exige_documentacao_entidade=True).values_list("id", flat=True)
        )

        bancada = getattr(self.instance, "autor_bancada", None)
        if bancada:
            self.fields["proponente"].queryset = bancada.membros.all()
            self.fields["proponente"].required = False
            self.fields["proponente"].help_text = "Qual vereador da bancada propôs esta emenda (opcional)."
        else:
            del self.fields["proponente"]

        self.fields["unidade_gestora"].empty_label = "Selecione…"

    def clean(self):
        cleaned = super().clean()
        categoria = cleaned.get("categoria_economica")
        custeio = cleaned.get("valor_custeio") or Decimal("0")
        investimento = cleaned.get("valor_investimento") or Decimal("0")

        if categoria == CategoriaEconomica.INVESTIMENTO:
            if investimento <= 0:
                self.add_error("valor_investimento", "Informe um valor de investimento maior que zero.")
            cleaned["valor_custeio"] = Decimal("0")
        elif categoria == CategoriaEconomica.CUSTEIO:
            if custeio <= 0:
                self.add_error("valor_custeio", "Informe um valor de custeio maior que zero.")
            cleaned["valor_investimento"] = Decimal("0")

        entidade = cleaned.get("entidade")
        unidade_gestora = cleaned.get("unidade_gestora")
        orgao_executor = cleaned.get("orgao_executor")
        if unidade_gestora and unidade_gestora.exige_documentacao_entidade:
            if not entidade:
                self.add_error("entidade", "Informe a entidade de destino para esta unidade gestora.")
            cleaned["orgao_executor"] = None
        elif unidade_gestora:
            if not orgao_executor:
                self.add_error("orgao_executor", "Selecione o órgão executor.")
            cleaned["entidade"] = None
        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.valor_custeio = self.cleaned_data.get("valor_custeio") or Decimal("0")
        instance.valor_investimento = self.cleaned_data.get("valor_investimento") or Decimal("0")
        instance.orgao_executor = self.cleaned_data.get("orgao_executor")
        instance.entidade = self.cleaned_data.get("entidade")
        if commit:
            instance.save()
        return instance


class EmendaConferenciaForm(forms.ModelForm):
    """Formulário do setor técnico: classificação orçamentária.

    Função e Subfunção de Governo não são campos do formulário — são calculadas
    automaticamente a partir da Vinculação Orçamentária (rubrica) em clean()/save(), via
    apps.orcamento.models.resolver_classificacao_funcional.
    """

    class Meta:
        model = Emenda
        fields = ["tipo_transferencia", "vinculacao_orcamentaria", "programa_ppa", "data_reserva"]
        widgets = {
            "data_reserva": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        emenda = self.instance
        if emenda and emenda.exercicio_id:
            self.fields["programa_ppa"].queryset = ProgramaPPA.objects.filter(exercicio=emenda.exercicio)
        self.fields["programa_ppa"].required = False
        self.fields["tipo_transferencia"].required = True
        self.fields["tipo_transferencia"].help_text = (
            "Define como o número/código da emenda será gerado ao publicar (ex.: "
            "2026.EPIMI.FD.001 para Finalidade Definida, 2026.EPIMI.TE.001 para "
            "Transferência Especial)."
        )

    def clean(self):
        cleaned = super().clean()
        vinculacao = cleaned.get("vinculacao_orcamentaria")
        if vinculacao:
            funcao, subfuncao = resolver_classificacao_funcional(vinculacao)
            if not funcao or not subfuncao:
                self.add_error(
                    "vinculacao_orcamentaria",
                    "Não foi possível identificar a função/subfunção de governo a partir "
                    "deste código. Confira o formato (ex.: 13 01. 08 244 5003 8.500) — o 3º "
                    "grupo de números é o código da função e o 4º o da subfunção, conforme "
                    "a Portaria MOG nº 42/1999.",
                )
            else:
                cleaned["funcao_governo"] = funcao
                cleaned["subfuncao_governo"] = subfuncao
        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.funcao_governo = self.cleaned_data.get("funcao_governo")
        instance.subfuncao_governo = self.cleaned_data.get("subfuncao_governo")
        if commit:
            instance.save()
        return instance


class DevolucaoForm(forms.Form):
    motivo = forms.CharField(
        label="Motivo da devolução",
        widget=forms.Textarea(attrs={"rows": 3}),
        required=True,
    )
