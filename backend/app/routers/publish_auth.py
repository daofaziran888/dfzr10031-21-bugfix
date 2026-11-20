"""发布授权预检接口。

覆盖：数据域/分组/许可/签收清单查询、发布预检、签收发布、许可撤回、
组外访问核验（撤回后组合统计读取 + 旧签收回查）、用户组消费范围、
解除共享后再次申请的上次批准层级回查。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.services.publish_auth import PublishAuthService

router = APIRouter(prefix="/api/publish_auth", tags=["发布授权预检"])

service = PublishAuthService()


class PrecheckPayload(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)


@router.get("/domains")
def list_domains() -> dict[str, Any]:
    """看板各图表引用的数据域清单（含归属团队）。"""
    return {"module": "data_domain", "items": service.list_domains()}


@router.get("/groups")
def list_groups() -> dict[str, Any]:
    """可消费看板发布内容的用户组（区分组内共享与合作方共享）。"""
    return {"module": "publish_group", "items": service.list_groups()}


@router.get("/licenses")
def list_licenses(domain: str | None = None, group_id: str | None = None,
                  status: str | None = None) -> dict[str, Any]:
    """来源许可清单，可按数据域、授权分组、许可状态过滤。"""
    items = service.list_licenses(domain=domain, group_id=group_id, status=status)
    return {"module": "publish_license", "total": len(items), "items": items}


@router.get("/signoffs")
def list_signoffs(group_id: str | None = None, dashboard_no: str | None = None) -> dict[str, Any]:
    """已签收发布记录，只追加不改写，撤回后仍可回查。"""
    items = service.list_signoffs(group_id=group_id, dashboard_no=dashboard_no)
    return {"module": "publish_signoff", "total": len(items), "items": items}


@router.post("/precheck")
def precheck(payload: PrecheckPayload) -> dict[str, Any]:
    """发布授权预检：按授权交集核算组合看板对请求分组的有效级别与发布方式。"""
    result, errors = service.precheck(payload.values)
    if result is None:
        return {"ok": False, "message": f"预检参数缺失或无效：{'、'.join(errors)}"}
    return {"ok": True, "message": "预检完成", "result": result}


@router.post("/signoffs")
def create_signoff(payload: PrecheckPayload) -> dict[str, Any]:
    """按预检结论签收发布；硬阻断时只允许按数据域独立交付。"""
    record, errors = service.create_signoff(payload.values)
    if record is None:
        return {"ok": False, "message": f"签收失败：{'、'.join(errors)}"}
    return {"ok": True, "message": "发布已签收", "entry": record}


@router.post("/licenses/{license_id}/revoke")
def revoke_license(license_id: int, payload: PrecheckPayload) -> dict[str, Any]:
    """撤回一项来源许可；撤回结果在后续预检中显式阻断、不得被组合看板隐藏。"""
    reason = str(payload.values.get("撤回原因") or "")
    entry, message = service.revoke_license(license_id, reason)
    if entry is None:
        return {"ok": False, "message": message}
    return {"ok": True, "message": message, "entry": entry}


@router.post("/verify")
def verify_access(payload: PrecheckPayload) -> dict[str, Any]:
    """用同一组外账户验证撤回后组合统计能否读取，并回查旧签收依据。"""
    result, errors = service.verify_access(payload.values)
    if result is None:
        return {"ok": False, "message": f"核验参数缺失：{'、'.join(errors)}"}
    return {"ok": True, "message": "访问核验完成", "result": result}


@router.get("/groups/{group_id}/consumption")
def group_consumption(group_id: str) -> dict[str, Any]:
    """用户组消费看板发布访问范围：可接收的只读页面与汇总数据范围。"""
    return service.group_consumption(group_id)


@router.get("/groups/{group_id}/last_approval")
def last_approval(group_id: str, dashboard_no: str) -> dict[str, Any]:
    """解除共享后再次申请：回查上次批准的数据层级与发布方式。"""
    return service.last_approved_level(group_id, dashboard_no)
