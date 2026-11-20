"""HTTP 层验证：在无 FastAPI 的离线环境用最小 shim 导入真实 router。

不 mock 业务逻辑，只替身 FastAPI/ Pydantic 外壳，确保：
 - router 能被真实导入、所有端点都已注册；
 - 端点函数能正常调用并返回正确的 JSON 结构；
 - 撤回 → 预检 → 访问核验 的完整链路在 HTTP 入口同样成立。
运行：python3 -I verify_publish_auth_http.py
"""
from __future__ import annotations

import sys
import types

sys.path.insert(0, "/workspace/backend")

# ---------------------------------------------------------------- 最小 FastAPI shim
fastapi = types.ModuleType("fastapi")


class APIRouter:
    def __init__(self, prefix: str = "", tags: list[str] | None = None) -> None:
        self.prefix = prefix
        self.routes: list[dict[str, object]] = []

    def _register(self, method: str, path: str):
        def deco(func):
            self.routes.append({"method": method, "path": path, "func": func})
            return func
        return deco

    def get(self, path: str, *args: object, **kwargs: object):
        return self._register("GET", path)

    def post(self, path: str, *args: object, **kwargs: object):
        return self._register("POST", path)


class HTTPException(Exception):
    def __init__(self, status_code: int, detail: str = "") -> None:
        self.status_code = status_code
        self.detail = detail


class QueryDefault:
    def __init__(self, default: object | None = None, description: str = "") -> None:
        self.default = default


def Query(default: object | None = None, description: str = "") -> object:  # noqa: N802
    return QueryDefault(default, description)


class Request:  # noqa: D401 - 仅占位，真实项目由 FastAPI 提供
    pass


fastapi.APIRouter = APIRouter
fastapi.HTTPException = HTTPException
fastapi.Query = Query
fastapi.Request = Request
sys.modules["fastapi"] = fastapi

pydantic = types.ModuleType("pydantic")


class BaseModel:
    def __init__(self, **kwargs: object) -> None:
        for key, value in kwargs.items():
            setattr(self, key, value)


def Field(default_factory=None, default=None):  # noqa: N802
    if default_factory is not None:
        return default_factory()
    return default


pydantic.BaseModel = BaseModel
pydantic.Field = Field
sys.modules["pydantic"] = pydantic

# ---------------------------------------------------------------- 导入真实 router
from app.routers import publish_auth as router_module  # noqa: E402

router = router_module.router
service = router_module.service

_passed = 0
_failed: list[str] = []


def check(name: str, condition: bool, detail: object = "") -> None:
    global _passed
    if condition:
        _passed += 1
        print(f"  [PASS] {name}")
    else:
        _failed.append(f"{name} {detail}")
        print(f"  [FAIL] {name} {detail}")


def find_route(method: str, suffix: str):
    for route in router.routes:
        if route["method"] == method and str(route["path"]).endswith(suffix):
            return route["func"]
    return None


print("== HTTP 层：路由注册 ==")
expected = [
    ("GET", "/domains"), ("GET", "/groups"), ("GET", "/licenses"), ("GET", "/signoffs"),
    ("POST", "/precheck"), ("POST", "/signoffs"), ("POST", "/revoke"),
    ("POST", "/verify"), ("GET", "/consumption"), ("GET", "/last_approval"),
]
for method, suffix in expected:
    check(f"已注册 {method} *{suffix}", find_route(method, suffix) is not None)
check("路由前缀正确", router.prefix == "/api/publish_auth", router.prefix)

print("== HTTP 层：GET 清单结构 ==")
domains_resp = find_route("GET", "/domains")()
check("数据域返回 2 条", len(domains_resp["items"]) == 2, len(domains_resp["items"]))
licenses_resp = find_route("GET", "/licenses")(None, None, None)
check("许可清单返回 6 条", licenses_resp["total"] == 6, licenses_resp["total"])
filtered = find_route("GET", "/licenses")("DOMAIN-RISK", None, None)
check("按数据域过滤生效", all(i["数据域编号"] == "DOMAIN-RISK" for i in filtered["items"]))

