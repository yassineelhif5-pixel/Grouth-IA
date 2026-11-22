from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.exceptions import BusinessError
from apps.core.views import GrowthAPIView

from . import services as s


class MarketingProfileView(GrowthAPIView):
    required_module = "content"
    permission_map = {"GET": "content.read", "PUT": "content.write", "PATCH": "content.write"}

    def get(self, request):
        return Response(s.get_profile())

    def put(self, request):
        return Response(s.save_profile(request.data))

    patch = put


class MarketingConversationsView(GrowthAPIView):
    required_module = "content"
    permission_map = {"GET": "content.read", "POST": "content.write"}

    def get(self, request):
        return Response(s.list_conversations())

    def post(self, request):
        return Response(s.chat(None, request.data.get("message", "")), status=201)


class MarketingChatView(GrowthAPIView):
    required_module = "content"
    permission_map = {"GET": "content.read", "POST": "content.write"}

    def get(self, request):
        cid = request.query_params.get("conversation_id")
        if not cid:
            raise BusinessError("conversation_id is required", "invalid")
        # Ownership and tenant isolation are checked before messages are returned.
        s.get_messages(cid)
        return Response(s.get_messages(cid))

    def post(self, request):
        return Response(s.chat(request.data.get("conversation_id"), request.data.get("message", "")))


class MarketingStrategiesView(GrowthAPIView):
    required_module = "content"
    permission_map = {"GET": "content.read", "POST": "content.write"}

    def get(self, request):
        return Response(s.list_strategies())

    def post(self, request):
        cid = request.data.get("conversation_id")
        if not cid:
            raise BusinessError("conversation_id is required", "invalid")
        return Response(s.propose_strategy(cid), status=201)


class MarketingStrategyDetailView(GrowthAPIView):
    required_module = "content"
    permission_map = {"PUT": "content.write", "PATCH": "content.write"}

    def put(self, request, strategy_id):
        return Response(s.update_strategy(strategy_id, request.data))

    patch = put


class MarketingStrategyApproveView(GrowthAPIView):
    required_module = "content"
    permission_map = {"POST": "content.approve"}

    def post(self, request, strategy_id):
        return Response(s.approve_strategy(strategy_id))
