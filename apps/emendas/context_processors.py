from apps.orcamento.models import Exercicio


def exercicio_atual(request):
    return {"exercicio_atual": Exercicio.atual()}
