from functools import wraps
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User, Group
from django.db.models import Q, ProtectedError
from django.forms import modelform_factory
from django.http import Http404
from django.shortcuts import render, redirect, get_object_or_404

from .models import (
    Delegacion, Territorio, Cargo, Rol, Funcionario,
    Vecino, JuntaVecinos, ParticipacionJunta, Hito,
    Trimestre, Meta, AsignacionMeta, TipoAtencion, SubtipoAtencion,
    Actividad, TuboCarta, Evidencia, HistorialTubo,
    BitacoraAuditoria, GestionSocial
)


# ==============================================================================
# DECORADOR EXCLUSIVO DEL DESARROLLADOR (NINGÚN EMPLEADO TIENE ACCESO)
# ==============================================================================
def solo_desarrollador(view_func):
    @wraps(view_func)
    @login_required(login_url='login')
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_superuser:
            messages.error(
                request,
                "Acceso restringido: el Centro de Administración es exclusivo del desarrollador del sistema."
            )
            return redirect('dashboard_inicio')
        return view_func(request, *args, **kwargs)
    return _wrapped_view


# ==============================================================================
# FORMULARIO SEGURO PARA USUARIOS (HASH DE CONTRASEÑAS)
# ==============================================================================
class AdminUserForm(forms.ModelForm):
    nueva_contrasena = forms.CharField(
        label="Contraseña",
        required=False,
        widget=forms.PasswordInput(attrs={
            'class': 'form-control form-control-sm',
            'placeholder': 'Dejar vacío para mantener la actual (obligatoria al crear)'
        }),
        help_text="Al editar un usuario existente, déjelo en blanco si no desea cambiar su clave."
    )

    class Meta:
        model = User
        fields = [
            'username', 'first_name', 'last_name', 'email',
            'nueva_contrasena', 'is_active', 'is_staff', 'is_superuser', 'groups'
        ]

    def clean(self):
        cleaned = super().clean()
        if not self.instance.pk and not cleaned.get('nueva_contrasena'):
            self.add_error('nueva_contrasena', 'Debe definir una contraseña para crear un usuario nuevo.')
        return cleaned

    def save(self, commit=True):
        user = super().save(commit=False)
        clave = self.cleaned_data.get('nueva_contrasena')
        if clave:
            user.set_password(clave)
        if commit:
            user.save()
            self.save_m2m()
        return user


