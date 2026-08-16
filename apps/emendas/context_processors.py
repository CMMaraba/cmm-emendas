from apps.orcamento.models import resolver_exercicio_selecionado


def exercicio_atual(request):
    return {"exercicio_atual": resolver_exercicio_selecionado(request)}
