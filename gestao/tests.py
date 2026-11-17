"""
Testes das regras de negócio e do controle de acesso do MVP.

Rodar com:  python manage.py test
"""
from datetime import date, datetime, timedelta

from django.contrib.auth.models import User
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from . import services
from .forms import EncontroForm, ler_marcacoes_da_chamada
from .models import Atividade, Encontro, Inscricao, Participante, Presenca

SENHA = "senha-de-teste-bem-longa"


def momento(dia, hora=14):
    return datetime(2026, 11, dia, hora, 0, tzinfo=timezone.get_current_timezone())


class BaseTestCase(TestCase):
    def setUp(self):
        self.usuario = User.objects.create_user("responsavel", password=SENHA)
        self.client.login(username="responsavel", password=SENHA)
        self.atividade = Atividade.objects.create(nome="Oficina de leitura")
        self.ana = Participante.objects.create(nome="Pessoa Exemplo A", data_nascimento=date(2010, 3, 1))
        self.bia = Participante.objects.create(nome="Pessoa Exemplo B", data_nascimento=date(2011, 5, 2))


class AcessoTests(TestCase):
    """RF01 e RNF01/RNF02."""

    def setUp(self):
        cache.clear()
        self.usuario = User.objects.create_user("responsavel", password=SENHA)

    def test_visitante_sem_login_e_redirecionado(self):
        for url in [reverse("menu"), reverse("participante_lista"), reverse("presenca_selecionar")]:
            resposta = self.client.get(url)
            self.assertEqual(resposta.status_code, 302)
            self.assertIn(reverse("login"), resposta["Location"])

    def test_senha_incorreta_e_recusada(self):
        resposta = self.client.post(reverse("login"), {"username": "responsavel", "password": "errada"})
        self.assertEqual(resposta.status_code, 200)
        self.assertContains(resposta, "Usuário ou senha incorretos")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_login_valido_e_logout_encerram_sessao(self):
        resposta = self.client.post(reverse("login"), {"username": "responsavel", "password": SENHA})
        self.assertRedirects(resposta, reverse("menu"))
        self.client.post(reverse("logout"))
        self.assertEqual(self.client.get(reverse("menu")).status_code, 302)

    def test_senha_guardada_com_hash_pbkdf2(self):
        self.usuario.refresh_from_db()
        self.assertTrue(self.usuario.password.startswith("pbkdf2_sha256$"))
        self.assertNotIn(SENHA, self.usuario.password)

    def test_alteracao_sem_token_csrf_e_recusada(self):
        cliente = Client(enforce_csrf_checks=True)
        cliente.login(username="responsavel", password=SENHA)
        resposta = cliente.post(reverse("participante_novo"), {"nome": "X", "data_nascimento": "2000-01-01"})
        self.assertEqual(resposta.status_code, 403)
        self.assertFalse(Participante.objects.filter(nome="X").exists())


class ParticipanteTests(BaseTestCase):
    """RF02 e RF03."""

    def test_cadastro_valido(self):
        resposta = self.client.post(reverse("participante_novo"), {"nome": "Carlos", "data_nascimento": "1990-01-10"})
        self.assertRedirects(resposta, reverse("participante_lista"))
        self.assertTrue(Participante.objects.filter(nome="Carlos").exists())

    def test_data_de_nascimento_futura_e_recusada(self):
        amanha = (timezone.localdate() + timedelta(days=1)).isoformat()
        resposta = self.client.post(reverse("participante_novo"), {"nome": "Carlos", "data_nascimento": amanha})
        self.assertContains(resposta, "não pode ser no futuro")
        self.assertFalse(Participante.objects.filter(nome="Carlos").exists())

    def test_nome_obrigatorio(self):
        self.client.post(reverse("participante_novo"), {"nome": "  ", "data_nascimento": "1990-01-10"})
        self.assertEqual(Participante.objects.count(), 2)

    def test_possivel_duplicidade_pede_confirmacao_sem_bloquear(self):
        dados = {"nome": "pessoa exemplo a", "data_nascimento": "2010-03-01"}
        resposta = self.client.post(reverse("participante_novo"), dados)
        self.assertContains(resposta, "Possível cadastro repetido")
        self.assertEqual(Participante.objects.count(), 2)

        self.client.post(reverse("participante_novo"), {**dados, "confirmar_duplicidade": "on"})
        self.assertEqual(Participante.objects.count(), 3)

    def test_pesquisa_por_parte_do_nome(self):
        resposta = self.client.get(reverse("participante_lista"), {"q": "exemplo b"})
        self.assertContains(resposta, "Pessoa Exemplo B")
        self.assertNotContains(resposta, "Pessoa Exemplo A")

    def test_pesquisa_sem_resultado_informa(self):
        resposta = self.client.get(reverse("participante_lista"), {"q": "ninguém"})
        self.assertContains(resposta, "Nenhum participante encontrado")

    def test_html_digitado_e_exibido_como_texto(self):
        Participante.objects.create(nome="<script>alert(1)</script>", data_nascimento=date(2000, 1, 1))
        resposta = self.client.get(reverse("participante_lista"))
        self.assertNotContains(resposta, "<script>alert(1)</script>")
        self.assertContains(resposta, "&lt;script&gt;")

    def test_participante_com_historico_nao_e_excluido(self):
        services.inscrever(self.ana, self.atividade)
        self.client.post(reverse("participante_excluir", args=[self.ana.pk]))
        self.assertTrue(Participante.objects.filter(pk=self.ana.pk).exists())