# ==============================================================================
# REGISTRO COMPLETO DE LOS 22 MODELOS (EXCLUSIVO DESARROLLADOR)
# ==============================================================================
ADMIN_MODELS = {
    # --- 1. Autenticación y Cuentas ---
    'usuarios': {
        'model': User,
        'nombre': 'Usuarios del Sistema',
        'nombre_singular': 'Usuario',
        'categoria': 'Autenticación y Cuentas',
        'icono': 'bi-person-lock',
        'form_class': AdminUserForm,
        'list_display': [
            ('username', 'Usuario'),
            ('first_name', 'Nombre'),
            ('last_name', 'Apellido'),
            ('email', 'Correo'),
            ('is_superuser', 'Superusuario'),
            ('is_active', 'Activo'),
        ],
        'search_fields': ['username', 'first_name', 'last_name', 'email'],
    },
    'grupos': {
        'model': Group,
        'nombre': 'Grupos de Permisos',
        'nombre_singular': 'Grupo',
        'categoria': 'Autenticación y Cuentas',
        'icono': 'bi-diagram-3-fill',
        'list_display': [
            ('id', 'ID'),
            ('name', 'Nombre del Grupo'),
        ],
        'search_fields': ['name'],
    },
    'funcionarios': {
        'model': Funcionario,
        'nombre': 'Funcionarios',
        'nombre_singular': 'Funcionario',
        'categoria': 'Autenticación y Cuentas',
        'icono': 'bi-person-badge-fill',
        'list_display': [
            ('rut', 'RUT'),
            ('nombre_completo', 'Nombre Completo'),
            ('correo', 'Correo'),
            ('cargo', 'Cargo'),
            ('delegacion', 'Delegación'),
            ('estado', 'Estado'),
        ],
        'search_fields': ['rut', 'nombres', 'apellidos', 'correo', 'cargo__nombre', 'delegacion__nombre'],
    },
    'roles': {
        'model': Rol,
        'nombre': 'Roles Institucionales',
        'nombre_singular': 'Rol',
        'categoria': 'Autenticación y Cuentas',
        'icono': 'bi-shield-check',
        'list_display': [
            ('codigo', 'Código'),
            ('nombre', 'Rol'),
            ('permisos', 'Descripción de Permisos'),
            ('activo', 'Activo'),
        ],
        'search_fields': ['codigo', 'nombre', 'permisos'],
    },

    # --- 2. Estructura Municipal ---
    'delegaciones': {
        'model': Delegacion,
        'nombre': 'Delegaciones',
        'nombre_singular': 'Delegación',
        'categoria': 'Estructura Municipal',
        'icono': 'bi-building-fill',
        'list_display': [
            ('codigo', 'Código'),
            ('nombre', 'Delegación'),
            ('direccion', 'Dirección'),
            ('activa', 'Activa'),
        ],
        'search_fields': ['codigo', 'nombre', 'direccion'],
    },
    'territorios': {
        'model': Territorio,
        'nombre': 'Territorios / Sectores',
        'nombre_singular': 'Territorio',
        'categoria': 'Estructura Municipal',
        'icono': 'bi-geo-alt-fill',
        'list_display': [
            ('codigo', 'Código'),
            ('nombre', 'Territorio'),
            ('delegacion', 'Delegación'),
            ('activo', 'Activo'),
        ],
        'search_fields': ['codigo', 'nombre', 'delegacion__nombre'],
    },
    'cargos': {
        'model': Cargo,
        'nombre': 'Cargos Municipales',
        'nombre_singular': 'Cargo',
        'categoria': 'Estructura Municipal',
        'icono': 'bi-briefcase-fill',
        'list_display': [
            ('codigo', 'Código'),
            ('nombre', 'Cargo'),
            ('activo', 'Activo'),
        ],
        'search_fields': ['codigo', 'nombre', 'descripcion'],
    },

    # --- 3. Planificación, Metas y Catálogos ---
    'trimestres': {
        'model': Trimestre,
        'nombre': 'Trimestres',
        'nombre_singular': 'Trimestre',
        'categoria': 'Planificación y Catálogos',
        'icono': 'bi-calendar-range-fill',
        'list_display': [
            ('codigo', 'Código'),
            ('nombre', 'Nombre'),
            ('anio', 'Año'),
            ('fecha_inicio', 'Inicio'),
            ('fecha_termino', 'Término'),
            ('estado', 'Estado'),
        ],
        'search_fields': ['codigo', 'nombre'],
    },
    'metas': {
        'model': Meta,
        'nombre': 'Catálogo de Metas',
        'nombre_singular': 'Meta',
        'categoria': 'Planificación y Catálogos',
        'icono': 'bi-bullseye',
        'list_display': [
            ('codigo', 'Código'),
            ('nombre', 'Meta'),
            ('tipo', 'Tipo'),
            ('unidad_medida', 'Unidad'),
            ('requiere_evidencia', 'Evidencia'),
            ('activa', 'Activa'),
        ],
        'search_fields': ['codigo', 'nombre', 'tipo'],
    },
    'asignacion-metas': {
        'model': AsignacionMeta,
        'nombre': 'Asignaciones de Metas',
        'nombre_singular': 'Asignación de Meta',
        'categoria': 'Planificación y Catálogos',
        'icono': 'bi-clipboard-data-fill',
        'list_display': [
            ('funcionario', 'Funcionario'),
            ('meta', 'Meta'),
            ('trimestre', 'Trimestre'),
            ('cantidad_objetivo', 'Objetivo'),
            ('ponderacion', 'Pond. (%)'),
            ('activa', 'Activa'),
        ],
        'search_fields': ['funcionario__nombres', 'funcionario__apellidos', 'meta__nombre', 'trimestre__nombre'],
    },
    'tipos-atencion': {
        'model': TipoAtencion,
        'nombre': 'Tipos de Atención',
        'nombre_singular': 'Tipo de Atención',
        'categoria': 'Planificación y Catálogos',
        'icono': 'bi-tags-fill',
        'list_display': [
            ('codigo', 'Código'),
            ('nombre', 'Nombre'),
            ('activo', 'Activo'),
        ],
        'search_fields': ['codigo', 'nombre'],
    },
    'subtipos-atencion': {
        'model': SubtipoAtencion,
        'nombre': 'Subtipos de Atención',
        'nombre_singular': 'Subtipo de Atención',
        'categoria': 'Planificación y Catálogos',
        'icono': 'bi-tag-fill',
        'list_display': [
            ('codigo', 'Código'),
            ('tipo_atencion', 'Tipo Padre'),
            ('nombre', 'Subtipo'),
            ('activo', 'Activo'),
        ],
        'search_fields': ['codigo', 'nombre', 'tipo_atencion__nombre'],
    },

    # --- 4. Comunidad y Territorio ---
    'vecinos': {
        'model': Vecino,
        'nombre': 'Vecinos',
        'nombre_singular': 'Vecino',
        'categoria': 'Comunidad y Territorio',
        'icono': 'bi-person-vcard-fill',
        'list_display': [
            ('rut', 'RUT'),
            ('nombre_completo', 'Nombre Completo'),
            ('telefono', 'Teléfono'),
            ('direccion', 'Dirección'),
            ('territorio', 'Territorio'),
            ('activo', 'Activo'),
        ],
        'search_fields': ['rut', 'nombres', 'apellidos', 'direccion', 'territorio__nombre'],
    },
    'juntas-vecinos': {
        'model': JuntaVecinos,
        'nombre': 'Juntas de Vecinos (JJVV)',
        'nombre_singular': 'Junta de Vecinos',
        'categoria': 'Comunidad y Territorio',
        'icono': 'bi-houses-fill',
        'list_display': [
            ('codigo', 'Código'),
            ('nombre', 'Nombre JJVV'),
            ('delegacion', 'Delegación'),
            ('territorio', 'Territorio'),
            ('activa', 'Activa'),
        ],
        'search_fields': ['codigo', 'nombre', 'delegacion__nombre', 'territorio__nombre'],
    },
    'participacion-juntas': {
        'model': ParticipacionJunta,
        'nombre': 'Participación en Juntas',
        'nombre_singular': 'Participación en Junta',
        'categoria': 'Comunidad y Territorio',
        'icono': 'bi-person-lines-fill',
        'list_display': [
            ('vecino', 'Vecino'),
            ('junta', 'Junta de Vecinos'),
            ('es_dirigente', 'Dirigente'),
            ('cargo_directiva', 'Cargo Directiva'),
            ('activo', 'Activo'),
        ],
        'search_fields': ['vecino__nombres', 'vecino__apellidos', 'junta__nombre', 'cargo_directiva'],
    },
    'hitos': {
        'model': Hito,
        'nombre': 'Hitos Programados',
        'nombre_singular': 'Hito',
        'categoria': 'Comunidad y Territorio',
        'icono': 'bi-flag-fill',
        'list_display': [
            ('codigo', 'Código'),
            ('nombre', 'Hito'),
            ('delegacion', 'Delegación'),
            ('fecha_inicio', 'Inicio'),
            ('fecha_termino', 'Término'),
            ('estado', 'Estado'),
        ],
        'search_fields': ['codigo', 'nombre', 'delegacion__nombre'],
    },

    # --- 5. Operación, Flujos y Evidencias ---
    'actividades': {
        'model': Actividad,
        'nombre': 'Actividades y Compromisos',
        'nombre_singular': 'Actividad',
        'categoria': 'Operación y Flujos',
        'icono': 'bi-list-check',
        'list_display': [
            ('codigo', 'Código'),
            ('fecha_actividad', 'Fecha'),
            ('funcionario_autor', 'Autor'),
            ('solicitante_nombre', 'Solicitante'),
            ('etapa_seguimiento', 'Seguimiento'),
            ('estado_verificacion', 'Verificación'),
        ],
        'search_fields': ['codigo', 'tipo_actividad', 'solicitante_nombre', 'solicitante_rut', 'junta_solicitante__nombre', 'entidad_reparacion', 'descripcion'],
    },
    'tubo-cartas': {
        'model': TuboCarta,
        'nombre': 'Tubo de Cartas',
        'nombre_singular': 'Carta',
        'categoria': 'Operación y Flujos',
        'icono': 'bi-envelope-paper-fill',
        'list_display': [
            ('codigo', 'Código'),
            ('numero_carta', 'N° Carta'),
            ('fecha_ingreso', 'Ingreso'),
            ('remitente', 'Remitente'),
            ('delegacion', 'Delegación'),
            ('estado', 'Estado'),
        ],
        'search_fields': ['codigo', 'numero_carta', 'remitente', 'destinatario', 'materia'],
    },
    'gestiones-sociales': {
        'model': GestionSocial,
        'nombre': 'Gestiones Sociales',
        'nombre_singular': 'Gestión Social',
        'categoria': 'Operación y Flujos',
        'icono': 'bi-people-fill',
        'list_display': [
            ('codigo', 'Código'),
            ('fecha_ingreso', 'Ingreso'),
            ('vecino', 'Vecino'),
            ('territorio', 'Territorio'),
            ('asistente_social', 'Asistente'),
            ('estado', 'Estado'),
        ],
        'search_fields': ['codigo', 'vecino__nombres', 'vecino__apellidos', 'vecino__rut', 'requerimiento'],
    },
    'evidencias': {
        'model': Evidencia,
        'nombre': 'Evidencias Adjuntas',
        'nombre_singular': 'Evidencia',
        'categoria': 'Operación y Flujos',
        'icono': 'bi-paperclip',
        'list_display': [
            ('codigo', 'Código'),
            ('actividad', 'Actividad'),
            ('etapa', 'Etapa'),
            ('tipo_archivo', 'Tipo'),
            ('autor', 'Autor'),
            ('fecha_carga', 'Fecha Carga'),
        ],
        'search_fields': ['codigo', 'actividad__codigo', 'tipo_archivo', 'observacion'],
    },

    # --- 6. Auditoría e Historial ---
    'historial-tubo': {
        'model': HistorialTubo,
        'nombre': 'Historial del Tubo',
        'nombre_singular': 'Registro de Historial',
        'categoria': 'Auditoría e Historial',
        'icono': 'bi-clock-history',
        'list_display': [
            ('fecha', 'Fecha'),
            ('actividad', 'Actividad'),
            ('carta', 'Carta'),
            ('estado_anterior', 'Anterior'),
            ('estado_nuevo', 'Nuevo'),
            ('autor', 'Autor'),
        ],
        'search_fields': ['estado_anterior', 'estado_nuevo', 'motivo_observacion', 'autor__nombres'],
    },
    'bitacora-auditoria': {
        'model': BitacoraAuditoria,
        'nombre': 'Bitácora de Auditoría',
        'nombre_singular': 'Registro de Auditoría',
        'categoria': 'Auditoría e Historial',
        'icono': 'bi-journal-text',
        'list_display': [
            ('fecha_hora', 'Fecha y Hora'),
            ('usuario', 'Usuario'),
            ('modulo', 'Módulo'),
            ('accion', 'Acción'),
            ('detalle', 'Detalle'),
        ],
        'search_fields': ['modulo', 'accion', 'detalle', 'usuario__nombres', 'usuario__apellidos'],
    },
}


