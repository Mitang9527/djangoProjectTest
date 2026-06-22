from rest_framework.renderers import JSONRenderer

class CustomRenderer(JSONRenderer):
    """
    统一全局响应格式渲染器
    """
    def render(self, data, accepted_media_type=None, renderer_context=None):
        response = renderer_context.get('response')
        
        # 默认响应结构
        code = response.status_code
        msg = 'success'
        
        # 处理异常情况（由自定义异常处理器或 DRF 抛出的错误）
        if code >= 400:
            msg = 'error'
            if isinstance(data, dict):
                # 如果有 detail 字段，将其作为消息
                msg = data.get('detail', data.get('message', '请求失败'))
                # 如果是表单验证错误，通常 data 会包含具体字段的错误列表
                if code == 400 and not data.get('detail'):
                    msg = '参数验证失败'
        
        # 如果视图中已经返回了带 code/msg 的结构，则不再包装
        if isinstance(data, dict) and ('code' in data and 'msg' in data):
            res_data = data
        else:
            # 统一包装结构
            res_data = {
                'code': code,
                'msg': msg,
                'data': data
            }

        return super().render(res_data, accepted_media_type, renderer_context)
