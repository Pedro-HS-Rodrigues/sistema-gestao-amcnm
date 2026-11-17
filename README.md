# Sistema de Gestão Comunitária da AMCNM

MVP desenvolvido na disciplina **Projeto de Software** (Cruzeiro do Sul Virtual) para a **Associação dos Moradores do Conjunto Novo Mondubim (AMCNM)**, em Fortaleza/CE. Projeto alinhado ao **ODS 11 – Cidades e Comunidades Sustentáveis**.

## Problema

A associação controla participantes, inscrições e presenças em anotações, planilhas e mensagens espalhadas. Isso dificulta consultar e atualizar cadastros, aumenta o risco de erros e perda de dados e consome o tempo dos responsáveis.

O MVP reúne tudo em um só lugar: **cadastro único do morador**, inscrições nas atividades e **frequência por encontro**, com histórico de participação, sem repetir os dados da pessoa.

## Funcionalidades (requisitos do MVP)

| Requisito | O que faz | Onde fica |
|---|---|---|
| RF01 | Login dos responsáveis; páginas internas exigem acesso | Tela **Entrar** e botão **Sair** |
| RF02 | Cadastro de participante (nome, nascimento, telefone opcional), com aviso de possível duplicidade | Participantes → Novo |
| RF03 | Pesquisa por parte do nome, com lista paginada (25 por página) | Participantes |
| RF04 | Cadastro de atividades (ativa/inativa) | Atividades |
| RF05 | Inscrição única por participante e atividade; cancelamento mantém o histórico | Atividade → Inscrições |
| RF06 | Encontros por atividade (previsto, realizado, cancelado) sem repetir data e horário | Atividade → Encontros |
| RF07 | Lista de chamada só com inscritos ativos | Registrar presença |
| RF08 | Registro de **Presente**, **Faltou** ou **Não informado** | Registrar presença |
| RF09 | Correção da frequência sem duplicar registros | Resultado → Corrigir presenças |
| RF10 | Histórico do morador em todas as atividades | Participante → Histórico |

## Tecnologias

- **Python 3.12+** e **Django 5.2**: telas (templates), formulários, autenticação e ORM
- **PostgreSQL** com **Psycopg 3**: banco de dados (SQLite pode ser usado só para testes rápidos)
- **HTML5 e CSS3**: telas responsivas e acessíveis, sem framework de front-end
- **Testes do Django** (`manage.py test`)

## Arquitetura

Monolito organizado em três camadas:

| Camada | Arquivos | Responsabilidade |
|---|---|---|
| Apresentação | `gestao/views.py`, `gestao/forms.py`, `templates/`, `gestao/templates/` | Recebe as ações do usuário, valida os formulários e mostra resultados e mensagens |
| Regras de negócio | `gestao/services.py`, `gestao/seguranca.py` | Inscrição, cancelamento, chamada, registro e correção de presença, histórico, exclusão protegida e bloqueio de login |
| Persistência | `gestao/models.py`, `gestao/migrations/` | Entidades, relacionamentos e restrições no banco, via ORM |

```
projeto-de-software-2026/
├── config/                  # configurações do Django (lidas de variáveis de ambiente)
├── gestao/                  # aplicação principal
│   ├── models.py            # persistência
│   ├── services.py          # regras de negócio
│   ├── seguranca.py         # bloqueio de login (RNF01)
│   ├── views.py, forms.py   # apresentação
│   ├── templates/gestao/    # telas
│   ├── static/css/          # estilo
│   ├── management/commands/ # popular_demo (dados fictícios)
│   └── tests.py             # testes automatizados
├── templates/               # layout base e tela de login
├── requirements.txt
└── .env.example
```

## Modelo de dados

| Entidade | Campos principais | Regras |
|---|---|---|
| **Participante** | nome, data_nascimento, telefone_contato, ativo | Nome obrigatório; nascimento não pode ser futuro; possível duplicidade (mesmo nome e nascimento) é mostrada para conferência, sem bloqueio |
| **Atividade** | nome, descricao, ativa | Atividade inativa não recebe inscrições |
| **Inscrição** | participante, atividade, data_inscricao, status (ativa/cancelada) | Combinação participante + atividade é **única**; exige participante e atividade ativos |
| **Encontro** | atividade, inicio, status (previsto/realizado/cancelado) | Combinação atividade + início é **única** |
| **Presença** | inscricao, encontro, compareceu | Combinação inscrição + encontro é **única**; exige encontro **realizado** e inscrição ativa da mesma atividade; sem registro significa "não informado", não falta |

