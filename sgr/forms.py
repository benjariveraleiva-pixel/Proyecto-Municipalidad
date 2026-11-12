from django import forms
from .models import AsignacionMeta, Actividad, TuboCarta
from .models import Vecino, JuntaVecinos, Hito
from django import forms
from django.contrib.auth.models import User
from .models import Funcionario, Rol
import os
from .models import Evidencia


class AsignacionMetaForm(forms.ModelForm):
    class Meta:
        model = AsignacionMeta
        fields = ['funcionario', 'meta', 'trimestre', 'cantidad_objetivo', 'ponderacion', 'observacion', 'activa']
        widgets = {
            'funcionario': forms.Select(attrs={'class': 'form-select form-select-sm'}),
            'meta': forms.Select(attrs={'class': 'form-select form-select-sm'}),
            'trimestre': forms.Select(attrs={'class': 'form-select form-select-sm'}),
            'cantidad_objetivo': forms.NumberInput(attrs={'class': 'form-control form-control-sm', 'min': '1', 'placeholder': 'Ej: 45'}),
            'ponderacion': forms.NumberInput(attrs={'class': 'form-control form-control-sm', 'step': '0.5', 'min': '1', 'max': '100', 'placeholder': 'Ej: 25.0'}),
            'observacion': forms.Textarea(attrs={'class': 'form-control form-control-sm', 'rows': 2, 'placeholder': 'Observación opcional...'}),
            'activa': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class CompromisoTuboForm(forms.ModelForm):
    class Meta:
        model = Actividad
        fields = [
            'fecha_actividad', 'meta_asignada', 'tipo_actividad', 'descripcion',
            'origen', 'solicitante_nombre', 'solicitante_rut', 'solicitante_telefono',
            'territorio', 'responsable_tubo', 'area_apoyo', 'fecha_compromiso'
        ]
        widgets = {
            'fecha_actividad': forms.DateInput(attrs={'type': 'date', 'class': 'form-control form-control-sm'}),
            'meta_asignada': forms.Select(attrs={'class': 'form-select form-select-sm'}),
            'tipo_actividad': forms.TextInput(attrs={'class': 'form-control form-control-sm', 'placeholder': 'Ej: Salida a terreno / Solicitud JJVV'}),
            'descripcion': forms.Textarea(attrs={'class': 'form-control form-control-sm', 'rows': 2}),
            'origen': forms.Select(attrs={'class': 'form-select form-select-sm'}),
            'solicitante_nombre': forms.TextInput(attrs={'class': 'form-control form-control-sm'}),
            'solicitante_rut': forms.TextInput(attrs={'class': 'form-control form-control-sm', 'placeholder': '12.345.678-9'}),
            'solicitante_telefono': forms.TextInput(attrs={'class': 'form-control form-control-sm'}),
            'territorio': forms.Select(attrs={'class': 'form-select form-select-sm'}),
            'responsable_tubo': forms.Select(attrs={'class': 'form-select form-select-sm'}),
            'area_apoyo': forms.TextInput(attrs={'class': 'form-control form-control-sm', 'placeholder': 'Ej: DISERCO / Tránsito'}),
            'fecha_compromiso': forms.DateInput(attrs={'type': 'date', 'class': 'form-control form-control-sm'}),
        }


class TuboCartaForm(forms.ModelForm):
    class Meta:
        model = TuboCarta
        fields = [
            'numero_carta', 'fecha_ingreso', 'remitente', 'destinatario',
            'telefono', 'materia', 'delegacion', 'responsable_seguimiento',
            'area_derivada', 'fecha_respuesta_compromiso'
        ]
        widgets = {
            'numero_carta': forms.TextInput(attrs={'class': 'form-control form-control-sm', 'placeholder': 'Ej: OF-2026-120'}),
            'fecha_ingreso': forms.DateInput(attrs={'type': 'date', 'class': 'form-control form-control-sm'}),
            'remitente': forms.TextInput(attrs={'class': 'form-control form-control-sm'}),
            'destinatario': forms.TextInput(attrs={'class': 'form-control form-control-sm'}),
            'telefono': forms.TextInput(attrs={'class': 'form-control form-control-sm'}),
            'materia': forms.Textarea(attrs={'class': 'form-control form-control-sm', 'rows': 2}),
            'delegacion': forms.Select(attrs={'class': 'form-select form-select-sm'}),
            'responsable_seguimiento': forms.Select(attrs={'class': 'form-select form-select-sm'}),
            'area_derivada': forms.TextInput(attrs={'class': 'form-control form-control-sm', 'placeholder': 'Ej: Operaciones / SECPLAN'}),
            'fecha_respuesta_compromiso': forms.DateInput(attrs={'type': 'date', 'class': 'form-control form-control-sm'}),
        }
        
class VecinoForm(forms.ModelForm):
    class Meta:
        model = Vecino
        fields = ['rut', 'nombres', 'apellidos', 'telefono', 'correo', 'direccion', 'territorio', 'activo']
        widgets = {
            'rut': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: 12.345.678-9'}),
            'nombres': forms.TextInput(attrs={'class': 'form-control'}),
            'apellidos': forms.TextInput(attrs={'class': 'form-control'}),
            'telefono': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '+569...'}),
            'correo': forms.EmailInput(attrs={'class': 'form-control'}),
            'direccion': forms.TextInput(attrs={'class': 'form-control'}),
            'territorio': forms.Select(attrs={'class': 'form-select'}),
            'activo': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

