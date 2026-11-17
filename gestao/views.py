"""Camada de apresentação: recebe as ações do usuário e devolve as telas."""
from django.contrib import messages
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from . import services
from .forms import AtividadeForm, EncontroForm, InscricaoForm, ParticipanteForm, ler_marcacoes_da_chamada
from .models import Atividade, Encontro, Inscricao, Participante


def menu(request):
    return render(request, "gestao/menu.html")


def _excluir(request, objeto, destino, mensagem_sucesso):
    """Fluxo comum de exclusão: confirmação (GET) e exclusão protegida (POST)."""
    if request.method == "POST":
        try:
            services.excluir_sem_historico(objeto)
        except services.RegraDeNegocioError as erro:
            messages.error(request, str(erro))
        else:
            messages.success(request, mensagem_sucesso)
        return redirect(destino)
    return render(request, "gestao/confirmar_exclusao.html", {"objeto": objeto, "voltar": destino})


# ---------------------------------------------------------------- Participantes

PARTICIPANTES_POR_PAGINA = 25


def participante_lista(request):
    termo = request.GET.get("q", "")
    paginador = Paginator(services.buscar_participantes(termo), PARTICIPANTES_POR_PAGINA)
    pagina = paginador.get_page(request.GET.get("pagina"))
    contexto = {"participantes": pagina.object_list, "pagina": pagina, "termo": termo}
    return render(request, "gestao/participante_lista.html", contexto)


def participante_detalhe(request, pk):
    participante = get_object_or_404(Participante, pk=pk)
    contexto = {"participante": participante, "historico": services.historico_participante(participante)}
    return render(request, "gestao/participante_detalhe.html", contexto)


def participante_form(request, pk=None):
    participante = get_object_or_404(Participante, pk=pk) if pk else None
    duplicados = []

    if request.method == "POST":
        form = ParticipanteForm(request.POST, instance=participante, mostrar_confirmacao=True)
        if form.is_valid():
            duplicados = services.possiveis_duplicados(
                form.cleaned_data["nome"], form.cleaned_data["data_nascimento"], ignorar_id=pk
            )
            if duplicados.exists() and not form.cleaned_data.get("confirmar_duplicidade"):
                messages.warning(request, "Já existe participante com o mesmo nome e data de nascimento. Confira abaixo.")
            else:
                salvo = form.save()
                messages.success(request, f"Participante “{salvo.nome}” salvo.")
                return redirect("participante_lista")
    else:
        form = ParticipanteForm(instance=participante)

    if not duplicados:
        form.fields.pop("confirmar_duplicidade", None)
    return render(
        request,
        "gestao/participante_form.html",
        {"form": form, "participante": participante, "duplicados": duplicados},
    )


@require_POST
def participante_alternar_ativo(request, pk):
    participante = get_object_or_404(Participante, pk=pk)
    participante.ativo = not participante.ativo
    participante.save(update_fields=["ativo"])
    situacao = "reativado" if participante.ativo else "desativado"
    messages.success(request, f"Participante “{participante.nome}” {situacao}.")
    return redirect("participante_lista")


def participante_excluir(request, pk):
    participante = get_object_or_404(Participante, pk=pk)
    return _excluir(request, participante, reverse("participante_lista"), f"Participante “{participante.nome}” excluído.")


# ------------------------------------------------------------------ Atividades

def atividade_lista(request):
    return render(request, "gestao/atividade_lista.html", {"atividades": Atividade.objects.all()})


def atividade_detalhe(request, pk):
    atividade = get_object_or_404(Atividade, pk=pk)
    contexto = {
        "atividade": atividade,
        "inscricoes": atividade.inscricoes.select_related("participante"),
        "encontros": atividade.encontros.all(),
        "form_inscricao": InscricaoForm(participantes=services.participantes_disponiveis(atividade)),
    }
    return render(request, "gestao/atividade_detalhe.html", contexto)


def atividade_form(request, pk=None):
    atividade = get_object_or_404(Atividade, pk=pk) if pk else None
    form = AtividadeForm(request.POST or None, instance=atividade)
    if request.method == "POST" and form.is_valid():
        salva = form.save()
        messages.success(request, f"Atividade “{salva.nome}” salva.")
        return redirect("atividade_lista")
    return render(request, "gestao/atividade_form.html", {"form": form, "atividade": atividade})


@require_POST
def atividade_alternar_ativa(request, pk):
    atividade = get_object_or_404(Atividade, pk=pk)
    atividade.ativa = not atividade.ativa
    atividade.save(update_fields=["ativa"])
    situacao = "reativada" if atividade.ativa else "desativada"
    messages.success(request, f"Atividade “{atividade.nome}” {situacao}.")
    return redirect("atividade_lista")