Registros com histórico **não podem ser excluídos** (o banco protege os vínculos). Nesses casos, participantes e atividades são **desativados** e inscrições são **canceladas**. O CPF não é coletado (minimização de dados).

## Como rodar localmente

Pré-requisitos: Python 3.12+ e PostgreSQL.

```bash
# 1. Ambiente virtual e dependências
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 2. Banco PostgreSQL (exemplo)
sudo -u postgres psql -c "CREATE USER amcnm WITH PASSWORD 'troque-esta-senha' CREATEDB;"
sudo -u postgres psql -c "CREATE DATABASE amcnm OWNER amcnm;"

# 3. Variáveis de ambiente
cp .env.example .env               # edite os valores
set -a; source .env; set +a

# 4. Tabelas, usuário responsável e dados fictícios (opcional)
python manage.py migrate
python manage.py createsuperuser
python manage.py popular_demo

# 5. Servidor
python manage.py runserver
```

Acesse http://127.0.0.1:8000 e entre com o usuário criado. Sem `POSTGRES_DB` definido, o projeto usa SQLite, o que é útil para testar rapidamente sem instalar o PostgreSQL.

As contas dos responsáveis são criadas pela administração em `/admin/`. A senha precisa ter no mínimo 12 caracteres.

## Testes

```bash
python manage.py test
```

Os 41 testes cobrem login e logout, bloqueio após tentativas erradas, senha com hash PBKDF2, proteção CSRF, validações do cadastro, inscrição e presença duplicadas, encontro não realizado, inscrição de outra atividade, correção de frequência, histórico, exclusão protegida e paginação. Também passam no PostgreSQL 16.

## Segurança e privacidade

- Todas as páginas exigem login (`LoginRequiredMiddleware`); senhas guardadas com PBKDF2-SHA256 (padrão do Django).
- Após 5 tentativas de login erradas para o mesmo usuário, o acesso fica bloqueado por 15 minutos, com mensagem que não revela se a conta existe. O contador fica no cache do Django; em produção com vários processos, use um cache compartilhado (banco ou Redis).
- Sessão expira após 30 minutos sem uso; cookies `HttpOnly` e `SameSite=Lax`, e `Secure` em produção.
- Formulários validados no servidor; alterações só por POST com token CSRF; consultas pelo ORM (sem SQL concatenado); templates com escape automático (sem XSS).
- Segredos (`DJANGO_SECRET_KEY`, senha do banco) ficam fora do código, em variáveis de ambiente.
- Em produção: `DJANGO_DEBUG=False`, HTTPS e, se a hospedagem permitir, `DJANGO_SECURE_SSL_REDIRECT=True` e `DJANGO_SECURE_HSTS_SECONDS`.

## Acessibilidade

Botões e campos com área mínima de 44 × 44 px, foco visível, rótulos associados aos campos, contraste alto e estados indicados por texto e símbolo além da cor (✓ Presente, — Faltou, ? Não informado). As telas funcionam no celular e com zoom de 200%.

## Fora do escopo e próximos passos

- **Fora do escopo:** aplicativo nativo, módulo financeiro, notificações automáticas (WhatsApp, SMS, e-mail) e check-in por QR Code.
- **Próximos passos:** exportação CSV, implantação em hospedagem com PostgreSQL gerenciado, teste de desempenho do RNF03 e validação com a representante da associação.

## Fluxo de trabalho

- `main`: versão estável
- `feature/*`: novas funcionalidades, integradas por pull request
- Commits no padrão [Conventional Commits](https://www.conventionalcommits.org/pt-br/) (`feat:`, `fix:`, `test:`, `docs:`, `chore:`, `style:`)

## Autor

- [@Pedro-HS-Rodrigues](https://github.com/Pedro-HS-Rodrigues)
