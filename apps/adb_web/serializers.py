from rest_framework import serializers


class DeviceSerializer(serializers.Serializer):
    serial = serializers.CharField()
    model = serializers.CharField(required=False, allow_blank=True)
    android_version = serializers.CharField(required=False, allow_blank=True)
    state = serializers.CharField(required=False, allow_blank=True)
    brand = serializers.CharField(required=False, allow_blank=True)
    sdk_version = serializers.CharField(required=False, allow_blank=True)


class PackageActionSerializer(serializers.Serializer):
    package_name = serializers.CharField(max_length=255, help_text="应用包名")


class ShellCommandSerializer(serializers.Serializer):
    command = serializers.CharField(max_length=4096, help_text="Shell 命令")


class InputTextSerializer(serializers.Serializer):
    text = serializers.CharField(max_length=500, help_text="要输入的文本")


class StartAppSerializer(serializers.Serializer):
    package_name = serializers.CharField(max_length=255)
    activity = serializers.CharField(max_length=255, required=False, allow_blank=True, help_text="可选 Activity，如 com.app/.MainActivity")


class EnvConfigSerializer(serializers.Serializer):
    account = serializers.CharField(max_length=128)
    password = serializers.CharField(max_length=128)
    env_preset = serializers.ChoiceField(
        choices=["1", "2"],
        required=False,
        allow_blank=True,
        help_text="1=国内2.0, 2=海外环境",
    )
    ip_address = serializers.CharField(max_length=255, required=False, allow_blank=True)
    context = serializers.CharField(max_length=64, required=False, allow_blank=True)
    restart_app = serializers.BooleanField(default=True)


class LogcatSerializer(serializers.Serializer):
    keyword = serializers.CharField(max_length=128, required=False, allow_blank=True)
    lines = serializers.IntegerField(default=500, min_value=1, max_value=5000)


class RecordingPullSerializer(serializers.Serializer):
    index = serializers.IntegerField(min_value=0, help_text="录屏序号")


class FlowMonitorSerializer(serializers.Serializer):
    package_name = serializers.CharField(max_length=255)


class MonkeySerializer(serializers.Serializer):
    package_name = serializers.CharField(max_length=255)
    throttle = serializers.IntegerField(default=500, min_value=0)
    seed = serializers.IntegerField(default=1000)
    event_count = serializers.IntegerField(default=1000, min_value=1, max_value=100000)


class InstallApkSerializer(serializers.Serializer):
    apk = serializers.FileField(help_text="APK 安装包")