print("== HTTP 层：预检 → 签收 → 撤回 → 再核验 完整链路 ==")
precheck_func = find_route("POST", "/precheck")
signoff_func = find_route("POST", "/signoffs")
revoke_func = None
for route in router.routes:
    if route["method"] == "POST" and "{license_id}" in str(route["path"]):
        revoke_func = route["func"]
verify_func = find_route("POST", "/verify")

payload = router_module.PrecheckPayload(values={
    "看板编号": "DASH-COMBO-01",
    "请求人分组编号": "GROUP-PARTNER-A",
    "核对日期": "2026-11-20",
    "请求汇总级别": "明细",
    "数据域": [
        {"数据域编号": "DOMAIN-ORDER", "请求汇总级别": "明细"},
        {"数据域编号": "DOMAIN-RISK", "请求汇总级别": "明细"},
    ],
})
pre = precheck_func(payload)
check("预检接口 ok=true", pre["ok"] is True)
check("预检组合级别=地区级汇总", pre["result"]["组合有效汇总级别"] == "地区级汇总",
      pre["result"]["组合有效汇总级别"])

sign_payload = router_module.PrecheckPayload(values=dict(payload.values))
sign = signoff_func(sign_payload)
check("签收接口 ok=true 且返回签收编号", sign["ok"] and sign["entry"]["签收编号"].startswith("SIGN-"))

# 参数缺失走 ok=false 分支（不抛异常）
bad = precheck_func(router_module.PrecheckPayload(values={"看板编号": "X"}))
check("预检参数缺失返回 ok=false 与可读信息", bad["ok"] is False and "预检参数" in bad["message"])

revoked = revoke_func(2, router_module.PrecheckPayload(values={"撤回原因": "HTTP 链路撤回验证"}))
check("撤回接口 ok=true", revoked["ok"] and revoked["entry"]["许可状态"] == "已撤回")

post = precheck_func(payload)
check("撤回后预检仍返回结果不隐藏", post["ok"] is True)
check("撤回后组合级别=无", post["result"]["组合有效汇总级别"] == "无")
check("撤回后裁决独立交付", post["result"]["建议发布方式"] == "收回组合页并按数据域独立交付")

# 撤回后强制组合页签收应被拒绝
combo_sign = signoff_func(router_module.PrecheckPayload(
    values={**dict(payload.values), "发布方式": "组合页降级到双方共同许可粒度"}))
check("组合页签收被接口拒绝", combo_sign["ok"] is False and "硬阻断" in combo_sign["message"],
      combo_sign.get("message"))

verify = verify_func(router_module.PrecheckPayload(values={
    "请求人分组编号": "GROUP-PARTNER-A",
    "数据域编号": "DOMAIN-ORDER",
    "请求汇总级别": "明细",
    "核对日期": "2026-11-20",
}))
check("访问核验接口返回拒绝读取", verify["result"]["读取结论"] == "拒绝读取")
check("访问核验带旧签收依据", len(verify["result"]["旧签收依据"]) >= 1)

consume_func = find_route("GET", "/consumption")
consume = consume_func("GROUP-ANALYST")
check("消费范围接口返回组内分析组", consume["授权分组编号"] == "GROUP-ANALYST")
check("消费范围含两个数据域", len(consume["各数据域消费范围"]) == 2)

last_func = find_route("GET", "/last_approval")
last = last_func("GROUP-PARTNER-A", "DASH-COMBO-01")
check("上次批准回查接口有历史", last["是否有历史签收"] is True)

print()
print(f"通过 {_passed} 项，失败 {len(_failed)} 项")
if _failed:
    for item in _failed:
        print("  -", item)
    sys.exit(1)
print("HTTP 层全部验证通过。")