class AtividadeTests(BaseTestCase):
    """RF04."""

    def test_cadastro_exige_nome(self):
        resposta = self.client.post(reverse("atividade_nova"), {"nome": "", "ativa": "on"})
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(Atividade.objects.count(), 1)

    def test_cadastro_valido(self):
        self.client.post(reverse("atividade_nova"), {"nome": "Futebol", "descricao": "Sábados", "ativa": "on"})
        self.assertTrue(Atividade.objects.filter(nome="Futebol", ativa=True).exists())


class InscricaoTests(BaseTestCase):
    """RF05."""

    def test_inscricao_valida(self):
        inscricao = services.inscrever(self.ana, self.atividade)
        self.assertEqual(inscricao.status, Inscricao.Status.ATIVA)

    def test_inscricao_repetida_e_recusada_sem_novo_registro(self):
        services.inscrever(self.ana, self.atividade)
        with self.assertRaises(services.RegraDeNegocioError):
            services.inscrever(self.ana, self.atividade)
        self.assertEqual(Inscricao.objects.count(), 1)

    def test_banco_impede_combinacao_duplicada(self):
        Inscricao.objects.create(participante=self.ana, atividade=self.atividade)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Inscricao.objects.create(participante=self.ana, atividade=self.atividade)

    def test_participante_ou_atividade_inativos_nao_recebem_inscricao(self):
        self.ana.ativo = False
        self.ana.save()
        with self.assertRaises(services.RegraDeNegocioError):
            services.inscrever(self.ana, self.atividade)

        self.atividade.ativa = False
        self.atividade.save()
        with self.assertRaises(services.RegraDeNegocioError):
            services.inscrever(self.bia, self.atividade)

    def test_cancelamento_mantem_registro_e_permite_reativar(self):
        inscricao = services.inscrever(self.ana, self.atividade)
        services.cancelar_inscricao(inscricao)
        inscricao.refresh_from_db()
        self.assertEqual(inscricao.status, Inscricao.Status.CANCELADA)

        services.inscrever(self.ana, self.atividade)
        self.assertEqual(Inscricao.objects.count(), 1)
        self.assertEqual(Inscricao.objects.get().status, Inscricao.Status.ATIVA)


class EncontroTests(BaseTestCase):
    """RF06."""

    def test_mesma_atividade_nao_tem_dois_encontros_no_mesmo_inicio(self):
        Encontro.objects.create(atividade=self.atividade, inicio=momento(20))
        form = EncontroForm(
            data={"inicio": "2026-11-20T14:00", "status": "previsto"},
            instance=Encontro(atividade=self.atividade),
            atividade=self.atividade,
        )
        self.assertFalse(form.is_valid())
        self.assertIn("inicio", form.errors)

    def test_outra_atividade_pode_usar_o_mesmo_horario(self):
        Encontro.objects.create(atividade=self.atividade, inicio=momento(20))
        outra = Atividade.objects.create(nome="Futebol")
        form = EncontroForm(
            data={"inicio": "2026-11-20T14:00", "status": "previsto"},
            instance=Encontro(atividade=outra),
            atividade=outra,
        )
        self.assertTrue(form.is_valid())


