# -*- coding: utf-8 -*-
"""关键词过滤工具：职位标题/描述/要求命中配置的关键词时直接跳过，不调用 AI 模型"""
import re

# 支持分隔符：换行、英文逗号、中文逗号、分号
_SEP_RE = re.compile(r"[\n,，;；]")


def split_keywords(raw):
    """把配置的过滤关键词字符串拆成列表（去掉空项）"""
    if not raw:
        return []
    return [k.strip() for k in _SEP_RE.split(str(raw)) if k and k.strip()]


def match_filter_keyword(keywords, job_info):
    """判断职位标题/描述/要求是否命中任一过滤关键词

    Args:
        keywords: 关键词列表
        job_info: 职位信息 dict

    Returns:
        命中时返回命中的关键词；未命中或未配置返回 None
    """
    if not keywords:
        return None
    texts = [
        job_info.get('title', ''),
        job_info.get('description', ''),
        job_info.get('requirements', ''),
    ]
    combined = "\n".join(t for t in texts if t)
    if not combined:
        return None
    for kw in keywords:
        if kw in combined:
            return kw
    return None
