# Generated manually for audit log enhancement
# Date: 2026-07-17

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # Add new fields to AuditLog
        migrations.AddField(
            model_name='auditlog',
            name='log_type',
            field=models.CharField(
                choices=[('MODEL', '模型操作'), ('SENSITIVE', '敏感操作'), ('SYSTEM', '系统操作')],
                default='MODEL',
                max_length=10,
                verbose_name='日志类型'
            ),
        ),
        migrations.AddField(
            model_name='auditlog',
            name='old_data',
            field=models.JSONField(blank=True, null=True, verbose_name='变更前数据'),
        ),
        migrations.AddField(
            model_name='auditlog',
            name='new_data',
            field=models.JSONField(blank=True, null=True, verbose_name='变更后数据'),
        ),
        migrations.AddField(
            model_name='auditlog',
            name='changes',
            field=models.JSONField(blank=True, null=True, verbose_name='变更详情'),
        ),
        migrations.AddField(
            model_name='auditlog',
            name='request_path',
            field=models.CharField(blank=True, max_length=500, null=True, verbose_name='请求路径'),
        ),
        migrations.AddField(
            model_name='auditlog',
            name='request_method',
            field=models.CharField(blank=True, max_length=10, null=True, verbose_name='请求方法'),
        ),
        migrations.AddField(
            model_name='auditlog',
            name='data_hash',
            field=models.CharField(blank=True, db_index=True, max_length=128, null=True, verbose_name='数据哈希'),
        ),
        migrations.AddField(
            model_name='auditlog',
            name='previous_hash',
            field=models.CharField(blank=True, db_index=True, max_length=128, null=True, verbose_name='上一条哈希'),
        ),
        migrations.AddField(
            model_name='auditlog',
            name='is_tampered',
            field=models.BooleanField(default=False, verbose_name='是否被篡改'),
        ),
        # Alter existing fields
        migrations.AlterField(
            model_name='auditlog',
            name='action',
            field=models.CharField(
                choices=[
                    ('CREATE', '新增'),
                    ('UPDATE', '修改'),
                    ('DELETE', '删除'),
                    ('LOGIN', '登录'),
                    ('LOGOUT', '登出'),
                    ('LOGIN_FAILED', '登录失败'),
                    ('PERMISSION_CHANGE', '权限变更'),
                    ('DATA_EXPORT', '数据导出'),
                    ('SETTINGS_CHANGE', '配置变更'),
                    ('PASSWORD_CHANGE', '密码变更'),
                    ('OTHER', '其他'),
                ],
                max_length=20,
                verbose_name='操作行为'
            ),
        ),
        migrations.AlterField(
            model_name='auditlog',
            name='target_id',
            field=models.CharField(blank=True, max_length=100, null=True, verbose_name='目标ID'),
        ),
        # Add indexes
        migrations.AddIndex(
            model_name='auditlog',
            index=models.Index(fields=['action', 'created_at'], name='core_audit_action_created_idx'),
        ),
        migrations.AddIndex(
            model_name='auditlog',
            index=models.Index(fields=['target_model', 'target_id'], name='core_audit_model_target_idx'),
        ),
        migrations.AddIndex(
            model_name='auditlog',
            index=models.Index(fields=['user', 'created_at'], name='core_audit_user_created_idx'),
        ),
        # Create AuditExcludeModel
        migrations.CreateModel(
            name='AuditExcludeModel',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('app_label', models.CharField(max_length=100, verbose_name='应用标签')),
                ('model_name', models.CharField(max_length=100, verbose_name='模型名称')),
                ('exclude_fields', models.JSONField(blank=True, default=list, null=True, verbose_name='排除字段')),
                ('reason', models.TextField(blank=True, null=True, verbose_name='排除原因')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'verbose_name': '审计排除配置',
                'verbose_name_plural': '审计排除配置',
                'db_table': 'core_audit_exclude',
                'unique_together': {('app_label', 'model_name')},
            },
        ),
    ]
