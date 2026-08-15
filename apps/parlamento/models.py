from django.conf import settings
from django.db import models


class Partido(models.Model):
    sigla = models.CharField("Sigla", max_length=20, unique=True)
    nome = models.CharField("Nome", max_length=150, blank=True)
    ativo = models.BooleanField("Ativo", default=True)

    class Meta:
        verbose_name = "Partido"
        verbose_name_plural = "Partidos"
        ordering = ["sigla"]

    def __str__(self):
        return self.sigla


class Vereador(models.Model):
    nome_parlamentar = models.CharField("Nome parlamentar", max_length=150)
    nome_civil = models.CharField("Nome civil", max_length=200, blank=True)
    partido = models.ForeignKey(
        Partido, verbose_name="Partido", on_delete=models.PROTECT, related_name="vereadores"
    )
    ativo = models.BooleanField("Ativo (mandato em exercício)", default=True)

    class Meta:
        verbose_name = "Vereador"
        verbose_name_plural = "Vereadores"
        ordering = ["nome_parlamentar"]

    def __str__(self):
        return self.nome_parlamentar


class Bancada(models.Model):
    """Bancada de um partido em um exercício orçamentário específico."""

    partido = models.ForeignKey(
        Partido, verbose_name="Partido", on_delete=models.PROTECT, related_name="bancadas"
    )
    exercicio = models.ForeignKey(
        "orcamento.Exercicio", verbose_name="Exercício", on_delete=models.PROTECT, related_name="bancadas"
    )
    coordenador = models.ForeignKey(
        Vereador,
        verbose_name="Coordenador(a)",
        on_delete=models.PROTECT,
        related_name="bancadas_coordenadas",
    )
    membros = models.ManyToManyField(Vereador, verbose_name="Vereadores da bancada", related_name="bancadas")
    ata = models.FileField(
        "Ata de apresentação (PDF)", upload_to="atas_bancada/%Y/", blank=True, null=True
    )
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Bancada"
        verbose_name_plural = "Bancadas"
        unique_together = [("partido", "exercicio")]
        ordering = ["exercicio", "partido"]

    def __str__(self):
        return f"Bancada {self.partido.sigla} — {self.exercicio}"

    @property
    def num_membros(self):
        return self.membros.count()


class Perfil(models.Model):
    class Papel(models.TextChoices):
        GABINETE = "gabinete", "Gabinete de Vereador"
        BANCADA = "bancada", "Bancada"
        TECNICO = "tecnico", "Setor Técnico"
        CONFIGURADOR = "configurador", "Configurador (Setor Técnico)"
        ADMIN = "admin", "Administrador"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="perfil"
    )
    papel = models.CharField("Papel", max_length=20, choices=Papel.choices)
    vereador = models.ForeignKey(
        Vereador,
        verbose_name="Vereador (gabinete)",
        on_delete=models.CASCADE,
        related_name="usuarios_gabinete",
        null=True,
        blank=True,
        help_text="Preencher apenas para papel 'Gabinete de Vereador'.",
    )
    partido = models.ForeignKey(
        Partido,
        verbose_name="Partido (bancada)",
        on_delete=models.CASCADE,
        related_name="usuarios_bancada",
        null=True,
        blank=True,
        help_text="Preencher apenas para papel 'Bancada'.",
    )

    class Meta:
        verbose_name = "Perfil de acesso"
        verbose_name_plural = "Perfis de acesso"

    def __str__(self):
        return f"{self.user.get_username()} ({self.get_papel_display()})"

    @property
    def is_gabinete(self):
        return self.papel == self.Papel.GABINETE

    @property
    def is_bancada(self):
        return self.papel == self.Papel.BANCADA

    @property
    def is_tecnico(self):
        return self.papel in (self.Papel.TECNICO, self.Papel.CONFIGURADOR, self.Papel.ADMIN)

    @property
    def is_configurador(self):
        return self.papel in (self.Papel.CONFIGURADOR, self.Papel.ADMIN)

    def bancada_do_exercicio(self, exercicio):
        if not self.partido_id:
            return None
        return Bancada.objects.filter(partido=self.partido, exercicio=exercicio).first()
