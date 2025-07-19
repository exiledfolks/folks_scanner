from rest_framework import status
from rest_framework.renderers import BaseRenderer
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Node


class PlainTextRenderer(BaseRenderer):
    media_type = 'text/plain'
    format = 'txt'
    charset = 'utf-8'

    def render(self, data, media_type=None, renderer_context=None):
        return data if isinstance(data, bytes) else data.encode(self.charset)

class WorkingNodesView(APIView):
    """
    API endpoint to return working nodes as a plain-text subscription link.
    """
    renderer_classes = [PlainTextRenderer]

    def get(self, request):
        links = Node.objects.filter(is_working=True).values_list('raw_link', flat=True)
        return Response('\n'.join(links) + '\n', content_type='text/plain; charset=utf-8', status=status.HTTP_200_OK)
