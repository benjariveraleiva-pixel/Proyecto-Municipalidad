from django.contrib import admin
from .models import (
    Delegacion, Territorio, Cargo, Rol, Funcionario,
    Vecino, JuntaVecinos, ParticipacionJunta, Hito,
    Trimestre, Meta, AsignacionMeta, TipoAtencion, SubtipoAtencion,
    Actividad, TuboCarta, Evidencia, HistorialTubo, BitacoraAuditoria
)

# === Vistas personalizadas para el Panel Admin ===

@admin.register(Delegacion)
class DelegacionAdmin(admin.ModelAdmin):
    list_display = ('codigo', 'nombre', 'direccion', 'activa', 'fecha_creacion')
    search_fields = ('codigo', 'nombre')
    list_filter = ('activa',)
    ordering = ('nombre',)

@admin.register(Cargo)
class CargoAdmin(admin.ModelAdmin):
    list_display = ('codigo', 'nombre', 'activo')
    search_fields = ('codigo', 'nombre')
    list_filter = ('activo',)
    ordering = ('nombre',)

# === Registros estándar para el resto de tablas ===
admin.site.register(Territorio)
admin.site.register(Rol)
admin.site.register(Funcionario)
admin.site.register(Vecino)
admin.site.register(JuntaVecinos)
admin.site.register(ParticipacionJunta)
admin.site.register(Hito)
admin.site.register(Trimestre)
admin.site.register(Meta)
admin.site.register(AsignacionMeta)
admin.site.register(TipoAtencion)
admin.site.register(SubtipoAtencion)
admin.site.register(Actividad)
admin.site.register(TuboCarta)
admin.site.register(Evidencia)
admin.site.register(HistorialTubo)
admin.site.register(BitacoraAuditoria)