# ==============================================================================
# UTILIDADES DE FORMULARIO Y FORMATEO DE CELDAS
# ==============================================================================
def _obtener_config_o_404(slug):
    cfg = ADMIN_MODELS.get(slug)
    if not cfg:
        raise Http404("Módulo administrativo no encontrado.")
    return cfg


def _construir_form_class(cfg):
    if 'form_class' in cfg:
        return cfg['form_class']
    return modelform_factory(cfg['model'], fields='__all__')


def _estilizar_formulario(form):
    for field in form.fields.values():
        widget = field.widget
        if isinstance(field, forms.DateField):
            field.widget = forms.DateInput(
                format='%Y-%m-%d',
                attrs={'type': 'date', 'class': 'form-control form-control-sm'}
            )
        elif isinstance(field, forms.DateTimeField):
            field.widget = forms.DateTimeInput(
                format='%Y-%m-%dT%H:%M',
                attrs={'type': 'datetime-local', 'class': 'form-control form-control-sm'}
            )
            field.input_formats = ['%Y-%m-%dT%H:%M', '%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M']
        elif isinstance(widget, forms.CheckboxInput):
            widget.attrs['class'] = 'form-check-input'
        elif isinstance(widget, forms.SelectMultiple):
            widget.attrs['class'] = 'form-select form-select-sm'
            widget.attrs['size'] = '5'
        elif isinstance(widget, forms.Select):
            widget.attrs['class'] = 'form-select form-select-sm'
        elif isinstance(widget, forms.Textarea):
            widget.attrs['class'] = 'form-control form-control-sm'
            widget.attrs['rows'] = '3'
        else:
            widget.attrs['class'] = 'form-control form-control-sm'
    return form


