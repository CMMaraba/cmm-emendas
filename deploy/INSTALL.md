# Instalação nativa em 10.3.150.7 (sem Docker)

Pressupõe Ubuntu 22.04 com Python 3.10+, acesso root e o repositório já clonado.

## 1. Pacotes de sistema

```bash
apt-get update
apt-get install -y python3-venv python3-dev libpq-dev build-essential \
    fonts-liberation nginx postgresql postgresql-contrib
```

## 2. Usuário de sistema e diretórios

```bash
useradd --system --home /opt/cmm-emendas --shell /usr/sbin/nologin cmmemendas
mkdir -p /opt/cmm-emendas /var/lib/cmm-emendas/media /var/lib/cmm-emendas/static /etc/cmm-emendas
chown -R cmmemendas:cmmemendas /opt/cmm-emendas /var/lib/cmm-emendas
```

## 3. Código e virtualenv

```bash
su - cmmemendas -s /bin/bash -c '
  git clone https://github.com/CMMaraba/cmm-emendas.git /opt/cmm-emendas
  cd /opt/cmm-emendas
  python3 -m venv .venv
  .venv/bin/pip install --upgrade pip
  .venv/bin/pip install -r requirements.txt
'
```

## 4. Banco de dados

```bash
sudo -u postgres psql -c "CREATE USER cmm_emendas WITH PASSWORD 'defina-uma-senha-forte';"
sudo -u postgres psql -c "CREATE DATABASE cmm_emendas OWNER cmm_emendas;"
```

PostgreSQL deve escutar apenas em `127.0.0.1` (padrão do pacote Ubuntu — conferir
`listen_addresses` em `/etc/postgresql/*/main/postgresql.conf`).

## 5. Segredos

```bash
cp .env.example /etc/cmm-emendas/emendas.env
# editar SECRET_KEY, DB_PASSWORD, ALLOWED_HOSTS, CSRF_TRUSTED_ORIGINS
chown root:cmmemendas /etc/cmm-emendas/emendas.env
chmod 640 /etc/cmm-emendas/emendas.env
```

Gerar `SECRET_KEY`:

```bash
/opt/cmm-emendas/.venv/bin/python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

## 6. Migrações e estáticos

```bash
su - cmmemendas -s /bin/bash -c '
  cd /opt/cmm-emendas
  export DJANGO_SETTINGS_MODULE=config.settings.prod
  export ENV_FILE=/etc/cmm-emendas/emendas.env
  .venv/bin/python manage.py migrate
  .venv/bin/python manage.py collectstatic --noinput
  .venv/bin/python manage.py seed_catalogos_2026
  .venv/bin/python manage.py createsuperuser
'
```

## 7. systemd + nginx

```bash
cp deploy/cmm-emendas.service /etc/systemd/system/cmm-emendas.service
systemctl daemon-reload
systemctl enable --now cmm-emendas

cp deploy/nginx-cmm-emendas.conf /etc/nginx/sites-available/cmm-emendas
ln -s /etc/nginx/sites-available/cmm-emendas /etc/nginx/sites-enabled/cmm-emendas
nginx -t && systemctl reload nginx
```

Para homologar em paralelo ao sistema Docker atual (que já ocupa a porta 8000), trocar
`listen 0.0.0.0:8000` por `listen 0.0.0.0:8001` no arquivo do nginx antes do cutover, e
testar em `http://10.3.150.7:8001/emendas/`. Ao migrar de vez, parar o container
(`docker stop project_web_1`) e voltar o nginx para a porta 8000.

## 8. Apache em 10.3.150.20 (proxy/TLS)

Aplicar `deploy/apache-10.3.150.20.snippet.conf` — ver instruções no próprio arquivo.
Requer `a2enmod headers` e `systemctl reload apache2`.

## 9. Migração dos dados do sistema legado

```bash
su - cmmemendas -s /bin/bash -c '
  cd /opt/cmm-emendas
  export DJANGO_SETTINGS_MODULE=config.settings.prod
  export ENV_FILE=/etc/cmm-emendas/emendas.env
  .venv/bin/python manage.py importar_legado
'
```

Lê diretamente do Postgres do container legado (`project_db_1`, porta 5432 do host) e
copia a mídia de `/root/emendas/project/app/media/`. Ver `--help` do comando para opções.

## 10. Backup

Acrescentar ao `/root/pm3-backup.sh` existente no CT:

```bash
sudo -u postgres pg_dump cmm_emendas | gzip > /caminho/do/backup/cmm_emendas_$(date +%F).sql.gz
rsync -a /var/lib/cmm-emendas/media/ /caminho/do/backup/cmm-emendas-media/
```
