#!/usr/bin/env bash
# Build do Render: instala dependências, coleta o CSS e aplica as migrações.
set -o errexit
pip install -r requirements.txt
python manage.py collectstatic --no-input
python manage.py migrate --no-input

# Cria o responsável inicial se ele ainda não existir (usa as variáveis
# DJANGO_SUPERUSER_USERNAME, DJANGO_SUPERUSER_PASSWORD e DJANGO_SUPERUSER_EMAIL).
if [ -n "${DJANGO_SUPERUSER_USERNAME:-}" ]; then
  python manage.py createsuperuser --no-input || echo "Usuário inicial já existe."
fi

# Dados FICTÍCIOS de demonstração (opcional): defina CARREGAR_DADOS_DEMO=1.
if [ "${CARREGAR_DADOS_DEMO:-0}" = "1" ]; then
  python manage.py popular_demo
fi
