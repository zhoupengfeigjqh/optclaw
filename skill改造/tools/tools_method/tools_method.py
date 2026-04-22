"""工具函数
"""
import json


def get_temperature(**kwargs):
    """获取温度
    """
    obj_list = kwargs.get('city_list')

    ret_list = []
    
    for item in obj_list:
        ret_list.append(f'{item}温度为18度')

    return json.dumps(ret_list, indent=2, ensure_ascii=False)


def get_moisture(**kwargs):
    """获取湿度
    """
    obj_list = kwargs.get('city_list')

    ret_list = []
    
    for item in obj_list:
        ret_list.append(f'{item}湿度为18度')

    return json.dumps(ret_list, indent=2, ensure_ascii=False)


def get_population(**kwargs):
    """获取人口
    """
    obj_list = kwargs.get('obj_list')

    ret_list = []
    
    for item in obj_list:
        ret_list.append(f'{item.get('city')}-{item.get('year')}人口为1500w')

    return json.dumps(ret_list, indent=2, ensure_ascii=False)