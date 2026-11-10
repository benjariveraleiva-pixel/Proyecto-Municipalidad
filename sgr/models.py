from django.db import models
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db.models import Sum
from django.utils import timezone


# ==============================================================================
# 1. TABLAS MAESTRAS Y ORGANIZACIONALES
# ==============================================================================

class Delegacion(models.Model):
    codigo = models.CharField(max_length=20, unique=True, editable=False)
    nombre = models.CharField(max_length=120, unique=True)
    direccion = models.CharField(max_length=250, blank=True)
    activa = models.BooleanField(default=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self.codigo:
            ultimo = Delegacion.objects.order_by('-id').first()
            secuencia = (ultimo.id + 1) if ultimo else 1
            self.codigo = f"DEL-{secuencia:03d}"
        super().save(*args, **kwargs)

    def __str__(self):
        return self.nombre


class Territorio(models.Model):
    codigo = models.CharField(max_length=20, unique=True, editable=False)
    nombre = models.CharField(max_length=120)
    descripcion = models.TextField(blank=True)
    delegacion = models.ForeignKey(Delegacion, on_delete=models.PROTECT, related_name='territorios')
    activo = models.BooleanField(default=True)

    def save(self, *args, **kwargs):
        if not self.codigo:
            ultimo = Territorio.objects.order_by('-id').first()
            secuencia = (ultimo.id + 1) if ultimo else 1
            self.codigo = f"TER-{secuencia:03d}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.nombre} ({self.delegacion.nombre})"


class Cargo(models.Model):
    codigo = models.CharField(max_length=20, unique=True, editable=False)
    nombre = models.CharField(max_length=120, unique=True)
    descripcion = models.TextField(blank=True)
    activo = models.BooleanField(default=True)

    def save(self, *args, **kwargs):
        if not self.codigo:
            ultimo = Cargo.objects.order_by('-id').first()
            secuencia = (ultimo.id + 1) if ultimo else 1
            self.codigo = f"CAR-{secuencia:03d}"
        super().save(*args, **kwargs)

    def __str__(self):
        return self.nombre


class Rol(models.Model):
    ROLES_SISTEMA = [
        ('ADMIN', 'Administrador'),
        ('DELEGADO', 'Delegado o Supervisor'),
        ('FUNCIONARIO', 'Funcionario'),
        ('VERIFICADOR', 'Verificador'),
    ]
    codigo = models.CharField(max_length=20, unique=True, editable=False)
    nombre = models.CharField(max_length=30, choices=ROLES_SISTEMA, unique=True)
    permisos = models.TextField(blank=True)
    activo = models.BooleanField(default=True)

    def save(self, *args, **kwargs):
        if not self.codigo:
            ultimo = Rol.objects.order_by('-id').first()
            secuencia = (ultimo.id + 1) if ultimo else 1
            self.codigo = f"ROL-{secuencia:02d}"
        super().save(*args, **kwargs)

    def __str__(self):
        return self.get_nombre_display()


class Funcionario(models.Model):
    ESTADOS_CUENTA = [
        ('PENDIENTE', 'Pendiente de Activación'),
        ('ACTIVO', 'Activo'),
        ('BLOQUEADO', 'Bloqueado Temporalmente'),
        ('INACTIVO', 'Inactivo'),
    ]
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='funcionario')
    rut = models.CharField(max_length=15, unique=True)
    nombres = models.CharField(max_length=120)
    apellidos = models.CharField(max_length=120)
    correo = models.EmailField(unique=True)
    telefono = models.CharField(max_length=30, blank=True)
    cargo = models.ForeignKey(Cargo, on_delete=models.PROTECT, related_name='funcionarios')
    delegacion = models.ForeignKey(Delegacion, on_delete=models.PROTECT, related_name='funcionarios')
    roles = models.ManyToManyField(Rol, related_name='funcionarios')
    estado = models.CharField(max_length=20, choices=ESTADOS_CUENTA, default='ACTIVO')
    debe_cambiar_clave = models.BooleanField(default=False)
    intentos_fallidos = models.PositiveIntegerField(default=0)
    bloqueado_hasta = models.DateTimeField(null=True, blank=True)
    ultimo_acceso = models.DateTimeField(null=True, blank=True)

    @property
    def nombre_completo(self):
        return f"{self.nombres} {self.apellidos}"

    def tiene_rol(self, codigo_rol):
        return self.roles.filter(nombre=codigo_rol, activo=True).exists()

    def __str__(self):
        return f"{self.nombre_completo} - {self.cargo.nombre} ({self.delegacion.nombre})"


