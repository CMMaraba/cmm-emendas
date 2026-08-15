from decimal import Decimal

from django import forms

from apps.orcamento.models import Entidade, OrgaoExecutor, ProgramaPPA, SubfuncaoGoverno

from .models import CategoriaEconomica, Emenda


class EmendaForm(forms.ModelForm):
    """Formulário do mérito, preenchido pelo gabinete ou pela bancada."""

    class Meta:
        model = Emenda
        fields = [
            "funcao_governo",
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
            "valor_custeio": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
            "valor_investimento": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["orgao_executor"].queryset = OrgaoExecutor.objects.filter(ativo=True)
        self.fields["orgao_executor"].required = False
        self.fields["entidade"].queryset = Entidade.objects.filter(ativa=True)
        self.fields["entidade"].required = False
        for nome in ("funcao_governo", "unidade_gestora"):
            self.fields[nome].empty_label = "Selecione…"

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

        unidade_gestora = cleaned.get("unidade_gestora")
        entidade = cleaned.get("entidade")
        orgao_executor = cleaned.get("orgao_executor")
        if unidade_gestora and unidade_gestora.exige_documentacao_entidade:
            if not entidade:
                self.add_error("entidade", "Selecione a entidade de destino para esta unidade gestora.")
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
    """Formulário do setor técnico: classificação orçamentária."""

    class Meta:
        model = Emenda
        fields = ["vinculacao_orcamentaria", "subfuncao_governo", "programa_ppa", "data_reserva"]
        widgets = {
            "data_reserva": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        emenda = self.instance
        if emenda and emenda.funcao_governo_id:
            self.fields["subfuncao_governo"].queryset = SubfuncaoGoverno.objects.filter(
                funcao=emenda.funcao_governo
            )
        if emenda and emenda.exercicio_id:
            self.fields["programa_ppa"].queryset = ProgramaPPA.objects.filter(exercicio=emenda.exercicio)
        self.fields["subfuncao_governo"].required = False
        self.fields["programa_ppa"].required = False


class DevolucaoForm(forms.Form):
    motivo = forms.CharField(
        label="Motivo da devolução",
        widget=forms.Textarea(attrs={"rows": 3}),
        required=True,
    )
