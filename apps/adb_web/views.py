from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser, JSONParser
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet
from rest_framework import serializers
from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiParameter

from .services import AdbService
from .serializers import (
    DeviceSerializer,
    PackageActionSerializer,
    ShellCommandSerializer,
    InputTextSerializer,
    StartAppSerializer,
    EnvConfigSerializer,
    LogcatSerializer,
    RecordingPullSerializer,
    FlowMonitorSerializer,
    MonkeySerializer,
    InstallApkSerializer,
    TabCompleteSerializer,
)


_adb_service: AdbService | None = None


def _service() -> AdbService:
    """返回模块级单例，避免每次请求重新创建（含 4 次 mkdir 开销）。"""
    global _adb_service
    if _adb_service is None:
        _adb_service = AdbService()
    return _adb_service


@extend_schema_view(
    list=extend_schema(summary="获取已连接 ADB 设备列表", tags=["adb_web"]),
    retrieve=extend_schema(summary="获取设备详情", tags=["adb_web"]),
)
class AdbDeviceViewSet(viewsets.ViewSet):
    """
    ADB 设备 Web 端接口

    从 adb_tools.py 剥离的 CLI 能力，基于 adbutils 库实现。
    设备标识使用 URL 中的 serial（如 192.168.1.1%3A5555）。
    """

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = DeviceSerializer

    lookup_value_regex = "[^/]+"

    @extend_schema(
        summary="获取已连接 ADB 设备列表",
        responses=DeviceSerializer(many=True),
        tags=["adb_web"],
    )
    def list(self, request):
        data = _service().list_devices()
        return Response(DeviceSerializer(data, many=True).data)

    @extend_schema(
        summary="获取设备详情",
        responses=DeviceSerializer,
        tags=["adb_web"],
    )
    def retrieve(self, request, pk=None):
        data = _service().get_device_info(pk)
        return Response(DeviceSerializer(data).data)

    @extend_schema(summary="获取第三方应用包名列表", tags=["adb_web"])
    @action(detail=True, methods=["get"])
    def packages(self, request, pk=None):
        third_party = request.query_params.get("third_party", "true").lower() != "false"
        packages = _service().list_packages(pk, third_party=third_party)
        return Response({"packages": packages, "count": len(packages)})

    @extend_schema(summary="设备截图", tags=["adb_web"])
    @action(detail=True, methods=["post"])
    def screenshot(self, request, pk=None):
        return Response(_service().take_screenshot(pk))

    @extend_schema(summary="执行 Shell 命令", tags=["adb_web"], request=ShellCommandSerializer)
    @action(detail=True, methods=["post"], url_path="shell")
    def run_shell(self, request, pk=None):
        serializer = ShellCommandSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        cwd = serializer.validated_data.get("cwd") or None
        return Response(_service().run_shell(pk, serializer.validated_data["command"], cwd=cwd))

    @extend_schema(summary="清除应用数据", tags=["adb_web"], request=PackageActionSerializer)
    @action(detail=True, methods=["post"], url_path="app/clear")
    def clear_app(self, request, pk=None):
        serializer = PackageActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(_service().clear_app_data(pk, serializer.validated_data["package_name"]))

    @extend_schema(summary="结束应用进程", tags=["adb_web"], request=PackageActionSerializer)
    @action(detail=True, methods=["post"], url_path="app/stop")
    def stop_app(self, request, pk=None):
        serializer = PackageActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(_service().stop_app(pk, serializer.validated_data["package_name"]))

    @extend_schema(summary="启动应用", tags=["adb_web"], request=StartAppSerializer)
    @action(detail=True, methods=["post"], url_path="app/start")
    def start_app(self, request, pk=None):
        serializer = StartAppSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        return Response(
            _service().start_app(pk, data["package_name"], data.get("activity") or None)
        )

    @extend_schema(summary="卸载应用", tags=["adb_web"], request=PackageActionSerializer)
    @action(detail=True, methods=["post"], url_path="app/uninstall")
    def uninstall_app(self, request, pk=None):
        serializer = PackageActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(_service().uninstall_app(pk, serializer.validated_data["package_name"]))

    @extend_schema(summary="安装 APK", tags=["adb_web"], request=InstallApkSerializer)
    @action(
        detail=True,
        methods=["post"],
        url_path="app/install",
        parser_classes=[MultiPartParser, FormParser],
    )
    def install_app(self, request, pk=None):
        serializer = InstallApkSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        apk_path = _service().save_uploaded_apk(serializer.validated_data["apk"])
        return Response(_service().install_apk(pk, apk_path))

    @extend_schema(summary="导出 APK", tags=["adb_web"], parameters=[
        OpenApiParameter(name="package_name", required=True, type=str),
    ])
    @action(detail=True, methods=["get"], url_path="app/export")
    def export_app(self, request, pk=None):
        package_name = request.query_params.get("package_name")
        if not package_name:
            return Response({"detail": "请提供 package_name 参数"}, status=status.HTTP_400_BAD_REQUEST)
        return Response(_service().export_apk(pk, package_name))

    @extend_schema(summary="ADB 文本输入", tags=["adb_web"], request=InputTextSerializer)
    @action(detail=True, methods=["post"], url_path="input")
    def input_text(self, request, pk=None):
        serializer = InputTextSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(_service().input_text(pk, serializer.validated_data["text"]))

    @extend_schema(summary="写入 EChat 环境配置", tags=["adb_web"], request=EnvConfigSerializer)
    @action(detail=True, methods=["post"], url_path="config")
    def change_config(self, request, pk=None):
        serializer = EnvConfigSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(_service().change_app_env(pk, **serializer.validated_data))

    @extend_schema(summary="打开系统语言设置", tags=["adb_web"])
    @action(detail=True, methods=["post"], url_path="language")
    def language_settings(self, request, pk=None):
        return Response(_service().open_language_settings(pk))

    @extend_schema(summary="清理 logcat 缓冲区", tags=["adb_web"])
    @action(detail=True, methods=["post"], url_path="logcat/clear")
    def clear_logcat(self, request, pk=None):
        return Response(_service().clear_logcat(pk))

    @extend_schema(summary="导出 logcat 日志", tags=["adb_web"], request=LogcatSerializer)
    @action(detail=True, methods=["post"], url_path="logcat/dump", parser_classes=[JSONParser, FormParser])
    def dump_logcat(self, request, pk=None):
        serializer = LogcatSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        return Response(_service().dump_logcat(pk, data.get("keyword") or None, data["lines"]))

    @extend_schema(summary="列出设备录屏文件", tags=["adb_web"])
    @action(detail=True, methods=["get"], url_path="recordings")
    def list_recordings(self, request, pk=None):
        return Response(_service().list_recordings(pk))

    @extend_schema(summary="拉取录屏到服务器", tags=["adb_web"], request=RecordingPullSerializer)
    @action(detail=True, methods=["post"], url_path="recordings/pull")
    def pull_recording(self, request, pk=None):
        serializer = RecordingPullSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(_service().pull_recording(pk, serializer.validated_data["index"]))

    @extend_schema(summary="获取应用流量统计", tags=["adb_web"], request=FlowMonitorSerializer)
    @action(detail=True, methods=["post"], url_path="flow")
    def flow_stats(self, request, pk=None):
        serializer = FlowMonitorSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(_service().get_flow_stats(pk, serializer.validated_data["package_name"]))

    @extend_schema(summary="运行 Monkey 测试", tags=["adb_web"], request=MonkeySerializer)
    @action(detail=True, methods=["post"], url_path="monkey")
    def monkey(self, request, pk=None):
        serializer = MonkeySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(_service().run_monkey(pk, **serializer.validated_data))

    @extend_schema(
        summary="Shell Tab 补全候选",
        tags=["adb_web"],
        request=TabCompleteSerializer,
    )
    @action(detail=True, methods=["post"], url_path="tab-complete")
    def tab_complete(self, request, pk=None):
        serializer = TabCompleteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        return Response(
            _service().tab_complete(pk, data.get("prefix", ""), data.get("cwd") or None)
        )


class EnvPresetSerializer(serializers.Serializer):
    presets = serializers.ListField(
        child=serializers.CharField()
    )


class AdbMetaViewSet(viewsets.ViewSet):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = EnvPresetSerializer

    @action(detail=False, methods=["get"], url_path="env-presets")
    @extend_schema(
        summary="环境预设列表",
        tags=["adb_web"],
        responses=EnvPresetSerializer
    )
    def env_presets(self, request):
        return Response({
            "presets": AdbService.list_env_presets()
        })
