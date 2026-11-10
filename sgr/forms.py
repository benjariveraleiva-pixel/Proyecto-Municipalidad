from django import forms
from .models import AsignacionMeta, Actividad, TuboCarta


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