def _formatear_valor(obj, campo):
    display_fn = getattr(obj, f'get_{campo}_display', None)
    if callable(display_fn):
        valor = display_fn()
    else:
        valor = getattr(obj, campo, None)

    if isinstance(valor, bool):
        return {'tipo': 'bool', 'valor': valor}
    if valor is None or valor == '':
        return {'tipo': 'texto', 'valor': '—'}
    if hasattr(valor, 'strftime'):
        if hasattr(valor, 'hour'):
            return {'tipo': 'texto', 'valor': valor.strftime('%d/%m/%Y %H:%M')}
        return {'tipo': 'texto', 'valor': valor.strftime('%d/%m/%Y')}
    texto = str(valor)
    if len(texto) > 95:
        texto = texto[:92] + '...'
    return {'tipo': 'texto', 'valor': texto}


def _registrar_auditoria(request, cfg, accion, detalle):
    if cfg['model'] is BitacoraAuditoria:
        return
    func_actual = getattr(request.user, 'funcionario', None)
    BitacoraAuditoria.objects.create(
        usuario=func_actual,
        modulo=f"Admin Desarrollador / {cfg['nombre']}",
        accion=accion,
        detalle=detalle
    )


# ==============================================================================
# VISTAS DEL CENTRO DE ADMINISTRACIÓN INTEGRADO (EXCLUSIVO DESARROLLADOR)
# ==============================================================================
@solo_desarrollador
def admin_sgr_home(request):
    categorias = {}
    total_registros = 0

    for slug, cfg in ADMIN_MODELS.items():
        conteo = cfg['model'].objects.count()
        total_registros += conteo
        cat = cfg['categoria']
        categorias.setdefault(cat, []).append({
            'slug': slug,
            'nombre': cfg['nombre'],
            'icono': cfg['icono'],
            'conteo': conteo,
        })

    acciones_recientes = BitacoraAuditoria.objects.select_related('usuario').order_by('-fecha_hora')[:12]

    return render(request, 'admin_sgr/admin_home.html', {
        'categorias': categorias,
        'total_modelos': len(ADMIN_MODELS),
        'total_registros': total_registros,
        'acciones_recientes': acciones_recientes,
    })


