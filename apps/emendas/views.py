from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from apps.orcamento.models import Exercicio, Faixa, resolver_classificacao_funcional
from apps.parlamento.models import Bancada, Perfil, Vereador

from .forms import DevolucaoForm, EmendaConferenciaForm, EmendaForm
from .models import Emenda
from .permissions import perfil_obrigatorio, tecnico_obrigatorio


def _autor_do_usuario(perfil, exercicio):
    if not exercicio:
        return None
    if perfil.is_gabinete:
        return perfil.vereador
    if perfil.is_bancada:
        return perfil.bancada_do_exercicio(exercicio)
    return None


def _faixas_do_usuario(perfil, exercicio):
    if not exercicio:
        return Faixa.objects.none()
    if perfil.is_gabinete:
        return exercicio.faixas.filter(modalidade=Faixa.Modalidade.INDIVIDUAL, ativa=True)
    if perfil.is_bancada:
        return exercicio.faixas.filter(modalidade=Faixa.Modalidade.COLETIVA, ativa=True)
    return Faixa.objects.none()


@perfil_obrigatorio
def painel_home(request):
    exercicio = Exercicio.atual()
    cards = []
    emendas = Emenda.objects.none()

    if request.user.is_superuser and not hasattr(request.user, "perfil"):
        if exercicio:
            emendas = Emenda.objects.filter(exercicio=exercicio)
        return render(request, "emendas/painel_home.html", {"exercicio": exercicio, "cards": cards, "emendas": emendas})

    perfil = request.user.perfil
    autor = _autor_do_usuario(perfil, exercicio)

    if autor:
        faixas = _faixas_do_usuario(perfil, exercicio)
        for faixa in faixas:
            saldo = faixa.saldo_de(autor)
            saldo["saldo_absoluto"] = abs(saldo["saldo"])
            cards.append({"faixa": faixa, **saldo})
        if isinstance(autor, Vereador):
            emendas = Emenda.objects.filter(autor_vereador=autor, exercicio=exercicio)
        elif isinstance(autor, Bancada):
            emendas = Emenda.objects.filter(autor_bancada=autor, exercicio=exercicio)

    context = {
        "exercicio": exercicio,
        "cards": cards,
        "emendas": emendas.select_related("faixa").order_by("-atualizado_em"),
        "perfil": perfil,
        "sem_bancada_no_exercicio": perfil.is_bancada and exercicio and not autor,
    }
    return render(request, "emendas/painel_home.html", context)


@perfil_obrigatorio
def emenda_form(request, pk=None, faixa_id=None):
    exercicio = Exercicio.atual()
    if not exercicio:
        messages.error(request, "Não há exercício orçamentário aberto no momento.")
        return redirect("emendas:painel_home")

    perfil = getattr(request.user, "perfil", None)
    if perfil is None and not request.user.is_superuser:
        raise PermissionDenied

    if pk:
        emenda = get_object_or_404(Emenda, pk=pk)
        autor = _autor_do_usuario(perfil, emenda.exercicio) if perfil else None
        is_owner = _emenda_pertence_ao_autor(emenda, autor)
        if not (request.user.is_superuser or is_owner):
            raise PermissionDenied
        if not emenda.pode_editar():
            messages.warning(request, "Esta emenda não pode mais ser editada no estado atual.")
            return redirect("emendas:painel_home")
    else:
        faixa = get_object_or_404(Faixa, pk=faixa_id, exercicio=exercicio, ativa=True)
        autor = _autor_do_usuario(perfil, exercicio) if perfil else None
        modalidade_ok = (perfil.is_gabinete and faixa.modalidade == Faixa.Modalidade.INDIVIDUAL) or (
            perfil.is_bancada and faixa.modalidade == Faixa.Modalidade.COLETIVA
        )
        if not autor or (perfil and not modalidade_ok):
            raise PermissionDenied("Sua conta não pode cadastrar emendas nesta faixa.")
        emenda = Emenda(exercicio=exercicio, faixa=faixa, criada_por=request.user, situacao=Emenda.Situacao.RASCUNHO)
        if isinstance(autor, Vereador):
            emenda.autor_vereador = autor
        else:
            emenda.autor_bancada = autor

    form = EmendaForm(request.POST or None, request.FILES or None, instance=emenda)

    saldo = emenda.faixa.saldo_de(autor) if autor else {"teto": 0, "usado": 0, "saldo": 0}
    usado_sem_esta = saldo["usado"] - (emenda.valor_previsto if emenda.pk else 0)

    if request.method == "POST":
        if form.is_valid():
            try:
                form.instance.full_clean(exclude=["numero", "codigo", "municipio", "partido", "modalidade", "tipo_transferencia"])
            except ValidationError as exc:
                for campo, erros in exc.message_dict.items():
                    for erro in erros:
                        form.add_error(campo if campo in form.fields else None, erro)
        if form.is_valid():
            form.save()
            messages.success(request, "Rascunho salvo com sucesso.")
            return redirect("emendas:painel_home")

    context = {
        "form": form,
        "emenda": emenda,
        "faixa": emenda.faixa,
        "teto": float(saldo["teto"]),
        "usado_sem_esta": float(usado_sem_esta),
    }
    return render(request, "emendas/emenda_form.html", context)


