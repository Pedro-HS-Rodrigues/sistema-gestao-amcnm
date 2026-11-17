from django import forms

from .models import Atividade, Encontro, Participante


class ParticipanteForm(forms.ModelForm):
    confirmar_duplicidade = forms.BooleanField(
        label="Confirmo que é outra pessoa e quero salvar mesmo assim",
        required=False,
    )

    class Meta:
        model = Participante
        fields = ["nome", "data_nascimento", "telefone_contato"]
        widgets = {
            "data_nascimento": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "telefone_contato": forms.TextInput(attrs={"type": "tel", "autocomplete": "off"}),
        }
        help_texts = {"telefone_contato": "Opcional."}

    def __init__(self, *args, mostrar_confirmacao=False, **kwargs):
        super().__init__(*args, **kwargs)
        if not mostrar_confirmacao:
            del self.fields["confirmar_duplicidade"]

    def clean_nome(self):
        nome = self.cleaned_data["nome"].strip()
        if not nome:
            raise forms.ValidationError("Informe o nome do participante.")
        return nome


class InscricaoForm(forms.Form):
    participante = forms.ModelChoiceField(
        label="Participante",
        queryset=Participante.objects.none(),
        empty_label="Selecione um participante",
        error_messages={"required": "Selecione um participante para inscrever."},
    )

    def __init__(self, *args, participantes=None, **kwargs):
        super().__init__(*args, **kwargs)
        if participantes is not None:
            self.fields["participante"].queryset = participantes


class AtividadeForm(forms.ModelForm):
    class Meta:
        model = Atividade
        fields = ["nome", "descricao", "ativa"]
        help_texts = {
            "descricao": "Opcional. Ex.: dias, horário e público da atividade.",
            "ativa": "Atividades inativas não recebem novas inscrições.",
        }


class EncontroForm(forms.ModelForm):
    class Meta:
        model = Encontro
        fields = ["inicio", "status"]
        widgets = {
            "inicio": forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
        }
        help_texts = {"status": "Só é possível registrar presença em encontros realizados."}

    def __init__(self, *args, atividade, **kwargs):
        super().__init__(*args, **kwargs)
        self.atividade = atividade

    def clean_inicio(self):
        inicio = self.cleaned_data["inicio"]
        repetidos = Encontro.objects.filter(atividade=self.atividade, inicio=inicio).exclude(pk=self.instance.pk)
        if repetidos.exists():
            raise forms.ValidationError("Esta atividade já tem um encontro com a mesma data e horário.")
        return inicio


PREFIXO_CHAMADA = "presenca_"


def ler_marcacoes_da_chamada(dados):
    """
    Converte os campos "presenca_<id da inscrição>" da tela de chamada em {id: opção}.

    Campos com sufixo que não é número são ignorados. As opções e os vínculos
    (inscrição ativa, mesma atividade) são validados em services.registrar_presencas.
    """
    marcacoes = {}
    for chave, valor in dados.items():
        if not chave.startswith(PREFIXO_CHAMADA):
            continue
        sufixo = chave.removeprefix(PREFIXO_CHAMADA)
        if sufixo.isdigit():
            marcacoes[int(sufixo)] = valor
    return marcacoes