class JuntaVecinosForm(forms.ModelForm):
    class Meta:
        model = JuntaVecinos
        fields = ['nombre', 'direccion', 'delegacion', 'territorio', 'fecha_constitucion', 'activa']
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: JJVV Las Violetas'}),
            'direccion': forms.TextInput(attrs={'class': 'form-control'}),
            'delegacion': forms.Select(attrs={'class': 'form-select'}),
            'territorio': forms.Select(attrs={'class': 'form-select'}),
            'fecha_constitucion': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'activa': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }

class HitoForm(forms.ModelForm):
    class Meta:
        model = Hito
        fields = ['nombre', 'descripcion', 'periodicidad', 'fecha_inicio', 'fecha_termino', 'delegacion', 'territorio', 'responsables', 'estado']
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control'}),
            'descripcion': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'periodicidad': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: Anual'}),
            'fecha_inicio': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'fecha_termino': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'delegacion': forms.Select(attrs={'class': 'form-select'}),
            'territorio': forms.Select(attrs={'class': 'form-select'}),
            'responsables': forms.SelectMultiple(attrs={'class': 'form-select'}),
            'estado': forms.Select(attrs={'class': 'form-select'}),
        }

class FuncionarioCreateForm(forms.ModelForm):
    username = forms.CharField(
        label="Nombre de Usuario Institucional",
        max_length=150, 
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: jperezo'})
    )
    roles = forms.ModelMultipleChoiceField(
        queryset=Rol.objects.filter(activo=True),
        widget=forms.SelectMultiple(attrs={'class': 'form-select', 'size': '4'}),
        help_text="Mantenga presionado Ctrl (o Cmd) para seleccionar múltiples roles."
    )

    class Meta:
        model = Funcionario
        fields = ['rut', 'nombres', 'apellidos', 'correo', 'telefono', 'cargo', 'delegacion', 'roles']
        widgets = {
            'rut': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '12.345.678-9'}),
            'nombres': forms.TextInput(attrs={'class': 'form-control'}),
            'apellidos': forms.TextInput(attrs={'class': 'form-control'}),
            'correo': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'correo@laserena.cl'}),
            'telefono': forms.TextInput(attrs={'class': 'form-control'}),
            'cargo': forms.Select(attrs={'class': 'form-select'}),
            'delegacion': forms.Select(attrs={'class': 'form-select'}),
        }

    def clean_username(self):
        username = self.cleaned_data.get('username')
        if User.objects.filter(username=username).exists():
            raise forms.ValidationError("Este nombre de usuario ya está en uso en el sistema.")
        return username

    def clean_correo(self):
        correo = self.cleaned_data.get('correo')
        if User.objects.filter(email=correo).exists() or Funcionario.objects.filter(correo=correo).exists():
            raise forms.ValidationError("Este correo institucional ya se encuentra registrado.")
        return correo
    