# ==============================================================================
# 2. VECINOS, JUNTAS DE VECINOS E HITOS (REQUERIMIENTOS NUEVOS)
# ==============================================================================

class Vecino(models.Model):
    rut = models.CharField(max_length=15, unique=True)
    nombres = models.CharField(max_length=120)
    apellidos = models.CharField(max_length=120)
    telefono = models.CharField(max_length=30)
    correo = models.EmailField(blank=True)
    direccion = models.CharField(max_length=250)
    territorio = models.ForeignKey(Territorio, on_delete=models.PROTECT, related_name='vecinos')
    activo = models.BooleanField(default=True)

    @property
    def nombre_completo(self):
        return f"{self.nombres} {self.apellidos}"

    def __str__(self):
        return f"{self.nombre_completo} ({self.rut})"


class JuntaVecinos(models.Model):
    codigo = models.CharField(max_length=20, unique=True, editable=False)
    nombre = models.CharField(max_length=150)
    direccion = models.CharField(max_length=250)
    delegacion = models.ForeignKey(Delegacion, on_delete=models.PROTECT, related_name='juntas')
    territorio = models.ForeignKey(Territorio, on_delete=models.PROTECT, related_name='juntas')
    fecha_constitucion = models.DateField()
    activa = models.BooleanField(default=True)

    def save(self, *args, **kwargs):
        if not self.codigo:
            ultimo = JuntaVecinos.objects.order_by('-id').first()
            secuencia = (ultimo.id + 1) if ultimo else 1
            self.codigo = f"JJVV-{secuencia:03d}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.codigo} - {self.nombre}"


class ParticipacionJunta(models.Model):
    vecino = models.ForeignKey(Vecino, on_delete=models.CASCADE, related_name='participaciones')
    junta = models.ForeignKey(JuntaVecinos, on_delete=models.CASCADE, related_name='integrantes')
    es_dirigente = models.BooleanField(default=False)
    cargo_directiva = models.CharField(max_length=80, blank=True, help_text="Ej: Presidente, Secretario, Socio")
    fecha_incorporacion = models.DateField(default=timezone.now)
    activo = models.BooleanField(default=True)

    class Meta:
        unique_together = ('vecino', 'junta')

    def __str__(self):
        rol = f"Dirigente ({self.cargo_directiva})" if self.es_dirigente else "Socio"
        return f"{self.vecino.nombre_completo} en {self.junta.nombre} [{rol}]"


class Hito(models.Model):
    ESTADOS_HITO = [
        ('PLANIFICADO', 'Planificado'),
        ('PROXIMO', 'Próximo'),
        ('EN_EJECUCION', 'En Ejecución'),
        ('FINALIZADO', 'Finalizado'),
        ('VENCIDO', 'Vencido'),
        ('CANCELADO', 'Cancelado'),
    ]
    codigo = models.CharField(max_length=20, unique=True, editable=False)
    nombre = models.CharField(max_length=150)
    descripcion = models.TextField(blank=True)
    periodicidad = models.CharField(max_length=80, help_text="Ej: Anual, Trimestral, Mensual, Único")
    fecha_inicio = models.DateField()
    fecha_termino = models.DateField()
    delegacion = models.ForeignKey(Delegacion, on_delete=models.PROTECT, related_name='hitos')
    territorio = models.ForeignKey(Territorio, on_delete=models.PROTECT, related_name='hitos')
    responsables = models.ManyToManyField(Funcionario, related_name='hitos_asignados')
    estado = models.CharField(max_length=20, choices=ESTADOS_HITO, default='PLANIFICADO')

    def save(self, *args, **kwargs):
        if not self.codigo:
            ultimo = Hito.objects.order_by('-id').first()
            secuencia = (ultimo.id + 1) if ultimo else 1
            self.codigo = f"HT-{secuencia:04d}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.codigo} · {self.nombre}"


