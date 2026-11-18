"""合箱（母单/子单）关系的归一化与裁决口径。

裁决：正式时效由母单统一承担。子单只作为母单正式单元的扫描证据，
不再单独产出路径、时效或赔付结论。这样同一组合只有一份正式结论，
既不会出现“母单待妥投、子单缺收件”的并行说法，也不会重复计赔。
"""
from app.errors import DomainError

RULING = "正式时效由母单统一承担；子单只保留扫描证据，不单独结算"


def _identifier(value, field):
    if not isinstance(value, str) or not value.strip():
        raise DomainError("BAD_COMBOS", f"{field}需要非空文本")
    return value.strip()


def _child_list(value):
    if isinstance(value, str):
        value = value.replace("，", ",").split(",")
    if not isinstance(value, (list, tuple, set)):
        raise DomainError("BAD_COMBOS", "子单需要文本或文本列表")
    children = []
    for item in value:
        child = _identifier(item, "子单")
        if child not in children:
            children.append(child)
    if not children:
        raise DomainError("BAD_COMBOS", "每个母单至少需要一个子单")
    return children


def _declaration(item):
    if isinstance(item, str):
        if ":" not in item:
            raise DomainError("BAD_COMBOS", "文本关系需要“母单:子单”格式")
        parent, children = item.split(":", 1)
        return _identifier(parent, "母单"), _child_list(children)
    if not isinstance(item, dict):
        raise DomainError("BAD_COMBOS", "合箱关系需要对象或“母单:子单”文本")
    if not any(key in item for key in ("parent","parent_id","mother","children","child_ids","child","members")):
        if len(item)!=1:
            raise DomainError("BAD_COMBOS", "对象关系需要母单与子单字段")
        key, value = next(iter(item.items()))
        return _declaration({"parent": key, "children": [value] if isinstance(value, str) else value})
    parent = item.get("parent", item.get("parent_id", item.get("mother")))
    children = item.get("children", item.get("child_ids", item.get("child", item.get("members"))))
    if children is None:
        raise DomainError("BAD_COMBOS", "母单需要子单")
    return _identifier(parent, "母单"), _child_list(children)


def normalize(declarations):
    """把各种合箱声明归一为按母单排序的 [{parent, children}]。

    支持：
    - [{"parent": "M1", "children": ["C1", "C2"]}]
    - [{"parent": "M1", "child": "C1"}]
    - ["M1:C1,C2"]
    - {"M1": ["C1", "C2"]}（键为母单）
    - {"C1": "M1"}（值为标量时，视为子单→母单）
    """
    if declarations in (None, "", []):
        return []
    if isinstance(declarations, str):
        declarations = [line.strip() for line in declarations.replace("，", ",").splitlines() if line.strip()]
    if isinstance(declarations, dict):
        if not declarations:
            return []
        if all(isinstance(value, str) for value in declarations.values()):
            declarations = [{"parent": parent, "child": child} for child, parent in declarations.items()]
        else:
            declarations = [{"parent": parent, "children": children} for parent, children in declarations.items()]
    if not isinstance(declarations, (list, tuple)):
        raise DomainError("BAD_COMBOS", "合箱关系需要列表或对象")

    merged = {}
    for item in declarations:
        parent, children = _declaration(item)
        merged.setdefault(parent, [])
        for child in children:
            if child not in merged[parent]:
                merged[parent].append(child)

    parents = set(merged)
    owners = {}
    for parent, children in merged.items():
        for child in children:
            if child == parent:
                raise DomainError("BAD_COMBOS", f"母单 {parent} 不能同时是子单")
            if child in parents:
                raise DomainError("BAD_COMBOS", f"子单 {child} 不能同时是母单")
            if child in owners and owners[child] != parent:
                raise DomainError("BAD_COMBOS", f"子单 {child} 同时属于 {owners[child]} 与 {parent}")
            owners[child] = parent

    return [
        {"parent": parent, "children": sorted(children)}
        for parent, children in sorted(merged.items())
    ]


def canonical_parameters(parameters=None):
    """返回可参与摘要计算的参数副本，保证同一组合换顺序/换写法仍是同一批。"""
    canonical = dict(parameters or {})
    if "combos" in canonical:
        combos = normalize(canonical["combos"])
        if combos:
            canonical["combos"] = combos
        else:
            canonical.pop("combos")
    return canonical


def parse_form(text):
    """解析上传表单里的合箱关系：JSON 或每行一条“母单:子单,子单”。

    关系常在起运后才补，因此允许与扫描文件分开提交；空值表示本批没有合箱。
    """
    if text is None or not str(text).strip():
        return {}
    raw = str(text).strip()
    if raw[0] in "[{":
        import json

        return {"combos": json.loads(raw)}
    lines = [line.strip().lstrip("﻿") for line in raw.splitlines()]
    return {"combos": [line for line in lines if line and not line.startswith("#")]}