class ActividadRegistroForm(forms.ModelForm):
    archivo_evidencia = forms.FileField(
        required=False,
        label="Adjuntar Evidencia Inicial (Foto o PDF)",
        widget=forms.ClearableFileInput(attrs={'class': 'form-control form-control-sm'})
    )
    observacion_evidencia = forms.CharField(
        required=False,
        label="Descripción del archivo adjunto",
        widget=forms.TextInput(attrs={'class': 'form-control form-control-sm', 'placeholder': 'Ej: Fotografía en terreno / Acta firmada'})
    )

    class Meta:
        model = Actividad
        fields = [
            'fecha_actividad', 'meta_asignada', 'hito', 'tipo_actividad',
            'origen', 'vecino_solicitante', 'solicitante_nombre', 'solicitante_rut',
            'solicitante_telefono', 'territorio', 'descripcion',
            'ingresa_al_tubo', 'responsable_tubo', 'area_apoyo', 'fecha_compromiso'
        ]
        widgets = {
            'fecha_actividad': forms.DateInput(attrs={'type': 'date', 'class': 'form-control form-control-sm'}),
            'meta_asignada': forms.Select(attrs={'class': 'form-select form-select-sm'}),
            'hito': forms.Select(attrs={'class': 'form-select form-select-sm'}),
            'tipo_actividad': forms.TextInput(attrs={'class': 'form-control form-control-sm', 'placeholder': 'Ej: Operativo terreno / Atención presencial'}),
            'origen': forms.Select(attrs={'class': 'form-select form-select-sm'}),
            'vecino_solicitante': forms.Select(attrs={'class': 'form-select form-select-sm'}),
            'solicitante_nombre': forms.TextInput(attrs={'class': 'form-control form-control-sm', 'placeholder': 'Nombre vecino u organización'}),
            'solicitante_rut': forms.TextInput(attrs={'class': 'form-control form-control-sm', 'placeholder': '12.345.678-9'}),
            'solicitante_telefono': forms.TextInput(attrs={'class': 'form-control form-control-sm', 'placeholder': '+569...'}),
            'territorio': forms.Select(attrs={'class': 'form-select form-select-sm'}),
            'descripcion': forms.Textarea(attrs={'class': 'form-control form-control-sm', 'rows': 2, 'placeholder': 'Detalle la gestión realizada...'}),
            'ingresa_al_tubo': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'responsable_tubo': forms.Select(attrs={'class': 'form-select form-select-sm'}),
            'area_apoyo': forms.TextInput(attrs={'class': 'form-control form-control-sm', 'placeholder': 'Ej: DISERCO / Seguridad Ciudadana'}),
            'fecha_compromiso': forms.DateInput(attrs={'type': 'date', 'class': 'form-control form-control-sm'}),
        }

    def clean_archivo_evidencia(self):
        archivo = self.cleaned_data.get('archivo_evidencia')
        if archivo:
            ext = os.path.splitext(archivo.name)[1].lower()
            permitidos = ['.jpg', '.jpeg', '.png', '.pdf', '.doc', '.docx', '.xls', '.xlsx']
            if ext not in permitidos:
                raise forms.ValidationError("Formato no permitido. Suba imágenes (JPG/PNG), PDF, Word o Excel.")
            if archivo.size > 10 * 1024 * 1024:
                raise forms.ValidationError("El archivo supera el tamaño máximo permitido de 10 MB.")
        return archivo


class SubirEvidenciaForm(forms.ModelForm):
    class Meta:
        model = Evidencia
        fields = ['archivo', 'tipo_archivo', 'observacion']
        widgets = {
            'archivo': forms.ClearableFileInput(attrs={'class': 'form-control form-control-sm', 'required': True}),
            'tipo_archivo': forms.TextInput(attrs={'class': 'form-control form-control-sm', 'placeholder': 'Ej: Fotografía / Acta de reunión'}),
            'observacion': forms.TextInput(attrs={'class': 'form-control form-control-sm', 'placeholder': 'Observación o respuesta a solicitud de antecedentes'}),
        }

    def clean_archivo(self):
        archivo = self.cleaned_data.get('archivo')
        if archivo:
            ext = os.path.splitext(archivo.name)[1].lower()
            permitidos = ['.jpg', '.jpeg', '.png', '.pdf', '.doc', '.docx', '.xls', '.xlsx']
            if ext not in permitidos:
                raise forms.ValidationError("Formato de archivo inválido.")
            if archivo.size > 10 * 1024 * 1024:
                raise forms.ValidationError("El archivo supera los 10 MB.")
        return archivo
    