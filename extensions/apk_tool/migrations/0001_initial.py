import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('users', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='BuildTask',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('status', models.CharField(choices=[('pending', '等待中'), ('decompiling', '反编译中'), ('configuring', '配置中'), ('building', '构建中'), ('signing', '签名中'), ('completed', '已完成'), ('failed', '失败')], default='pending', max_length=20)),
                ('apk_type', models.CharField(choices=[('large', '大屏 APK'), ('small', '小屏 APK'), ('screenless', '无屏 APK'), ('custom', '自定义 APK')], default='large', max_length=20)),
                ('custom_apk', models.FileField(blank=True, null=True, upload_to='apk_tool/uploads/')),
                ('env_key', models.CharField(blank=True, default='domestic_v2', max_length=50)),
                ('login_type', models.CharField(blank=True, default='account', max_length=20)),
                ('map_type', models.CharField(blank=True, default='none', max_length=30)),
                ('sound_codec', models.CharField(blank=True, default='opus', max_length=30)),
                ('dsp_provider', models.CharField(blank=True, default='default', max_length=30)),
                ('launcher_module', models.CharField(blank=True, default='none', max_length=20)),
                ('recorder_enable', models.BooleanField(default=False)),
                ('tone_enabled', models.BooleanField(default=True)),
                ('tts_enabled', models.BooleanField(default=True)),
                ('device_model', models.CharField(blank=True, default='', max_length=50)),
                ('terminal_config', models.CharField(blank=True, default='', max_length=50)),
                ('package_name', models.CharField(blank=True, max_length=100)),
                ('apk_name', models.CharField(blank=True, max_length=200)),
                ('apk_path', models.CharField(blank=True, max_length=500)),
                ('apk_relative_path', models.CharField(blank=True, max_length=500)),
                ('apk_size', models.PositiveBigIntegerField(default=0)),
                ('build_log', models.TextField(blank=True, default='')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('creator', models.ForeignKey(null=True, blank=True, on_delete=models.SET_NULL, related_name='apk_build_tasks', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'APK 构建任务',
                'verbose_name_plural': 'APK 构建任务',
                'db_table': 'apk_tool_build_task',
                'ordering': ['-created_at'],
            },
        ),
    ]