class PresencaTests(BaseTestCase):
    """RF07, RF08 e RF09."""

    def setUp(self):
        super().setUp()
        self.insc_ana = services.inscrever(self.ana, self.atividade)
        self.insc_bia = services.inscrever(self.bia, self.atividade)
        self.encontro = Encontro.objects.create(
            atividade=self.atividade, inicio=momento(20), status=Encontro.Status.REALIZADO
        )

    def test_lista_somente_inscritos_ativos_da_atividade(self):
        futebol = Atividade.objects.create(nome="Futebol")
        carlos = Participante.objects.create(nome="Carlos", data_nascimento=date(2009, 1, 1))
        services.inscrever(carlos, futebol)
        services.cancelar_inscricao(self.insc_bia)

        inscritos = list(services.inscritos_do_encontro(self.encontro))
        self.assertEqual(inscritos, [self.insc_ana])

    def test_registra_presenca_e_falta(self):
        services.registrar_presencas(self.encontro, {self.insc_ana.pk: "presente", self.insc_bia.pk: "faltou"})
        self.assertTrue(Presenca.objects.get(inscricao=self.insc_ana).compareceu)
        self.assertFalse(Presenca.objects.get(inscricao=self.insc_bia).compareceu)

    def test_correcao_atualiza_sem_duplicar(self):
        services.registrar_presencas(self.encontro, {self.insc_bia.pk: "faltou"})
        services.registrar_presencas(self.encontro, {self.insc_bia.pk: "presente"})
        self.assertEqual(Presenca.objects.count(), 1)
        self.assertTrue(Presenca.objects.get().compareceu)

    def test_nao_informado_nao_conta_como_falta(self):
        services.registrar_presencas(self.encontro, {self.insc_ana.pk: "nao_informado"})
        self.assertFalse(Presenca.objects.exists())

    def test_encontro_nao_realizado_nao_aceita_presenca(self):
        previsto = Encontro.objects.create(atividade=self.atividade, inicio=momento(27))
        with self.assertRaises(services.RegraDeNegocioError):
            services.registrar_presencas(previsto, {self.insc_ana.pk: "presente"})
        self.assertFalse(Presenca.objects.exists())

    def test_inscricao_de_outra_atividade_e_recusada(self):
        futebol = Atividade.objects.create(nome="Futebol")
        insc_futebol = services.inscrever(self.ana, futebol)
        with self.assertRaises(services.RegraDeNegocioError):
            services.registrar_presencas(self.encontro, {insc_futebol.pk: "presente"})

    def test_banco_impede_presenca_duplicada(self):
        Presenca.objects.create(inscricao=self.insc_ana, encontro=self.encontro, compareceu=True)
        with self.assertRaises(IntegrityError), transaction.atomic():
            Presenca.objects.create(inscricao=self.insc_ana, encontro=self.encontro, compareceu=False)

    def test_fluxo_pelas_telas(self):
        url = reverse("presenca_registrar", args=[self.encontro.pk])
        resposta = self.client.post(url, {f"presenca_{self.insc_ana.pk}": "presente"})
        self.assertRedirects(resposta, reverse("presenca_resultado", args=[self.encontro.pk]))
        resultado = self.client.get(reverse("presenca_resultado", args=[self.encontro.pk]))
        self.assertContains(resultado, "✓ Presente")

    def test_encontro_com_presencas_nao_e_excluido(self):
        services.registrar_presencas(self.encontro, {self.insc_ana.pk: "presente"})
        self.client.post(reverse("encontro_excluir", args=[self.encontro.pk]))
        self.assertTrue(Encontro.objects.filter(pk=self.encontro.pk).exists())


class HistoricoTests(BaseTestCase):
    """RF10."""

    def test_historico_reune_atividades_sem_misturar_participantes(self):
        futebol = Atividade.objects.create(nome="Futebol")
        insc_leitura = services.inscrever(self.ana, self.atividade)
        insc_futebol = services.inscrever(self.ana, futebol)
        insc_bia = services.inscrever(self.bia, self.atividade)

        leitura = Encontro.objects.create(atividade=self.atividade, inicio=momento(13), status="realizado")
        jogo = Encontro.objects.create(atividade=futebol, inicio=momento(14, 9), status="realizado")
        services.registrar_presencas(leitura, {insc_leitura.pk: "presente", insc_bia.pk: "faltou"})
        services.registrar_presencas(jogo, {insc_futebol.pk: "faltou"})

        historico = services.historico_participante(self.ana)
        self.assertEqual([h["inscricao"].atividade.nome for h in historico], ["Futebol", "Oficina de leitura"])
        self.assertEqual(sum(h["total_registrado"] for h in historico), 2)

        resposta = self.client.get(reverse("participante_detalhe", args=[self.ana.pk]))
        self.assertContains(resposta, "Futebol")
        self.assertContains(resposta, "Oficina de leitura")
        self.assertContains(resposta, "13/11/2026 14:00")


