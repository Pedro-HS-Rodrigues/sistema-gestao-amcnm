"""
Camada de regras de negócio.

As telas (views) chamam estas funções; elas validam as condições de cada
operação e usam o ORM (models) para consultar ou gravar os dados.
"""
from django.db import transaction
from django.db.models import Prefetch, ProtectedError

from .models import Atividade, Encontro, Inscricao, Participante, Presenca


class RegraDeNegocioError(Exception):
    """Operação recusada por uma regra do sistema; a mensagem é mostrada ao usuário."""


def possiveis_duplicados(nome, data_nascimento, ignorar_id=None):
    """RF02: participantes com mesmo nome e nascimento, para conferência (sem bloqueio)."""
    duplicados = Participante.objects.filter(nome__iexact=nome.strip(), data_nascimento=data_nascimento)
    if ignorar_id:
        duplicados = duplicados.exclude(pk=ignorar_id)
    return duplicados


def buscar_participantes(termo):
    """RF03: pesquisa por parte do nome."""
    participantes = Participante.objects.all()
    if termo:
        participantes = participantes.filter(nome__icontains=termo.strip())
    return participantes


# ------------------------------------------------------------------ Inscrições

@transaction.atomic
def inscrever(participante, atividade):
    """
    RF05: inscreve o participante na atividade.

    Participante e atividade precisam estar ativos e a combinação é única:
    uma inscrição ativa repetida é recusada; uma cancelada é reativada,
    sem criar outro registro.
    """
    if not participante.ativo:
        raise RegraDeNegocioError("O participante está inativo e não pode receber novas inscrições.")
    if not atividade.ativa:
        raise RegraDeNegocioError("A atividade está inativa e não aceita novas inscrições.")

    existente = Inscricao.objects.select_for_update().filter(participante=participante, atividade=atividade).first()
    if existente:
        if existente.ativa:
            raise RegraDeNegocioError(f"{participante.nome} já está inscrito(a) em {atividade.nome}.")
        existente.status = Inscricao.Status.ATIVA
        existente.save(update_fields=["status"])
        return existente
    return Inscricao.objects.create(participante=participante, atividade=atividade)


def cancelar_inscricao(inscricao):
    """O cancelamento mantém o registro e as presenças anteriores."""
    if not inscricao.ativa:
        raise RegraDeNegocioError("Esta inscrição já está cancelada.")
    inscricao.status = Inscricao.Status.CANCELADA
    inscricao.save(update_fields=["status"])
    return inscricao


def participantes_disponiveis(atividade):
    """Participantes ativos que ainda não têm inscrição ativa na atividade."""
    inscritos = atividade.inscricoes.filter(status=Inscricao.Status.ATIVA).values("participante_id")
    return Participante.objects.filter(ativo=True).exclude(pk__in=inscritos)


# ------------------------------------------------------------------- Presenças

# Opções da chamada e o valor gravado em Presenca.compareceu
# (None = não informado: nenhum registro é mantido).
OPCOES_FREQUENCIA = {"presente": True, "faltou": False, "nao_informado": None}


def inscritos_do_encontro(encontro):
    """RF07: só os participantes com inscrição ativa na atividade do encontro."""
    return (
        Inscricao.objects.filter(atividade_id=encontro.atividade_id, status=Inscricao.Status.ATIVA)
        .select_related("participante")
        .order_by("participante__nome")
    )


def frequencias_do_encontro(encontro):
    """Mapa {id da inscrição: compareceu} com o que já foi registrado no encontro."""
    return dict(encontro.presencas.values_list("inscricao_id", "compareceu"))


def linhas_da_chamada(encontro):
    """Inscritos ativos do encontro com a frequência registrada (None = não informado)."""
    frequencias = frequencias_do_encontro(encontro)
    return [(inscricao, frequencias.get(inscricao.pk)) for inscricao in inscritos_do_encontro(encontro)]


@transaction.atomic
def registrar_presencas(encontro, marcacoes):
    """
    RF08 e RF09: grava ou corrige a frequência de cada inscrito.

    `marcacoes` é um dicionário {id da inscrição: "presente" | "faltou" | "nao_informado"}.
    Regras: o encontro precisa estar realizado; a inscrição precisa estar ativa e
    pertencer à mesma atividade; há no máximo um registro por inscrição e encontro
    (uma correção atualiza o registro existente em vez de criar outro).
    """
    if not encontro.realizado:
        raise RegraDeNegocioError("Só é possível registrar presença em encontros com situação “Realizado”.")

    inscricoes_validas = {i.pk: i for i in inscritos_do_encontro(encontro)}
    for inscricao_id, opcao in marcacoes.items():
        if inscricao_id not in inscricoes_validas:
            raise RegraDeNegocioError("Há participante sem inscrição ativa nesta atividade. Recarregue a lista.")
        if opcao not in OPCOES_FREQUENCIA:
            raise RegraDeNegocioError("Escolha Presente, Faltou ou Não informado para cada participante.")

    for inscricao_id, opcao in marcacoes.items():
        compareceu = OPCOES_FREQUENCIA[opcao]
        inscricao = inscricoes_validas[inscricao_id]
        if compareceu is None:
            Presenca.objects.filter(inscricao=inscricao, encontro=encontro).delete()
        else:
            Presenca.objects.update_or_create(
                inscricao=inscricao, encontro=encontro, defaults={"compareceu": compareceu}
            )


# ------------------------------------------------------------------- Histórico

def historico_participante(participante):
    """
    RF10: inscrições do participante em todas as atividades, cada uma com as
    frequências registradas (encontros mais recentes primeiro).
    """
    presencas = Presenca.objects.select_related("encontro").order_by("-encontro__inicio")
    inscricoes = participante.inscricoes.select_related("atividade").prefetch_related(
        Prefetch("presencas", queryset=presencas)
    )
    historico = []
    for inscricao in inscricoes.order_by("atividade__nome"):
        registros = list(inscricao.presencas.all())
        historico.append(
            {
                "inscricao": inscricao,
                "presencas": registros,
                "total_presente": sum(1 for p in registros if p.compareceu),
                "total_registrado": len(registros),
            }
        )
    return historico


# ------------------------------------------------------------------- Exclusões

MENSAGENS_COM_HISTORICO = {
    Participante: "Este participante tem histórico e não pode ser excluído. Desative o cadastro.",
    Atividade: "Esta atividade tem histórico e não pode ser excluída. Desative a atividade.",
    Encontro: "Este encontro tem presenças registradas e não pode ser excluído.",
}


def excluir_sem_historico(objeto):
    """
    Exclui o registro somente se nada depender dele.

    As chaves estrangeiras usam PROTECT, então o banco recusa a exclusão de
    registros com histórico; aqui essa recusa vira uma mensagem para o usuário.
    """
    try:
        with transaction.atomic():
            objeto.delete()
    except ProtectedError:
        mensagem = MENSAGENS_COM_HISTORICO.get(type(objeto), "Este registro tem histórico e não pode ser excluído.")
        raise RegraDeNegocioError(mensagem) from None
