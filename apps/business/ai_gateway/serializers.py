"""AI 网关 - 请求/响应序列化。"""
from rest_framework import serializers

VALID_KINDS = ("image", "video")
VALID_RESOLUTIONS = ("standard", "hd", "4k")


class GenerationRequestSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=VALID_KINDS)
    prompt = serializers.CharField(allow_blank=True, required=False, default="")
    ref_image = serializers.CharField(allow_blank=True, required=False, default=None)
    resolution = serializers.ChoiceField(choices=VALID_RESOLUTIONS, required=False, default="standard")
    count = serializers.IntegerField(min_value=1, max_value=8, required=False, default=1)
    style = serializers.CharField(allow_blank=True, required=False, default="")
    size = serializers.CharField(allow_blank=True, required=False, default="1:1")
