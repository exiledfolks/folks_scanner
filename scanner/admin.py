from django.contrib import admin

from .actions import run_full_scan_sync
from .models import Channel, Mirror, Node, Subscription


@admin.action(description="Update subscription links for selected records")
def update_subscriptions(modeladmin, request, queryset):
    subscription_ids = list(queryset.values_list('id', flat=True))
    from .actions import push_subscription_to_github
    push_subscription_to_github(subscription_ids=subscription_ids)
    modeladmin.message_user(request, f"✅ Update completed for {len(subscription_ids)} selected subscriptions!")

@admin.action(description="Scan and update nodes for selected Mirrors")
def scan_mirrors(modeladmin, request, queryset):
    mirror_ids = list(queryset.values_list('id', flat=True))
    from .actions import run_full_scan_sync
    run_full_scan_sync(mirror_ids=mirror_ids)
    modeladmin.message_user(request, f"✅ Scan completed for {len(mirror_ids)} selected mirrors!")

@admin.action(description="Scan and update nodes for selected Channels")
def scan_channels(modeladmin, request, queryset):
    channel_ids = list(queryset.values_list('id', flat=True))
    from .actions import run_full_scan_sync
    run_full_scan_sync(channel_ids=channel_ids)
    modeladmin.message_user(request, f"✅ Scan completed for {len(channel_ids)} selected channels!")



@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ('url', 'active', 'updated_at')
    list_filter = ('active',)
    search_fields = ('url',)
    actions = [update_subscriptions]


@admin.register(Mirror)
class MirrorAdmin(admin.ModelAdmin):
    list_display = ('url', 'active', 'last_checked')
    list_filter = ('active',)
    search_fields = ('url',)
    actions = [scan_mirrors]



@admin.register(Channel)
class ChannelAdmin(admin.ModelAdmin):
    list_display = ('username', 'active', 'last_checked')
    list_filter = ('active',)
    search_fields = ('username',)
    actions = [scan_channels]



@admin.register(Node)
class NodeAdmin(admin.ModelAdmin):
    list_display = ('protocol', 'host', 'port', 'user_id', 'remark', 'is_working', 'last_speed_kbps', 'last_checked')
    list_filter = ('protocol', 'is_working')
    search_fields = ('host', 'remark', 'source')