# ==============================================================================
# 3. TRIMESTRES, METAS Y ASIGNACIÓN INDIVIDUAL (CON VALIDACIONES DE LA PROFE)
# ==============================================================================

class Trimestre(models.Model):
    ESTADOS_TRIMESTRE = [
        ('ABIERTO', 'Abierto / En Curso'),
        ('CERRADO', 'Cerrado'),
        ('REABIERTO', 'Reabierto con Autorización'),
    ]
    codigo = models.CharField(max_length=20, unique=True, editable=False)
    nombre = models.CharField(max_length=100)
    anio = models.PositiveIntegerField(default=2026)
    numero = models.PositiveSmallIntegerField(choices=[(1, 'T1'), (2, 'T2'), (3, 'T3'), (4, 'T4')])
    fecha_inicio = models.DateField()
    fecha_termino = models.DateField()
    estado = models.CharField(max_length=20, choices=ESTADOS_TRIMESTRE, default='ABIERTO')

    class Meta:
        unique_together = ('anio', 'numero')

    def save(self, *args, **kwargs):
        if not self.codigo:
            self.codigo = f"TRI-{self.anio}-T{self.numero}"
        super().save(*args, **kwargs)

    @property
    def dias_totales(self):
        return max((self.fecha_termino - self.fecha_inicio).days + 1, 1)

    @property
    def porcentaje_esperado_hoy(self):
        hoy = timezone.now().date()
        if hoy < self.fecha_inicio:
            return 0.0
        if hoy >= self.fecha_termino:
            return 100.0
        dias_transcurridos = (hoy - self.fecha_inicio).days + 1
        return round((dias_transcurridos / self.dias_totales) * 100.0, 1)

    def __str__(self):
        return f"{self.nombre} ({self.anio})"


class Meta(models.Model):
    codigo = models.CharField(max_length=20, unique=True, editable=False)
    nombre = models.CharField(max_length=160)
    descripcion = models.TextField(blank=True)
    tipo = models.CharField(max_length=80, default='Operativa')
    unidad_medida = models.CharField(max_length=60, default='Atenciones / Gestiones')
    requiere_evidencia = models.BooleanField(default=True)
    activa = models.BooleanField(default=True)

    def save(self, *args, **kwargs):
        if not self.codigo:
            ultimo = Meta.objects.order_by('-id').first()
            secuencia = (ultimo.id + 1) if ultimo else 1
            self.codigo = f"MT-{secuencia:03d}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.codigo} · {self.nombre}"


