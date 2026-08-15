"""Importa as emendas de 2026 do sistema legado (cmm-emendas / mdmassa), publicado hoje
em https://maraba.pa.leg.br/emendas/.

O legado guarda 'orgao_executor' como texto livre e o PDF final já mesclado (não a
documentação bruta da entidade). Este comando:
  1. Lê emendas_emenda, oscs_docs_oscpdf do Postgres legado (psycopg2 direto, sem ORM).
  2. Resolve cada linha para Vereador/Bancada/FuncaoGoverno/UnidadeGestora/OrgaoExecutor
     ou Entidade já semeados por `seed_catalogos_2026`.
  3. Cria/atualiza Entidade e Bancada com a documentação/ata BRUTA (osc_pdfs/,
     atas_partidos/), localizada por aproximação de nome (mesma heurística do legado,
     usada aqui só nesta migração única — o sistema novo passa a linkar por FK).
  4. Cria Emenda já como 'publicada', preservando o código antigo em `codigo_legado` e
     renumerando por faixa (elimina as colisões EPIMI 1,55%/2,00% do legado).

Rode com --dry-run primeiro para ver o relatório sem gravar nada.
"""

import os
import re
import shutil
from decimal import Decimal, InvalidOperation

import psycopg2
import psycopg2.extras
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files import File
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.emendas.models import CategoriaEconomica, Emenda
from apps.orcamento.models import (
    Entidade,
    Exercicio,
    Faixa,
    FuncaoGoverno,
    OrgaoExecutor,
    ProgramaPPA,
    SubfuncaoGoverno,
    UnidadeGestora,
)
from apps.parlamento.models import Bancada, Partido, Vereador

FAIXA_SIGLA_POR_TIPO = {"coletiva": "EPIMB", "155": "EPIMI155", "200": "EPIMI200"}

ENTIDADE_ALIASES = {
    "APAE": "APAE de Marabá",
    "APRM - Expoama": "APRM (Expoama)",
    "Inst. SERVI": "Instituto Servi",
    "Patinha de Rua": "Patinhas de Rua",
    "Rotary Club": "Rotary Clube",
}


def _normalizar(texto):
    texto = texto.upper().replace("_", " ")
    texto = re.sub(r"[^\w\s]", "", texto)
    return " ".join(texto.split())


def _mapear_unidade_gestora(raw):
    raw_lower = (raw or "").lower()
    if "sdu" in raw_lower or "superintendência de desenvolvimento urbano" in raw_lower:
        return "Prefeitura Administração Indireta (SDU)"
    if "fccm" in raw_lower or "fundação casa da cultura" in raw_lower:
        return "Prefeitura Administração Indireta (Fundação Casa da Cultura)"
    if "ipasemar" in raw_lower:
        return "Prefeitura Administração Indireta (IPASEMAR)"
    if "ssam" in raw_lower or "serviço de saneamento ambiental" in raw_lower:
        return "Prefeitura Administração Indireta (SSAM)"
    if "osc" in raw_lower:
        return "Entidade Privada Sem Fins Lucrativos"
    return "Prefeitura Administração Direta"


