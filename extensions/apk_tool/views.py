import traceback
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404
from django.http import FileResponse
from pathlib import Path
from django.conf import settings as django_settings

from loguru import logger

from .models import BuildTask
from .serializers import BuildTaskSerializer, BuildTaskCreateSerializer
from .services.apk_service import decompile_apk, build_apk
from .services.config_service import (
    load_slclient_json, batch_update_config,
    list_terminal_configs, import_terminal_config,
    get_formatted_key_configs,
)


class BuildTaskViewSet(viewsets.ModelViewSet):
    """
    APK 构建任务 API
    """
    permission_classes = [IsAuthenticated]
    queryset = BuildTask.objects.all()

    def get_serializer_class(self):
        if self.action in ('create', 'update', 'partial_update'):
            return BuildTaskCreateSerializer
        return BuildTaskSerializer

    def create(self, request, *args, **kwargs):
        """创建构建任务 — 带详细错误日志"""
        logger.info("[APK API] 创建任务请求 — user={}, data={}", request.user.username, request.data)
        try:
            serializer = self.get_serializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            self.perform_create(serializer)
            logger.success(f"[APK API] 任务创建成功 — id={serializer.instance.id}")
            headers = self.get_success_headers(serializer.data)
            return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)
        except Exception as e:
            logger.error(f"[APK API] 创建任务异常 — {e}\n{traceback.format_exc()}")
            return Response({
                'success': False,
                'message': f'创建任务失败: {str(e)}',
                'detail': str(e),
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def perform_create(self, serializer):
        instance = serializer.save(creator=self.request.user)
        logger.info(f"[APK API] 创建构建任务 — id={instance.id}, apk_type={instance.apk_type}, creator={self.request.user.username}")

    def list(self, request, *args, **kwargs):
        logger.debug(f"[APK API] 列出构建任务 — user={request.user.username}")
        return super().list(request, *args, **kwargs)

    def retrieve(self, request, *args, **kwargs):
        logger.debug(f"[APK API] 查询构建任务 — id={kwargs.get('pk')}")
        return super().retrieve(request, *args, **kwargs)

    @action(detail=True, methods=['post'], url_path='decompile')
    def decompile(self, request, pk=None):
        """反编译 APK"""
        logger.info(f"[APK API] 反编译请求 — task_id={pk}, user={request.user.username}")
        try:
            task = self.get_object()
            task.status = 'decompiling'
            task.save()

            custom_apk_path = None
            if task.apk_type == 'custom' and task.custom_apk:
                custom_apk_path = task.custom_apk.path

            result = decompile_apk(str(task.id), task.apk_type, custom_apk_path)

            if result['success']:
                task.status = 'configuring'
                task.package_name = result.get('package_name', '')
                task.build_log = '\n'.join(result.get('logs', []))
                task.save()
                logger.success(f"[APK API] 反编译成功 — task_id={task.id}, package={task.package_name}")
                return Response({
                    'success': True,
                    'message': result['message'],
                    'package_name': result.get('package_name'),
                    'slclient_data': result.get('slclient_data', {}),
                })
            else:
                task.status = 'failed'
                task.build_log = '\n'.join(result.get('logs', []))
                task.save()
                logger.error(f"[APK API] 反编译失败 — task_id={task.id}: {result['message']}")
                return Response({
                    'success': False,
                    'message': result['message'],
                    'logs': result.get('logs', []),
                }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"[APK API] 反编译异常 — task_id={pk}: {e}\n{traceback.format_exc()}")
            return Response({
                'success': False,
                'message': f'反编译异常: {str(e)}',
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['post'], url_path='configure')
    def configure(self, request, pk=None):
        """更新配置"""
        logger.info(f"[APK API] 配置更新请求 — task_id={pk}, keys={list(request.data.keys())}")
        try:
            task = self.get_object()
            config_data = request.data

            success = batch_update_config(str(task.id), config_data)

            if success:
                updated_data = load_slclient_json(str(task.id))
                logger.success(f"[APK API] 配置更新成功 — task_id={task.id}")
                return Response({
                    'success': True,
                    'message': '配置已更新',
                    'slclient_data': updated_data,
                })
            else:
                logger.error(f"[APK API] 配置更新失败 — task_id={task.id}")
                return Response({
                    'success': False,
                    'message': '配置更新失败',
                }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"[APK API] 配置更新异常 — task_id={pk}: {e}\n{traceback.format_exc()}")
            return Response({
                'success': False,
                'message': f'配置更新异常: {str(e)}',
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['post'], url_path='import-terminal')
    def import_terminal(self, request, pk=None):
        """导入终端预设配置"""
        folder_name = request.data.get('folder_name', '')
        logger.info(f"[APK API] 导入终端配置 — task_id={pk}, folder={folder_name}")
        try:
            task = self.get_object()

            result = import_terminal_config(str(task.id), folder_name)

            if result['success']:
                task.terminal_config = folder_name
                task.save()
                logger.success(f"[APK API] 终端配置导入成功 — task_id={task.id}, folder={folder_name}")
                return Response({
                    'success': True,
                    'message': result['message'],
                    'slclient_data': result.get('slclient_data', {}),
                })
            else:
                logger.error(f"[APK API] 终端配置导入失败 — task_id={task.id}: {result['message']}")
                return Response({
                    'success': False,
                    'message': result['message'],
                }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"[APK API] 终端配置导入异常 — task_id={pk}: {e}\n{traceback.format_exc()}")
            return Response({
                'success': False,
                'message': f'终端导入异常: {str(e)}',
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['post'], url_path='build')
    def build(self, request, pk=None):
        """构建 APK（完整流程：重打包 + 对齐 + 签名）"""
        logger.info(f"[APK API] 构建请求 — task_id={pk}, user={request.user.username}")
        try:
            task = self.get_object()
            task.status = 'building'
            task.save()

            result = build_apk(
                str(task.id),
                model_name=task.device_model,
                launcher_module=task.launcher_module,
                recorder_enable=task.recorder_enable,
            )

            if result['success']:
                task.status = 'completed'
                task.apk_name = result.get('apk_name', '')
                task.apk_path = result.get('apk_path', '')
                task.apk_relative_path = result.get('apk_relative_path', '')
                task.apk_size = result.get('apk_size', 0)
                task.build_log = '\n'.join(result.get('logs', []))
                task.save()
                logger.success(f"[APK API] 构建成功 — task_id={task.id}, apk={task.apk_name}, size={task.apk_size}")
                return Response({
                    'success': True,
                    'message': result['message'],
                    'apk_name': result.get('apk_name'),
                    'apk_relative_path': result.get('apk_relative_path'),
                    'apk_size': result.get('apk_size', 0),
                })
            else:
                task.status = 'failed'
                task.build_log = '\n'.join(result.get('logs', []))
                task.save()
                logger.error(f"[APK API] 构建失败 — task_id={task.id}: {result['message']}")
                return Response({
                    'success': False,
                    'message': result['message'],
                    'logs': result.get('logs', []),
                }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"[APK API] 构建异常 — task_id={pk}: {e}\n{traceback.format_exc()}")
            return Response({
                'success': False,
                'message': f'构建异常: {str(e)}',
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['get'], url_path='download')
    def download(self, request, pk=None):
        """下载构建完成的 APK"""
        logger.info(f"[APK API] 下载请求 — task_id={pk}")
        task = self.get_object()

        if task.status != 'completed' or not task.apk_path:
            logger.warning(f"[APK API] APK 未构建完成 — task_id={task.id}, status={task.status}")
            return Response({
                'success': False,
                'message': 'APK 未构建完成',
            }, status=status.HTTP_400_BAD_REQUEST)

        apk_file = Path(task.apk_path)
        if not apk_file.exists():
            logger.error(f"[APK API] APK 文件不存在 — task_id={task.id}, path={task.apk_path}")
            return Response({
                'success': False,
                'message': 'APK 文件不存在',
            }, status=status.HTTP_404_NOT_FOUND)

        logger.success(f"[APK API] APK 下载开始 — task_id={task.id}, file={task.apk_name}")
        response = FileResponse(
            open(apk_file, 'rb'),
            as_attachment=True,
            filename=task.apk_name or apk_file.name,
        )
        return response

    @action(detail=True, methods=['get'], url_path='config')
    def get_config(self, request, pk=None):
        """获取当前配置"""
        logger.debug(f"[APK API] 获取配置 — task_id={pk}")
        task = self.get_object()
        slclient_data = load_slclient_json(str(task.id))
        return Response({
            'success': True,
            'slclient_data': slclient_data,
        })

    @action(detail=True, methods=['get'], url_path='key-configs')
    def get_key_configs(self, request, pk=None):
        """获取按键配置列表"""
        logger.debug(f"[APK API] 获取按键配置 — task_id={pk}")
        task = self.get_object()
        key_configs = get_formatted_key_configs(str(task.id))
        return Response({
            'success': True,
            'key_configs': key_configs,
        })

    @action(detail=False, methods=['get'], url_path='terminal-list')
    def terminal_list(self, request):
        """列出所有终端预设配置"""
        logger.debug(f"[APK API] 获取终端列表 — user={request.user.username}")
        configs = list_terminal_configs()
        return Response({
            'success': True,
            'terminals': configs,
            'total': len(configs),
        })