@solo_desarrollador
def admin_sgr_list(request, slug):
    cfg = _obtener_config_o_404(slug)
    model = cfg['model']
    q = request.GET.get('q', '').strip()

    qs = model.objects.all().order_by('-pk')
    if q and cfg.get('search_fields'):
        filtro = Q()
        for campo in cfg['search_fields']:
            filtro |= Q(**{f"{campo}__icontains": q})
        qs = qs.filter(filtro)

    columnas = [label for _, label in cfg['list_display']]
    campos = [campo for campo, _ in cfg['list_display']]

    filas = []
    for obj in qs[:200]:
        filas.append({
            'pk': obj.pk,
            'titulo': str(obj),
            'celdas': [_formatear_valor(obj, c) for c in campos],
        })

    return render(request, 'admin_sgr/admin_list.html', {
        'slug': slug,
        'cfg': cfg,
        'columnas': columnas,
        'filas': filas,
        'total_encontrados': qs.count(),
        'q': q,
    })


@solo_desarrollador
def admin_sgr_crear(request, slug):
    cfg = _obtener_config_o_404(slug)
    FormClass = _construir_form_class(cfg)

    if request.method == 'POST':
        form = _estilizar_formulario(FormClass(request.POST, request.FILES))
        if form.is_valid():
            obj = form.save()
            _registrar_auditoria(request, cfg, f"Crear {cfg['nombre_singular']}", f"Se creó el registro: {obj}")
            messages.success(request, f"{cfg['nombre_singular']} creado exitosamente.")
            return redirect('admin_sgr_list', slug=slug)
        else:
            messages.error(request, "Revise los errores marcados en el formulario.")
    else:
        form = _estilizar_formulario(FormClass())

    return render(request, 'admin_sgr/admin_form.html', {
        'slug': slug,
        'cfg': cfg,
        'form': form,
        'es_edicion': False,
    })


