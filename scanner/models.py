from django.db import models

class Mirror(models.Model):
    name = models.CharField(max_length=25, unique=True)
    url = models.URLField(unique=True)
    active = models.BooleanField(default=True)
    last_checked = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Channel(models.Model):
    username = models.CharField(max_length=255, unique=True)
    active = models.BooleanField(default=True)
    last_checked = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    def __str__(self):
        return self.username


class Node(models.Model):
    PROTOCOL_CHOICES = [
        ('vless', 'VLESS'),
        ('vmess', 'VMESS'),
        ('trojan', 'Trojan'),
        ('ss', 'Shadowsocks'),
    ]

    protocol = models.CharField(max_length=10, choices=PROTOCOL_CHOICES)
    raw_link = models.TextField()
    host = models.CharField(max_length=255)
    port = models.PositiveIntegerField()
    user_id = models.CharField(max_length=255, blank=True, null=True)
    remark = models.CharField(max_length=255, blank=True, null=True)
    source = models.CharField(max_length=255, blank=True, null=True)

    last_ping_ms = models.IntegerField(blank=True, null=True)
    last_speed_kbps = models.FloatField(blank=True, null=True)
    last_checked = models.DateTimeField(auto_now=True)
    is_working = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('protocol', 'host', 'port', 'user_id')

    def __str__(self):
        return f"{self.protocol.upper()} {self.host}:{self.port} {self.remark or ''}"
