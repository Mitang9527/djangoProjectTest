from rest_framework import serializers
from .models import BuildTask


class BuildTaskSerializer(serializers.ModelSerializer):
    creator_name = serializers.CharField(source='creator.username', read_only=True, default='—')
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    apk_type_display = serializers.CharField(source='get_apk_type_display', read_only=True)

    class Meta:
        model = BuildTask
        fields = [
            'id', 'status', 'status_display', 'apk_type', 'apk_type_display',
            'custom_apk', 'env_key', 'login_type', 'map_type',
            'sound_codec', 'dsp_provider', 'launcher_module', 'recorder_enable',
            'tone_enabled', 'tts_enabled', 'device_model', 'terminal_config',
            'package_name', 'apk_name', 'apk_path', 'apk_relative_path', 'apk_size',
            'build_log', 'created_at', 'updated_at', 'creator', 'creator_name',
        ]
        read_only_fields = [
            'id', 'package_name', 'apk_name', 'apk_path', 'apk_relative_path',
            'apk_size', 'build_log', 'created_at', 'updated_at', 'creator',
        ]


class BuildTaskCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = BuildTask
        fields = [
            'apk_type', 'custom_apk', 'env_key', 'login_type', 'map_type',
            'sound_codec', 'dsp_provider', 'launcher_module', 'recorder_enable',
            'tone_enabled', 'tts_enabled', 'device_model', 'terminal_config',
        ]
