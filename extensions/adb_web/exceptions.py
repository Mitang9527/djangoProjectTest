from rest_framework.exceptions import APIException


class AdbError(APIException):
    status_code = 503
    default_detail = "ADB 服务不可用"
    default_code = "adb_error"


class AdbDeviceNotFound(AdbError):
    status_code = 404
    default_detail = "未找到可用设备"
    default_code = "device_not_found"


class AdbOperationError(AdbError):
    status_code = 400
    default_detail = "ADB 操作失败"
    default_code = "adb_operation_failed"
