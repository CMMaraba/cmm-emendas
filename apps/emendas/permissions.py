from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied


def perfil_obrigatorio(view_func):
    """Garante que o usuário logado tem Perfil associado antes de acessar o painel."""

    @wraps(view_func)
    @login_required
    def _wrapped(request, *args, **kwargs):
        if request.user.is_superuser:
            return view_func(request, *args, **kwargs)
        if not hasattr(request.user, "perfil"):
            raise PermissionDenied("Este usuário não possui perfil de acesso configurado.")
        return view_func(request, *args, **kwargs)

    return _wrapped


def papel_obrigatorio(*papeis):
    """Restringe a view aos papéis informados (superuser sempre passa)."""

    def decorador(view_func):
        @wraps(view_func)
        @perfil_obrigatorio
        def _wrapped(request, *args, **kwargs):
            if request.user.is_superuser:
                return view_func(request, *args, **kwargs)
            if request.user.perfil.papel not in papeis:
                raise PermissionDenied("Seu papel de acesso não permite esta ação.")
            return view_func(request, *args, **kwargs)

        return _wrapped

    return decorador


def tecnico_obrigatorio(view_func):
    from apps.parlamento.models import Perfil

    return papel_obrigatorio(Perfil.Papel.TECNICO, Perfil.Papel.CONFIGURADOR, Perfil.Papel.ADMIN)(view_func)


def configurador_obrigatorio(view_func):
    from apps.parlamento.models import Perfil

    return papel_obrigatorio(Perfil.Papel.CONFIGURADOR, Perfil.Papel.ADMIN)(view_func)
