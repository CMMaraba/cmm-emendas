# cmm-emendas

Sistema de cadastro de Emendas Impositivas Municipais da Câmara Municipal de Marabá.

Cada vereador (emendas individuais) e cada bancada partidária (emendas coletivas) tem
login próprio — inclusive assessores — para cadastrar suas emendas. O setor técnico
confere e completa a classificação orçamentária antes da publicação. A tabela pública em
`/emendas/` é gerada a partir desses dados e pode ser filtrada e exportada em
CSV/JSON/XLSX/PDF pela população e por órgãos de controle.

Substitui o sistema legado em `github.com/mdmassa/cmm-emendas`, cujo modelo de dados era
uma tabela única sem autoria, alimentada por upload manual de planilha.

## Principais diferenças em relação ao sistema anterior

- **Autoria real**: cada emenda pertence a um vereador ou a uma bancada, com login próprio.
- **Fluxo de conferência**: Rascunho → Enviada → Em conferência → Publicada. Só o publicado
  aparece na tabela pública.
- **Painel de saldo**: cada gabinete/bancada vê, em tempo real, quanto já usou do teto da
  faixa e o quanto falta — com aviso e bloqueio de envio quando o limite é ultrapassado.
- **Nada de RCL/percentual/nº de vereadores fixo no código**: tudo é cadastro em
  `Exercicio`/`Faixa`, editável por técnicos designados, porque esses valores mudam
  ano a ano.
- **Catálogos em vez de texto livre**: entidades (OSCs), órgãos executores, funções e
  subfunções de governo são cadastros com FK, não texto digitado — elimina duplicidade
  de nomes e ambiguidade na anexação de documentos.
- **Sem Docker**: roda nativo no mesmo CT do Portal Modelo (gunicorn + systemd + nginx +
  PostgreSQL nativos). Ver `deploy/INSTALL.md`.

## Desenvolvimento local

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
python manage.py migrate
python manage.py seed_catalogos_2026
python manage.py createsuperuser
python manage.py runserver
```

Settings de desenvolvimento usam SQLite (`config/settings/dev.py`) — nada a configurar.

## Testes

```bash
pytest
```

## Estrutura

- `apps/parlamento` — vereadores, partidos, bancadas, perfis de acesso.
- `apps/orcamento` — exercícios, faixas (com seus tetos), catálogos (unidades gestoras,
  órgãos executores, entidades, funções/subfunções de governo, programas do PPA).
- `apps/emendas` — o modelo `Emenda`, workflow, formulários, geração do PDF oficial.
- `apps/transparencia` — tabela pública, exportações, API JSON.
- `deploy/` — unit do systemd, config do nginx, trecho para o Apache do proxy reverso,
  e o passo a passo completo de instalação (`INSTALL.md`).

## Licença

MIT — ver `LICENSE`.