@override_settings(LOGIN_LIMITE_TENTATIVAS=5)
class BloqueioLoginTests(TestCase):
    """RNF01: bloqueio temporário após tentativas erradas."""

    def setUp(self):
        cache.clear()
        User.objects.create_user("responsavel", password=SENHA)

    def tentar(self, senha, usuario="responsavel"):
        return self.client.post(reverse("login"), {"username": usuario, "password": senha})

    def test_sexta_tentativa_e_bloqueada_mesmo_com_senha_correta(self):
        for _ in range(5):
            self.assertEqual(self.tentar("errada").status_code, 200)
        resposta = self.tentar(SENHA)
        self.assertEqual(resposta.status_code, 429)
        self.assertContains(resposta, "Muitas tentativas", status_code=429)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_bloqueio_nao_revela_se_a_conta_existe(self):
        for _ in range(5):
            self.tentar("errada", usuario="ninguem")
        resposta = self.tentar("errada", usuario="ninguem")
        self.assertContains(resposta, "Muitas tentativas", status_code=429)

    def test_maiusculas_e_espacos_contam_como_o_mesmo_usuario(self):
        for _ in range(5):
            self.tentar("errada", usuario="Responsavel ")
        self.assertEqual(self.tentar(SENHA).status_code, 429)

    def test_login_correto_zera_o_contador(self):
        for _ in range(4):
            self.tentar("errada")
        self.assertRedirects(self.tentar(SENHA), reverse("menu"))
        self.client.post(reverse("logout"))
        self.tentar("errada")
        self.assertRedirects(self.tentar(SENHA), reverse("menu"))

    def test_acesso_volta_depois_que_o_bloqueio_expira(self):
        for _ in range(5):
            self.tentar("errada")
        cache.clear()  # simula o fim dos 15 minutos
        self.assertRedirects(self.tentar(SENHA), reverse("menu"))


class RefatoracaoTests(BaseTestCase):
    """Exclusão protegida na camada de serviços, leitura da chamada e paginação."""

    def test_exclusao_com_historico_vira_mensagem_de_regra(self):
        services.inscrever(self.ana, self.atividade)
        with self.assertRaisesMessage(services.RegraDeNegocioError, "tem histórico"):
            services.excluir_sem_historico(self.ana)
        self.assertTrue(Participante.objects.filter(pk=self.ana.pk).exists())

    def test_exclusao_sem_historico_remove_o_registro(self):
        services.excluir_sem_historico(self.bia)
        self.assertFalse(Participante.objects.filter(pk=self.bia.pk).exists())

    def test_leitura_da_chamada_ignora_campos_malformados(self):
        dados = {"presenca_7": "presente", "presenca_x": "faltou", "presenca_": "faltou", "csrfmiddlewaretoken": "t"}
        self.assertEqual(ler_marcacoes_da_chamada(dados), {7: "presente"})

    def test_lista_de_participantes_e_paginada(self):
        Participante.objects.bulk_create(
            [Participante(nome=f"Morador {i:02d}", data_nascimento=date(2000, 1, 1)) for i in range(30)]
        )
        primeira = self.client.get(reverse("participante_lista"))
        self.assertEqual(len(primeira.context["participantes"]), 25)
        self.assertContains(primeira, "Página 1 de 2")

        segunda = self.client.get(reverse("participante_lista"), {"q": "Morador", "pagina": 2})
        self.assertEqual(len(segunda.context["participantes"]), 5)
        self.assertContains(segunda, "q=Morador&amp;pagina=1")


class AjustesDaValidacaoTests(BaseTestCase):
    """Ajustes de usabilidade da 1ª rodada de validação com a representante da associação."""

    def setUp(self):
        super().setUp()
        services.inscrever(self.ana, self.atividade)
        agora = timezone.now()
        self.hoje = Encontro.objects.create(
            atividade=self.atividade, inicio=agora, status=Encontro.Status.REALIZADO
        )
        self.antigo = Encontro.objects.create(
            atividade=self.atividade, inicio=agora - timedelta(days=7), status=Encontro.Status.REALIZADO
        )
        self.previsto_hoje = Encontro.objects.create(
            atividade=self.atividade, inicio=agora + timedelta(hours=1), status=Encontro.Status.PREVISTO
        )

    def test_menu_usa_o_termo_fazer_chamada(self):
        resposta = self.client.get(reverse("menu"))
        self.assertContains(resposta, "Fazer chamada")
        self.assertNotContains(resposta, "Registrar presença")

    def test_encontros_de_hoje_trazem_so_os_realizados_do_dia(self):
        encontros = list(services.encontros_de_hoje(timezone.localdate()))
        self.assertIn(self.hoje, encontros)
        self.assertNotIn(self.antigo, encontros)
        self.assertNotIn(self.previsto_hoje, encontros)

    def test_tela_de_selecao_mostra_atalho_para_encontros_de_hoje(self):
        resposta = self.client.get(reverse("presenca_selecionar"))
        self.assertContains(resposta, "Encontros de hoje")
        self.assertContains(resposta, reverse("presenca_registrar", args=[self.hoje.pk]))

    def test_chamada_explica_o_nao_informado(self):
        resposta = self.client.get(reverse("presenca_registrar", args=[self.hoje.pk]))
        self.assertContains(resposta, "Não informado (ainda não registrado)")

    def test_resultado_destaca_o_botao_corrigir_presencas(self):
        resposta = self.client.get(reverse("presenca_resultado", args=[self.hoje.pk]))
        self.assertContains(resposta, "botao grande")
        self.assertContains(resposta, "Corrigir presenças")
