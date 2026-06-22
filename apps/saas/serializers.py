"""
SaaS 后台管理系统 - API 序列化器
"""
from rest_framework import serializers
from .models import (
    Plan,
    PlanFeature,
    Tenant,
    TenantSubscription,
    TenantConfig,
    Permission,
    Role,
    TenantMember,
    Order,
    Invoice
)


class PlanSerializer(serializers.ModelSerializer):
    class Meta:
        model = Plan
        fields = '__all__'
        read_only_fields = ['id', 'created_at', 'updated_at']


class PlanFeatureSerializer(serializers.ModelSerializer):
    class Meta:
        model = PlanFeature
        fields = '__all__'
        read_only_fields = ['id', 'created_at']


class TenantSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tenant
        fields = '__all__'
        read_only_fields = ['id', 'created_by', 'created_at', 'updated_at']


class TenantSubscriptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = TenantSubscription
        fields = '__all__'
        read_only_fields = ['id', 'created_at', 'updated_at']


class TenantConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = TenantConfig
        fields = '__all__'
        read_only_fields = ['id', 'created_at', 'updated_at']


class PermissionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Permission
        fields = '__all__'
        read_only_fields = ['id', 'created_at']


class RoleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Role
        fields = '__all__'
        read_only_fields = ['id', 'created_at', 'updated_at']


class TenantMemberSerializer(serializers.ModelSerializer):
    class Meta:
        model = TenantMember
        fields = '__all__'
        read_only_fields = ['id', 'joined_at']


class OrderSerializer(serializers.ModelSerializer):
    class Meta:
        model = Order
        fields = '__all__'
        read_only_fields = ['id', 'order_number', 'created_at', 'updated_at']


class InvoiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Invoice
        fields = '__all__'
        read_only_fields = ['id', 'invoice_number', 'created_at', 'updated_at']
