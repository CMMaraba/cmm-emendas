from decimal import Decimal

from django import forms
from django.utils.html import format_html, format_html_join

from apps.orcamento.models import Entidade, OrgaoExecutor, ProgramaPPA, resolver_classificacao_funcional

from .models import CategoriaEconomica, Emenda


class EntidadeTextWidget(forms.TextInput):
    """Campo digitável com sugestões (datalist) das entidades já cadastradas, em vez de
    um dropdown com as 148+ OSCs — a entidade continua vinculada por FK, só a forma de
    escolher deixa de ser uma lista fixa."""

    def __init__(self, attrs=None):
        base_attrs = {"list": "entidades-lista", "autocomplete": "off", "placeholder": "Digite o nome da entidade…"}
        if attrs:
            base_attrs.update(attrs)
        super().__init__(attrs=base_attrs)

    def render(self, name, value, attrs=None, renderer=None):
        html = super().render(name, value, attrs, renderer)
        opcoes = format_html_join(
            "", '<option value="{}">',
            ((e.nome,) for e in Entidade.objects.filter(ativa=True).order_by("nome")),
        )
        return format_html('{}<datalist id="entidades-lista">{}</datalist>', html, opcoes)


class EmendaForm(forms.ModelForm):
    """Formulário do mérito, preenchido pelo gabinete ou pela bancada.

    Função e Subfunção de Governo NÃO entram aqui: são calculadas automaticamente pelo
    setor técnico a partir da Vinculação Orçamentária (rubrica), na conferência
    (ver EmendaConferenciaForm e apps.orcamento.models.resolver_classificacao_funcional).
    """

    entidade_nome = forms.CharField(
        label="Entidade (OSC)",
        required=False,
        widget=EntidadeTextWidget(),
        help_text="Preencha quando o destino for uma entidade privada sem fins lucrativos (OSC). Comece a digitar para ver as já cadastradas.",
    )

    class Meta:
        model = Emenda
        fields = [
            "proponente",
            "unidade_gestora",
            "orgao_executor",
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
        if self.instance.pk and self.instance.entidade_id:
            self.fields["entidade_nome"].initial = self.instance.entidade.nome

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

        nome_digitado = (cleaned.get("entidade_nome") or "").strip()
        entidade = None
        if nome_digitado:
            entidade = Entidade.objects.filter(nome__iexact=nome_digitado, ativa=True).first()
            if not entidade:
                self.add_error(
                    "entidade_nome",
                    "Entidade não encontrada no cadastro ativo. Confira o nome exato ou "
                    "peça ao setor técnico para cadastrá-la antes de enviar.",
                )
        cleaned["entidade"] = entidade

        unidade_gestora = cleaned.get("unidade_gestora")
        orgao_executor = cleaned.get("orgao_executor")
        if unidade_gestora and unidade_gestora.exige_documentacao_entidade:
            if not entidade:
                self.add_error("entidade_nome", "Informe a entidade de destino para esta unidade gestora.")
            cleaned["orgao_executor"] = None
        elif unidade_gestora:
            if not orgao_executor:
                self.add_error("orgao_executor", "Selecione o órgão executor.")
            cleaned["entidade"] = None
        return cleaned

    def _post_clean(self):
        # "entidade" não é um campo do form (Meta.fields) — precisa estar na instance
        # antes do Emenda.clean() (chamado por instance.full_clean() dentro do
        # super()._post_clean()), senão a validação de "unidade gestora exige entidade"
        # roda achando que nada foi preenchido.
        self.instance.entidade = self.cleaned_data.get("entidade")
        super()._post_clean()

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