@solo_desarrollador
def admin_sgr_editar(request, slug, pk):
    cfg = _obtener_config_o_404(slug)
    obj = get_object_or_404(cfg['model'], pk=pk)
    FormClass = _construir_form_class(cfg)

    if request.method == 'POST':
        form = _estilizar_formulario(FormClass(request.POST, request.FILES, instance=obj))
        if form.is_valid():
            obj_guardado = form.save()
            _registrar_auditoria(request, cfg, f"Editar {cfg['nombre_singular']}", f"Se actualizó el registro #{pk}: {obj_guardado}")
            messages.success(request, f"{cfg['nombre_singular']} actualizado exitosamente.")
            return redirect('admin_sgr_list', slug=slug)
        else:
            messages.error(request, "No se pudo guardar. Revise las validaciones del formulario.")
    else:
        form = _estilizar_formulario(FormClass(instance=obj))

    return render(request, 'admin_sgr/admin_form.html', {
        'slug': slug,
        'cfg': cfg,
        'form': form,
        'objeto': obj,
        'es_edicion': True,
    })


@solo_desarrollador
def admin_sgr_eliminar(request, slug, pk):
    if request.method == 'POST':
        cfg = _obtener_config_o_404(slug)
        obj = get_object_or_404(cfg['model'], pk=pk)
        nombre_obj = str(obj)
        try:
            obj.delete()
            _registrar_auditoria(request, cfg, f"Eliminar {cfg['nombre_singular']}", f"Se eliminó el registro #{pk}: {nombre_obj}")
            messages.success(request, f"Registro '{nombre_obj}' eliminado correctamente.")
        except ProtectedError:
            messages.error(
                request,
                f"No se puede eliminar '{nombre_obj}' porque tiene otros registros asociados en el sistema. Desactívelo editándolo en su lugar."
            )
    return redirect('admin_sgr_list', slug=slug)