class AsignacionMeta(models.Model):
    funcionario = models.ForeignKey(Funcionario, on_delete=models.PROTECT, related_name='metas_asignadas')
    meta = models.ForeignKey(Meta, on_delete=models.PROTECT, related_name='asignaciones')
    trimestre = models.ForeignKey(Trimestre, on_delete=models.PROTECT, related_name='asignaciones')
    cantidad_objetivo = models.PositiveIntegerField(help_text="Meta cuantitativa a cumplir en el trimestre")
    ponderacion = models.DecimalField(max_digits=5, decimal_places=2, help_text="Porcentaje de ponderación (Ej: 25.00)")
    fecha_asignacion = models.DateTimeField(auto_now_add=True)
    observacion = models.TextField(blank=True)
    activa = models.BooleanField(default=True)

    class Meta:
        unique_together = ('funcionario', 'meta', 'trimestre')

    def clean(self):
        # Validación 1 de la profesora: Que se registre la meta cuantitativa (> 0)
        if not self.cantidad_objetivo or self.cantidad_objetivo <= 0:
            raise ValidationError("Debe registrar una meta cuantitativa (cantidad objetivo) mayor a 0.")

        # Validación 2 de la profesora: Que la meta pertenezca a un trimestre válido/abierto
        if self.trimestre_id and self.trimestre.estado == 'CERRADO':
            raise ValidationError(f"El trimestre {self.trimestre} está cerrado y no admite nuevas asignaciones ni modificaciones.")

        # Validación 3 de la profesora: Que la sumatoria de ponderaciones no supere el 100%
        if self.funcionario_id and self.trimestre_id and self.activa:
            otras_ponderaciones = AsignacionMeta.objects.filter(
                funcionario=self.funcionario,
                trimestre=self.trimestre,
                activa=True
            ).exclude(pk=self.pk).aggregate(total=Sum('ponderacion'))['total'] or 0

            suma_total = float(otras_ponderaciones) + float(self.ponderacion or 0)
            if suma_total > 100.0:
                disponible = round(100.0 - float(otras_ponderaciones), 2)
                raise ValidationError(
                    f"La sumatoria de ponderaciones para {self.funcionario.nombre_completo} en {self.trimestre.nombre} "
                    f"llegaría a {suma_total}%, superando el máximo de 100%. Porcentaje disponible: {disponible}%."
                )

    @property
    def actividades_aprobadas_count(self):
        return self.actividades.filter(estado_verificacion='APROBADA_PONDERA').count()

    @property
    def porcentaje_cumplimiento_real(self):
        if self.cantidad_objetivo <= 0:
            return 0.0
        pct = (self.actividades_aprobadas_count / self.cantidad_objetivo) * 100.0
        return round(pct, 1)

    @property
    def porcentaje_cumplimiento_aplicable(self):
        # Regla municipal: Tope máximo de 120% por meta
        return min(self.porcentaje_cumplimiento_real, 120.0)

    @property
    def resultado_ponderado(self):
        return round((self.porcentaje_cumplimiento_aplicable * float(self.ponderacion)) / 100.0, 2)

    def __str__(self):
        return f"{self.funcionario.nombre_completo} | {self.meta.nombre} ({self.ponderacion}%)"


# ==============================================================================
# 4. ACTIVIDADES, TUBO DE GESTIÓN Y VERIFICACIÓN
# ==============================================================================

class TipoAtencion(models.Model):
    codigo = models.CharField(max_length=20, unique=True, editable=False)
    nombre = models.CharField(max_length=120, unique=True)
    descripcion = models.TextField(blank=True)
    activo = models.BooleanField(default=True)

    def save(self, *args, **kwargs):
        if not self.codigo:
            ultimo = TipoAtencion.objects.order_by('-id').first()
            secuencia = (ultimo.id + 1) if ultimo else 1
            self.codigo = f"TAT-{secuencia:03d}"
        super().save(*args, **kwargs)

    def __str__(self):
        return self.nombre


class SubtipoAtencion(models.Model):
    codigo = models.CharField(max_length=20, unique=True, editable=False)
    tipo_atencion = models.ForeignKey(TipoAtencion, on_delete=models.CASCADE, related_name='subtipos')
    nombre = models.CharField(max_length=120)
    activo = models.BooleanField(default=True)

    def save(self, *args, **kwargs):
        if not self.codigo:
            ultimo = SubtipoAtencion.objects.order_by('-id').first()
            secuencia = (ultimo.id + 1) if ultimo else 1
            self.codigo = f"SUB-{secuencia:03d}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.tipo_atencion.nombre} -> {self.nombre}"


