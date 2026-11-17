"""
Segurança do login (RNF01): bloqueio temporário após tentativas erradas.

Após LOGIN_LIMITE_TENTATIVAS falhas para o mesmo nome de usuário, novas
tentativas ficam bloqueadas por LOGIN_BLOQUEIO_SEGUNDOS, mesmo com a senha
correta. O contador é zerado quando o login dá certo.

A mensagem de bloqueio é igual para qualquer nome digitado, exista a conta ou
não, para não revelar quais usuários estão cadastrados.
"""
from django.conf import settings
from django.contrib.auth import views as auth_views
from django.core.cache import cache


def _limite():
    return getattr(settings, "LOGIN_LIMITE_TENTATIVAS", 5)


def _bloqueio_segundos():
    return getattr(settings, "LOGIN_BLOQUEIO_SEGUNDOS", 15 * 60)


def _chave(usuario):
    return "login-falhas:" + (usuario or "").strip().lower()


def esta_bloqueado(usuario):
    return cache.get(_chave(usuario), 0) >= _limite()


def registrar_falha(usuario):
    """Soma uma falha; o prazo de bloqueio recomeça a cada nova falha."""
    chave = _chave(usuario)
    tentativas = cache.get(chave, 0) + 1
    cache.set(chave, tentativas, _bloqueio_segundos())
    return tentativas


def limpar_falhas(usuario):
    cache.delete(_chave(usuario))


class LoginComBloqueioView(auth_views.LoginView):
    """Tela de login do Django com o bloqueio temporário do RNF01."""

    def post(self, request, *args, **kwargs):
        usuario = request.POST.get("username", "")
        if esta_bloqueado(usuario):
            # Não chega a verificar a senha enquanto o bloqueio estiver ativo.
            form = self.get_form_class()(request=request, initial={"username": usuario})
            contexto = self.get_context_data(form=form, bloqueado=True)
            return self.render_to_response(contexto, status=429)
        return super().post(request, *args, **kwargs)

    def form_invalid(self, form):
        registrar_falha(self.request.POST.get("username", ""))
        return super().form_invalid(form)

    def form_valid(self, form):
        limpar_falhas(self.request.POST.get("username", ""))
        return super().form_valid(form)
