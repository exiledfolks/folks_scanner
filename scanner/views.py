from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .models import Node

class WorkingNodesView(APIView):
    """
    API endpoint to return working nodes as a plain-text subscription link.
    """

    def get(self, request):
        nodes = Node.objects.filter(is_working=True)
        links = [node.raw_link for node in nodes]
        return Response('\n'.join(links), content_type='text/plain', status=status.HTTP_200_OK)