class Actividad(models.Model):
    ORIGENES = [
        ('INTERNO', 'Solicitud Interna'),
        ('EXTERNO', 'Vecino / Comunidad (Externo)'),
        ('TERRENO', 'Levantamiento en Terreno'),
    ]
    ESTADOS_VERIFICACION = [
        ('PENDIENTE', 'Pendiente de Revisión'),
        ('APROBADA_PONDERA', 'Aprobada y Pondera'),
        ('APROBADA_NO_PONDERA', 'Aprobada y No Pondera'),
        ('SOLICITUD_ANTECEDENTES', 'Solicitud de Antecedentes'),
        ('RECHAZADA', 'Rechazada'),
        ('ANULADA', 'Anulada'),
    ]
    ESTADOS_TUBO = [
        ('PENDIENTE', 'Pendiente'),
        ('EN_PROCESO', 'En Proceso'),
        ('REALIZADO', 'Realizado'),
        ('CERRADO', 'Cerrado'),
        ('NO_APLICA', 'No Aplica'),
        ('VENCIDO', 'Vencido'),
    ]

    codigo = models.CharField(max_length=20, unique=True, editable=False)
    fecha_registro = models.DateTimeField(auto_now_add=True)
    fecha_actividad = models.DateField(default=timezone.now)
    funcionario_autor = models.ForeignKey(Funcionario, on_delete=models.PROTECT, related_name='actividades_creadas')
    meta_asignada = models.ForeignKey(AsignacionMeta, on_delete=models.PROTECT, related_name='actividades')
    hito = models.ForeignKey(Hito, on_delete=models.SET_NULL, null=True, blank=True, related_name='actividades')
    tipo_actividad = models.CharField(max_length=120)
    descripcion = models.TextField()
    origen = models.CharField(max_length=20, choices=ORIGENES, default='EXTERNO')

    # Solicitante (Vecino o Nombre de Contacto/Organización)
    vecino_solicitante = models.ForeignKey(Vecino, on_delete=models.SET_NULL, null=True, blank=True)
    solicitante_nombre = models.CharField(max_length=150)
    solicitante_rut = models.CharField(max_length=20, blank=True)
    solicitante_telefono = models.CharField(max_length=30, blank=True)
    territorio = models.ForeignKey(Territorio, on_delete=models.PROTECT, related_name='actividades')

    # Campos del Tubo de Gestión (Sin duplicar entidad, como exige la Municipalidad)
    ingresa_al_tubo = models.BooleanField(default=False)
    responsable_tubo = models.ForeignKey(Funcionario, on_delete=models.PROTECT, related_name='compromisos_tubo')
    area_apoyo = models.CharField(max_length=120, blank=True, help_text="Ej: DISERCO, Tránsito, Alumbrado Público")
    fecha_compromiso = models.DateField(null=True, blank=True)
    estado_tubo = models.CharField(max_length=20, choices=ESTADOS_TUBO, default='PENDIENTE')
    avances_observaciones = models.TextField(blank=True)
    fecha_cierre = models.DateField(null=True, blank=True)

    # Estado de Verificación
    estado_verificacion = models.CharField(max_length=30, choices=ESTADOS_VERIFICACION, default='PENDIENTE')
    observacion_verificador = models.TextField(blank=True)
    verificado_por = models.ForeignKey(
        Funcionario, on_delete=models.SET_NULL, null=True, blank=True, related_name='actividades_verificadas'
    )
    fecha_verificacion = models.DateTimeField(null=True, blank=True)

    def save(self, *args, **kwargs):
        if not self.codigo:
            ultimo = Actividad.objects.order_by('-id').first()
            secuencia = (ultimo.id + 1) if ultimo else 1
            self.codigo = f"AC-{secuencia:04d}"

        # Cálculo automático de estado VENCIDO en el Tubo
        if self.ingresa_al_tubo and self.fecha_compromiso:
            hoy = timezone.now().date()
            if hoy > self.fecha_compromiso and self.estado_tubo in ['PENDIENTE', 'EN_PROCESO']:
                self.estado_tubo = 'VENCIDO'
        super().save(*args, **kwargs)

    @property
    def bloqueada_edicion(self):
        return self.estado_verificacion in ['APROBADA_PONDERA', 'APROBADA_NO_PONDERA']

    def __str__(self):
        return f"{self.codigo} - {self.descripcion[:50]}"


# ==============================================================================
# 5. TUBO DE CARTAS, GESTIONES SOCIALES, EVIDENCIAS Y BITÁCORA
# ==============================================================================