def _emenda_pertence_ao_autor(emenda, autor):
    if autor is None:
        return False
    if isinstance(autor, Vereador):
        return emenda.autor_vereador_id == autor.id
    if isinstance(autor, Bancada):
        return emenda.autor_bancada_id == autor.id
    return False


@perfil_obrigatorio
def emenda_enviar(request, pk):
    if request.method != "POST":
        return redirect("emendas:painel_home")
    emenda = get_object_or_404(Emenda, pk=pk)
    perfil = getattr(request.user, "perfil", None)
    autor = _autor_do_usuario(perfil, emenda.exercicio) if perfil else None
    if not (request.user.is_superuser or _emenda_pertence_ao_autor(emenda, autor)):
        raise PermissionDenied
    try:
        emenda.enviar()
        messages.success(request, f"Emenda {emenda.codigo} enviada para conferência do setor técnico.")
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    return redirect("emendas:painel_home")


@perfil_obrigatorio
def emenda_excluir(request, pk):
    if request.method != "POST":
        return redirect("emendas:painel_home")
    emenda = get_object_or_404(Emenda, pk=pk)
    perfil = getattr(request.user, "perfil", None)
    autor = _autor_do_usuario(perfil, emenda.exercicio) if perfil else None
    if not (request.user.is_superuser or _emenda_pertence_ao_autor(emenda, autor)):
        raise PermissionDenied
    if not emenda.pode_editar():
        messages.error(request, "Esta emenda não pode mais ser excluída no estado atual.")
        return redirect("emendas:painel_home")
    codigo = emenda.codigo or "(rascunho)"
    emenda.delete()
    messages.success(request, f"Emenda {codigo} excluída.")
    return redirect("emendas:painel_home")


@tecnico_obrigatorio
def conferencia_lista(request):
    base = Emenda.objects.select_related("faixa", "autor_vereador", "autor_bancada", "autor_bancada__partido")
    emendas = base.filter(
        situacao__in=[Emenda.Situacao.ENVIADA, Emenda.Situacao.EM_CONFERENCIA]
    ).order_by("enviada_em")
    emendas_publicadas = base.filter(situacao=Emenda.Situacao.PUBLICADA).order_by("-publicada_em")
    return render(
        request,
        "emendas/conferencia_lista.html",
        {"emendas": emendas, "emendas_publicadas": emendas_publicadas},
    )


@tecnico_obrigatorio
def validar_vinculacao(request):
    """Endpoint AJAX: confere ao vivo se a Vinculação Orçamentária digitada resolve
    para uma Função/Subfunção de Governo válida, sem precisar salvar o formulário."""
    codigo = request.GET.get("codigo", "")
    funcao, subfuncao = resolver_classificacao_funcional(codigo)
    if funcao and subfuncao:
        return JsonResponse({
            "encontrado": True,
            "funcao": funcao.nome,
            "subfuncao": subfuncao.nome,
        })
    return JsonResponse({"encontrado": False})


@tecnico_obrigatorio
def conferencia_detalhe(request, pk):
    emenda = get_object_or_404(Emenda, pk=pk)
    form = EmendaConferenciaForm(request.POST or None, instance=emenda)
    devolucao_form = DevolucaoForm(request.POST or None)

    if request.method == "POST":
        acao = request.POST.get("acao")
        if acao == "iniciar":
            try:
                emenda.iniciar_conferencia(request.user)
                messages.success(request, "Conferência iniciada.")
            except ValidationError as exc:
                messages.error(request, " ".join(exc.messages))
            return redirect("emendas:conferencia_detalhe", pk=pk)

        if acao == "publicar":
            if form.is_valid():
                form.save()
                emenda.refresh_from_db()
                try:
                    emenda.publicar(request.user)
                    messages.success(request, f"Emenda {emenda.codigo} publicada.")
                    return redirect("emendas:conferencia_lista")
                except ValidationError as exc:
                    messages.error(request, " ".join(exc.messages))
            return redirect("emendas:conferencia_detalhe", pk=pk)

        if acao == "devolver":
            if devolucao_form.is_valid():
                try:
                    emenda.devolver(request.user, devolucao_form.cleaned_data["motivo"])
                    messages.success(request, f"Emenda {emenda.codigo} devolvida ao gabinete.")
                    return redirect("emendas:conferencia_lista")
                except ValidationError as exc:
                    messages.error(request, " ".join(exc.messages))
            return redirect("emendas:conferencia_detalhe", pk=pk)

    return render(
        request,
        "emendas/conferencia_detalhe.html",
        {"emenda": emenda, "form": form, "devolucao_form": devolucao_form},
    )


@login_required
def cadastros_home(request):
    if not (request.user.is_superuser or (hasattr(request.user, "perfil") and request.user.perfil.is_tecnico)):
        raise PermissionDenied
    return render(request, "emendas/cadastros_home.html", {})


@login_required
def configuracao_home(request):
    if not (request.user.is_superuser or (hasattr(request.user, "perfil") and request.user.perfil.is_configurador)):
        raise PermissionDenied
    exercicio = Exercicio.atual()
    faixas = []
    if exercicio:
        for faixa in exercicio.faixas.all():
            faixas.append({"faixa": faixa, "teto_por_vereador": faixa.teto_por_vereador()})
    return render(request, "emendas/configuracao_home.html", {"exercicio": exercicio, "faixas": faixas})