class Command(BaseCommand):
    help = "Importa as emendas de 2026 do banco do sistema legado (project_db_1)."

    def add_arguments(self, parser):
        parser.add_argument("--legacy-host", default="127.0.0.1")
        parser.add_argument("--legacy-port", default="5432")
        parser.add_argument("--legacy-db", default="django_db")
        parser.add_argument("--legacy-user", default="django_user")
        parser.add_argument("--legacy-password", default="django_password")
        parser.add_argument(
            "--legacy-media", default="/root/emendas/project/app/media",
            help="Caminho da pasta media do sistema legado (osc_pdfs/, atas_partidos/).",
        )
        parser.add_argument("--ano", type=int, default=2026)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        self.dry_run = options["dry_run"]
        self.legacy_media = options["legacy_media"]
        self.exercicio = Exercicio.objects.get(ano=options["ano"])
        self.faixas = {f.sigla_codigo: f for f in self.exercicio.faixas.all()}
        self.User = get_user_model()
        self.usuario_importacao = self._obter_usuario_importacao()

        self.programas_ppa_cache = {}
        self.avisos = []

        conn = psycopg2.connect(
            host=options["legacy_host"], port=options["legacy_port"], dbname=options["legacy_db"],
            user=options["legacy_user"], password=options["legacy_password"],
        )
        try:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM emendas_emenda ORDER BY tipo, CAST(numero AS INTEGER)"
                )
                linhas = cur.fetchall()
                cur.execute("SELECT nome_arquivo, arquivo FROM oscs_docs_oscpdf")
                self.osc_pdfs = cur.fetchall()
        finally:
            conn.close()

        self.stdout.write(f"{len(linhas)} emendas encontradas no sistema legado.")

        criadas, ignoradas = 0, 0
        with transaction.atomic():
            for linha in linhas:
                try:
                    # Savepoint por linha: um erro de banco em uma emenda não pode
                    # envenenar a transação e derrubar as linhas seguintes.
                    with transaction.atomic():
                        self._importar_linha(linha)
                    criadas += 1
                except Exception as exc:  # noqa: BLE001 — relatório de importação, não é produção
                    ignoradas += 1
                    self.avisos.append(f"Linha {linha.get('codigo')}: IGNORADA — {exc}")
            if self.dry_run:
                self.stdout.write(self.style.WARNING("--dry-run: revertendo a transação, nada foi gravado."))
                transaction.set_rollback(True)

        for aviso in self.avisos:
            self.stdout.write(self.style.WARNING(aviso))
        self.stdout.write(self.style.SUCCESS(f"Processadas: {criadas} · Ignoradas: {ignoradas}"))
        self._relatorio_totais()

    def _obter_usuario_importacao(self):
        usuario = self.User.objects.filter(is_superuser=True).order_by("id").first()
        if not usuario:
            raise RuntimeError("Crie um superusuário antes de importar (python manage.py createsuperuser).")
        return usuario

    def _importar_linha(self, linha):
        faixa = self.faixas[FAIXA_SIGLA_POR_TIPO[linha["tipo"]]]
        partido = Partido.objects.get(sigla=linha["partido"].strip())

        if faixa.modalidade == Faixa.Modalidade.COLETIVA:
            bancada = Bancada.objects.get(partido=partido, exercicio=self.exercicio)
            self._garantir_ata(bancada, partido.sigla)
            autor_kwargs = {"autor_bancada": bancada}
        else:
            vereador = Vereador.objects.get(nome_parlamentar=linha["vereador"].strip())
            if vereador.partido_id != partido.id:
                self.avisos.append(
                    f"{linha['codigo']}: vereador {vereador} tem partido atual "
                    f"{vereador.partido.sigla}, legado registrava {partido.sigla} — "
                    "mantida a filiação atual do cadastro."
                )
            autor_kwargs = {"autor_vereador": vereador}

        funcao = FuncaoGoverno.objects.filter(nome=linha["funcao_governo"].strip()).first()
        if not funcao:
            raise ValueError(f"Função de governo não encontrada: {linha['funcao_governo']!r}")

        subfuncao, _ = SubfuncaoGoverno.objects.get_or_create(
            funcao=funcao, nome=linha["subfuncao_governo"].strip()
        )
        programa_ppa = self._obter_programa_ppa(linha["programa_ppa"], linha["objetivos_ppa"])

        nome_ug = _mapear_unidade_gestora(linha["orgao_executor"])
        unidade_gestora = UnidadeGestora.objects.get(nome=nome_ug)

        orgao_executor = None
        entidade = None
        if unidade_gestora.exige_documentacao_entidade:
            entidade = self._obter_entidade(linha["orgao_executor"])
        else:
            orgao_executor, _ = OrgaoExecutor.objects.get_or_create(
                nome=linha["orgao_executor"].strip(), unidade_gestora=unidade_gestora
            )

        categoria = (
            CategoriaEconomica.INVESTIMENTO
            if (linha["categoria_economica"] or "").strip().lower() == "investimento"
            else CategoriaEconomica.CUSTEIO
        )

        emenda = Emenda(
            exercicio=self.exercicio,
            faixa=faixa,
            codigo_legado=linha["codigo"],
            funcao_governo=funcao,
            unidade_gestora=unidade_gestora,
            orgao_executor=orgao_executor,
            entidade=entidade,
            acao_orcamentaria=linha["acao_orcamentaria"] or "",
            objeto_despesa=linha["acao_objeto"] or "",
            categoria_economica=categoria,
            valor_custeio=self._decimal(linha["valor_custeio"]),
            valor_investimento=self._decimal(linha["valor_investimento"]),
            vinculacao_orcamentaria=linha["vinculacao_orcamentaria"] or "",
            subfuncao_governo=subfuncao,
            programa_ppa=programa_ppa,
            situacao=Emenda.Situacao.PUBLICADA,
            criada_por=self.usuario_importacao,
            conferida_por=self.usuario_importacao,
            **autor_kwargs,
        )
        emenda.full_clean(exclude=["numero", "codigo", "municipio", "partido", "modalidade", "tipo_transferencia"])
        emenda.save()
        from django.utils import timezone
        emenda.enviada_em = timezone.now()
        emenda.publicada_em = timezone.now()
        emenda.save(update_fields=["enviada_em", "publicada_em"])

    def _decimal(self, valor):
        if valor in (None, ""):
            return Decimal("0")
        try:
            return Decimal(str(valor))
        except InvalidOperation:
            return Decimal("0")

    def _obter_programa_ppa(self, nome, objetivos):
        nome = (nome or "Programa não informado").strip()
        if nome in self.programas_ppa_cache:
            return self.programas_ppa_cache[nome]
        existente = ProgramaPPA.objects.filter(exercicio=self.exercicio, nome=nome).first()
        if not existente:
            codigo = f"LEG-{ProgramaPPA.objects.filter(exercicio=self.exercicio).count() + 1:03d}"
            existente = ProgramaPPA.objects.create(
                exercicio=self.exercicio, codigo=codigo, nome=nome, objetivos=objetivos or ""
            )
        self.programas_ppa_cache[nome] = existente
        return existente

    def _obter_entidade(self, orgao_executor_raw):
        nome = orgao_executor_raw.strip()
        if nome.upper().startswith("OSC"):
            nome = re.sub(r"^OSC\s*-\s*", "", nome, flags=re.IGNORECASE).strip()
        nome = ENTIDADE_ALIASES.get(nome, nome)

        entidade, criada = Entidade.objects.get_or_create(nome=nome)
        if criada or not entidade.documentacao:
            self._vincular_documentacao_entidade(entidade)
        return entidade

    def _vincular_documentacao_entidade(self, entidade):
        alvo = _normalizar(entidade.nome)
        for row in self.osc_pdfs:
            candidato = _normalizar(os.path.splitext(row["nome_arquivo"])[0])
            if alvo in candidato or candidato in alvo:
                caminho = self._resolver_caminho_media(row["arquivo"])
                if caminho and os.path.exists(caminho) and not self.dry_run:
                    with open(caminho, "rb") as fh:
                        entidade.documentacao.save(os.path.basename(caminho), File(fh), save=True)
                return
        self.avisos.append(f"Entidade '{entidade.nome}': nenhuma documentação encontrada em osc_pdfs/.")

    def _garantir_ata(self, bancada, sigla_partido):
        if bancada.ata:
            return
        pasta_atas = os.path.join(self.legacy_media, "atas_partidos")
        if not os.path.isdir(pasta_atas):
            return
        alvo = sigla_partido.strip().upper()
        for arquivo in os.listdir(pasta_atas):
            if not arquivo.lower().endswith(".pdf"):
                continue
            if alvo in os.path.splitext(arquivo)[0].upper():
                caminho = os.path.join(pasta_atas, arquivo)
                if not self.dry_run:
                    with open(caminho, "rb") as fh:
                        bancada.ata.save(arquivo, File(fh), save=True)
                return
        self.avisos.append(f"Bancada {sigla_partido}: ata não encontrada em atas_partidos/.")

    def _resolver_caminho_media(self, campo_arquivo):
        if not campo_arquivo:
            return None
        nome = campo_arquivo if not campo_arquivo.startswith("/") else os.path.basename(campo_arquivo)
        return os.path.join(self.legacy_media, nome)

    def _relatorio_totais(self):
        from django.db.models import Sum

        self.stdout.write("\nConferência de totais por faixa:")
        for faixa in self.exercicio.faixas.all():
            total = Emenda.objects.filter(faixa=faixa).aggregate(t=Sum("valor_previsto"))["t"] or 0
            qtd = Emenda.objects.filter(faixa=faixa).count()
            self.stdout.write(f"  {faixa.nome}: {qtd} emendas — R$ {total:,.2f}".replace(",", "X").replace(".", ",").replace("X", "."))