def atividade_excluir(request, pk):
    atividade = get_object_or_404(Atividade, pk=pk)
    return _excluir(request, atividade, reverse("atividade_lista"), f"Atividade “{atividade.nome}” excluída.")


# ------------------------------------------------------------------ Inscrições

@require_POST
def inscricao_criar(request, atividade_pk):
    atividade = get_object_or_404(Atividade, pk=atividade_pk)
    form = InscricaoForm(request.POST, participantes=Participante.objects.all())
    if form.is_valid():
        try:
            inscricao = services.inscrever(form.cleaned_data["participante"], atividade)
        except services.RegraDeNegocioError as erro:
            messages.error(request, str(erro))
        else:
            messages.success(request, f"{inscricao.participante.nome} inscrito(a) em {atividade.nome}.")
    else:
        messages.error(request, "Selecione um participante para inscrever.")
    return redirect("atividade_detalhe", pk=atividade.pk)


@require_POST
def inscricao_cancelar(request, pk):
    inscricao = get_object_or_404(Inscricao.objects.select_related("participante", "atividade"), pk=pk)
    try:
        services.cancelar_inscricao(inscricao)
    except services.RegraDeNegocioError as erro:
        messages.error(request, str(erro))
    else:
        messages.success(request, f"Inscrição de {inscricao.participante.nome} cancelada. O histórico foi mantido.")
    return redirect("atividade_detalhe", pk=inscricao.atividade_id)


# ------------------------------------------------------------------- Encontros

def encontro_form(request, atividade_pk=None, pk=None):
    if pk:
        encontro = get_object_or_404(Encontro.objects.select_related("atividade"), pk=pk)
        atividade = encontro.atividade
    else:
        atividade = get_object_or_404(Atividade, pk=atividade_pk)
        encontro = Encontro(atividade=atividade)

    form = EncontroForm(request.POST or None, instance=encontro, atividade=atividade)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Encontro salvo.")
        return redirect("atividade_detalhe", pk=atividade.pk)
    return render(request, "gestao/encontro_form.html", {"form": form, "atividade": atividade, "encontro": encontro})


def encontro_excluir(request, pk):
    encontro = get_object_or_404(Encontro.objects.select_related("atividade"), pk=pk)
    destino = reverse("atividade_detalhe", args=[encontro.atividade_id])
    return _excluir(request, encontro, destino, "Encontro excluído.")


# -------------------------------------------------------- Registro de presença

def presenca_selecionar(request):
    """Tela 2 (parte 1): escolher a atividade e o encontro."""
    atividades = Atividade.objects.filter(ativa=True)
    atividade = None
    encontros = Encontro.objects.none()

    atividade_id = request.GET.get("atividade")
    if atividade_id:
        atividade = get_object_or_404(Atividade, pk=atividade_id)
        encontros = atividade.encontros.filter(status=Encontro.Status.REALIZADO)
    elif "escolher" in request.GET:
        messages.error(request, "Selecione uma atividade para continuar.")

    if atividade and "carregar" in request.GET:
        encontro_id = request.GET.get("encontro")
        if encontro_id:
            encontro = get_object_or_404(Encontro, pk=encontro_id, atividade=atividade)
            return redirect("presenca_registrar", encontro_pk=encontro.pk)
        messages.error(request, "Selecione um encontro para continuar.")

    contexto = {
        "atividades": atividades,
        "atividade": atividade,
        "encontros": encontros,
        "encontros_hoje": services.encontros_de_hoje(),
    }
    return render(request, "gestao/presenca_selecionar.html", contexto)


def presenca_registrar(request, encontro_pk):
    """Tela 2 (parte 2): lista de inscritos e marcação manual da frequência."""
    encontro = get_object_or_404(Encontro.objects.select_related("atividade"), pk=encontro_pk)

    if request.method == "POST":
        try:
            services.registrar_presencas(encontro, ler_marcacoes_da_chamada(request.POST))
        except services.RegraDeNegocioError as erro:
            messages.error(request, str(erro))
        else:
            messages.success(request, "Presenças salvas.")
            return redirect("presenca_resultado", encontro_pk=encontro.pk)

    linhas = services.linhas_da_chamada(encontro)
    return render(request, "gestao/presenca_form.html", {"encontro": encontro, "linhas": linhas})


def presenca_resultado(request, encontro_pk):
    """Tela 3: confirmação e conferência do que foi registrado."""
    encontro = get_object_or_404(Encontro.objects.select_related("atividade"), pk=encontro_pk)
    linhas = services.linhas_da_chamada(encontro)
    return render(request, "gestao/presenca_resultado.html", {"encontro": encontro, "linhas": linhas})
