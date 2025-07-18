from django.contrib import admin
from .models import Mirror, Channel, Node
from .actions import run_full_scan

@admin.action(description="Scan and update nodes")
def scan_nodes(modeladmin, request, queryset):
    run_full_scan()
    modeladmin.message_user(request, "✅ Scan completed!")


@admin.register(Mirror)
class MirrorAdmin(admin.ModelAdmin):
    list_display = ('url', 'active', 'last_checked')
    list_filter = ('active',)
    search_fields = ('url',)


@admin.register(Channel)
class ChannelAdmin(admin.ModelAdmin):
    list_display = ('username', 'active', 'last_checked')
    list_filter = ('active',)
    search_fields = ('username',)


@admin.register(Node)
class NodeAdmin(admin.ModelAdmin):
    list_display = ('protocol', 'host', 'port', 'remark', 'is_working', 'last_speed_kbps', 'last_checked')
    list_filter = ('protocol', 'is_working')
    search_fields = ('host', 'remark', 'source')
    actions = [scan_nodes]
