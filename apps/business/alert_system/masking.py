import re
import json
from typing import Any, Dict, List, Union
from loguru import logger


class DataMasker:
    """数据脱敏工具类"""

    MOBILE_PATTERN = re.compile(r'1[3-9]\d{9}')
    EMAIL_PATTERN = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')
    ID_CARD_PATTERN = re.compile(r'[1-9]\d{5}(18|19|20)\d{2}(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])\d{3}[\dXx]')
    BANK_CARD_PATTERN = re.compile(r'\d{16,19}')
    IP_PATTERN = re.compile(r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}')

    MOBILE_REPLACEMENT = r'1****\2'
    EMAIL_REPLACEMENT = lambda m: m.group(0)[:2] + '****@' + m.group(0).split('@')[1]
    ID_CARD_REPLACEMENT = r'\1********\2'
    BANK_CARD_REPLACEMENT = lambda m: m.group(0)[:4] + '****' + m.group(0)[-4:]
    IP_REPLACEMENT = lambda m: '.'.join(m.group(0).split('.')[:2]) + '.***.***'

    @classmethod
    def mask_mobile(cls, text: str) -> str:
        """脱敏手机号：138****1234"""
        return cls.MOBILE_PATTERN.sub(lambda m: m.group(0)[:3] + '****' + m.group(0)[7:], text)

    @classmethod
    def mask_email(cls, text: str) -> str:
        """脱敏邮箱：te****@example.com"""
        return cls.EMAIL_PATTERN.sub(lambda m: m.group(0)[:2] + '****@' + m.group(0).split('@')[1], text)

    @classmethod
    def mask_id_card(cls, text: str) -> str:
        """脱敏身份证：110***********1234"""
        return cls.ID_CARD_PATTERN.sub(lambda m: m.group(0)[:6] + '********' + m.group(0)[14:], text)

    @classmethod
    def mask_bank_card(cls, text: str) -> str:
        """脱敏银行卡：6222****1234"""
        return cls.BANK_CARD_PATTERN.sub(lambda m: m.group(0)[:4] + '****' + m.group(0)[-4:], text)

    @classmethod
    def mask_ip(cls, text: str) -> str:
        """脱敏IP地址：192.168.***.***"""
        return cls.IP_PATTERN.sub(lambda m: '.'.join(m.group(0).split('.')[:2]) + '.***.***', text)

    @classmethod
    def mask_all(cls, text: str) -> str:
        """对文本进行所有类型的脱敏"""
        if not text or not isinstance(text, str):
            return text

        text = cls.mask_mobile(text)
        text = cls.mask_email(text)
        text = cls.mask_id_card(text)
        text = cls.mask_bank_card(text)
        text = cls.mask_ip(text)
        return text

    @classmethod
    def mask_dict(cls, data: Dict[str, Any], fields: List[str] = None) -> Dict[str, Any]:
        """
        对字典进行脱敏
        :param data: 字典数据
        :param fields: 指定要脱敏的字段列表，None则对所有可能包含敏感信息的值进行脱敏
        """
        if not data:
            return data

        result = data.copy()

        def _process_value(value: Any) -> Any:
            if isinstance(value, str):
                return cls.mask_all(value)
            elif isinstance(value, dict):
                return cls.mask_dict(value, fields)
            elif isinstance(value, list):
                return [_process_value(item) for item in value]
            else:
                return value

        if fields:
            for field in fields:
                if field in result:
                    result[field] = _process_value(result[field])
        else:
            for key, value in result.items():
                result[key] = _process_value(value)

        return result

    @classmethod
    def mask_json(cls, json_str: str) -> str:
        """对JSON字符串进行脱敏"""
        try:
            data = json.loads(json_str)
            masked = cls.mask_dict(data)
            return json.dumps(masked, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"JSON脱敏失败: {e}")
            return cls.mask_all(json_str)


def mask_data(data: Union[str, Dict, List, Any]) -> Union[str, Dict, List, Any]:
    """
    通用数据脱敏函数
    """
    if isinstance(data, str):
        return DataMasker.mask_all(data)
    elif isinstance(data, dict):
        return DataMasker.mask_dict(data)
    elif isinstance(data, list):
        return [mask_data(item) for item in data]
    else:
        return data