class TuboCarta(models.Model):
    ESTADOS_CARTA = [
        ('INGRESADA', 'Ingresada'),
        ('DERIVADA', 'Derivada'),
        ('EN_PROCESO', 'En Proceso'),
        ('APROBADA', 'Aprobada'),
        ('FINALIZADA', 'Finalizada'),
        ('NO_APLICA', 'No Aplica'),
    ]
    codigo = models.CharField(max_length=20, unique=True, editable=False)
    numero_carta = models.CharField(max_length=50, unique=True)
    fecha_ingreso = models.DateField(default=timezone.now)
    remitente = models.CharField(max_length=150)
    destinatario = models.CharField(max_length=150)
    telefono = models.CharField(max_length=30, blank=True)
    materia = models.TextField()
    delegacion = models.ForeignKey(Delegacion, on_delete=models.PROTECT, related_name='cartas')
    responsable_seguimiento = models.ForeignKey(Funcionario, on_delete=models.PROTECT, related_name='cartas_asignadas')
    area_derivada = models.CharField(max_length=120, blank=True)
    fecha_respuesta_compromiso = models.DateField(null=True, blank=True)
    estado = models.CharField(max_length=20, choices=ESTADOS_CARTA, default='INGRESADA')
    pronunciamiento = models.TextField(blank=True)
    observaciones = models.TextField(blank=True)
    fecha_cierre = models.DateField(null=True, blank=True)

    def save(self, *args, **kwargs):
        if not self.codigo:
            ultimo = TuboCarta.objects.order_by('-id').first()
            secuencia = (ultimo.id + 1) if ultimo else 1
            self.codigo = f"CA-{secuencia:04d}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.codigo} (Carta N° {self.numero_carta}) - {self.remitente}"


class Evidencia(models.Model):
    codigo = models.CharField(max_length=30, unique=True, editable=False)
    actividad = models.ForeignKey(Actividad, on_delete=models.CASCADE, related_name='evidencias')
    archivo = models.FileField(upload_to='evidencias/%Y/%m/')
    tipo_archivo = models.CharField(max_length=40, default='Fotografía / Documento')
    autor = models.ForeignKey(Funcionario, on_delete=models.PROTECT, related_name='evidencias_subidas')
    fecha_carga = models.DateTimeField(auto_now_add=True)
    observacion = models.TextField(blank=True)

    def save(self, *args, **kwargs):
        if not self.codigo:
            cant = self.actividad.evidencias.count() + 1
            self.codigo = f"EV-{self.actividad.codigo}-{cant:02d}"
        super().save(*args, **kwargs)

    def __str__(self):
        return self.codigo


class HistorialTubo(models.Model):
    actividad = models.ForeignKey(Actividad, on_delete=models.CASCADE, null=True, blank=True, related_name='historial_tubo')
    carta = models.ForeignKey(TuboCarta, on_delete=models.CASCADE, null=True, blank=True, related_name='historial_carta')
    estado_anterior = models.CharField(max_length=40, blank=True)
    estado_nuevo = models.CharField(max_length=40)
    responsable_anterior = models.ForeignKey(
        Funcionario, on_delete=models.SET_NULL, null=True, blank=True, related_name='reasignaciones_salientes'
    )
    responsable_nuevo = models.ForeignKey(
        Funcionario, on_delete=models.SET_NULL, null=True, blank=True, related_name='reasignaciones_entrantes'
    )
    autor = models.ForeignKey(Funcionario, on_delete=models.PROTECT)
    motivo_observacion = models.TextField()
    fecha = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Cambio a {self.estado_nuevo} ({self.fecha.strftime('%d/%m/%Y %H:%M')})"


class BitacoraAuditoria(models.Model):
    usuario = models.ForeignKey(Funcionario, on_delete=models.SET_NULL, null=True, blank=True)
    modulo = models.CharField(max_length=80)
    accion = models.CharField(max_length=120)
    detalle = models.TextField()
    fecha_hora = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"[{self.fecha_hora.strftime('%d/%m/%Y %H:%M')}] {self.modulo}: {self.accion}"