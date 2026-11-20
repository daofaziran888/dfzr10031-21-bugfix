"""发布授权预检业务规则。

这里把多数据来源看板的发布授权核算集中在一处，关键口径如下：

1. 一条明细的发布权限只到该行所需全部授权的「交集」——多数据域组合时，
   组合看板的有效级别取各数据域有效级别的最小值，任何一域不达标都要降级或拒绝。
2. 不同团队对同一数据域的许可彼此独立：A 团队拿到的许可不能当成 B 团队的全部
   许可，核算只采用「来源团队 → 请求人分组」这一条链路真正命中的许可。
3. 最终判定同时检查来源许可（级别/期限/范围/状态）与请求人分组（是否属于
   来源团队的组内共享范围或合作方共享范围）。
4. 被撤回（revoke）的许可必须在结果里显式体现，组合看板不得把撤回结果藏起来：
   撤回许可命中即记为阻断项；只有另一条独立、未撤回且同样覆盖该域与该分组的
   许可存在时，才允许放行，但撤回痕迹仍随结果返回。
5. 组外（合作方）发布给出两种方式并给出裁决：能降到共同粒度就降级交付组合页，
   任一数据域完全无许可则收回组合页、按域独立交付。
6. 签收记录只追加不改写；解除共享后再次申请可回查上次批准的数据层级，撤回后
   旧签收依据仍可回查，但新的读取请求按当前许可重新判定。
"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.store import store

MODULE = "publish_auth"
DOMAIN_MODULE = "data_domain"
GROUP_MODULE = "publish_group"
LICENSE_MODULE = "publish_license"
SIGNOFF_MODULE = "publish_signoff"

# 汇总级别从粗到细；rank 越大，可读取的数据层级越高（明细最细）。
LEVEL_ORDER = ["总量汇总", "地区级汇总", "明细"]
LEVEL_RANK = {level: index for index, level in enumerate(LEVEL_ORDER)}
NONE_LEVEL = "无"

SCOPE_TEAM = "组内共享"
SCOPE_PARTNER = "合作方共享"

STATUS_ACTIVE = "生效中"
STATUS_REVOKED = "已撤回"


def _today() -> date:
    return date.today()


def _parse_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def min_level(levels: list[str]) -> str:
    """取一组级别里的最低粒度（授权交集）。

    交集里只要出现一个「无」，整体就是「无」——不能把缺失的授权静默丢掉。
    """
    if any(level == NONE_LEVEL for level in levels):
        return NONE_LEVEL
    valid = [level for level in levels if level in LEVEL_RANK]
    if not valid:
        return NONE_LEVEL
    return min(valid, key=lambda level: LEVEL_RANK[level])


class PublishAuthService:
    # ------------------------------------------------------------------ 基础读取
    def list_licenses(self, *, domain: str | None = None, group_id: str | None = None,
                      status: str | None = None) -> list[dict[str, Any]]:
        rows = store.rows(LICENSE_MODULE)
        if domain:
            rows = [row for row in rows if row.get("数据域编号") == domain]
        if group_id:
            rows = [row for row in rows if row.get("授权分组编号") == group_id]
        if status:
            rows = [row for row in rows if row.get("许可状态") == status]
        return rows

    def list_domains(self) -> list[dict[str, Any]]:
        return store.rows(DOMAIN_MODULE)

    def list_groups(self) -> list[dict[str, Any]]:
        return store.rows(GROUP_MODULE)

    def list_signoffs(self, *, group_id: str | None = None,
                      dashboard_no: str | None = None) -> list[dict[str, Any]]:
        rows = store.rows(SIGNOFF_MODULE)
        if group_id:
            rows = [row for row in rows if row.get("授权分组编号") == group_id]
        if dashboard_no:
            rows = [row for row in rows if row.get("看板编号") == dashboard_no]
        return rows

    def _get_group(self, group_id: str) -> dict[str, Any] | None:
        for row in store.rows(GROUP_MODULE):
            if row.get("组编号") == group_id:
                return row
        return None

    def _get_domain(self, domain_id: str) -> dict[str, Any] | None:
        for row in store.rows(DOMAIN_MODULE):
            if row.get("数据域编号") == domain_id:
                return row
        return None

    def _get_license(self, license_id: int) -> dict[str, Any] | None:
        return store.find(LICENSE_MODULE, license_id)

    # ------------------------------------------------------------------ 许可维护
    def revoke_license(self, license_id: int, reason: str) -> tuple[dict[str, Any] | None, str]:
        license_row = self._get_license(license_id)
        if license_row is None:
            return None, f"许可 {license_id} 不存在"
        if license_row["许可状态"] == STATUS_REVOKED:
            return license_row, "该许可此前已撤回，本次重复撤回不改变结果"
        license_row["许可状态"] = STATUS_REVOKED
        license_row["撤回原因"] = reason or "发布授权预检撤回"
        license_row["撤回时间"] = _today().isoformat()
        license_row["abnormal"] = True
        return license_row, "许可已撤回，组合看板再次预检时该来源将显式阻断"

    # ------------------------------------------------------------------ 单条命中
    def _license_matches_group(self, license_row: dict[str, Any], group: dict[str, Any]) -> bool:
        """判断一条许可的共享范围是否覆盖请求人分组。

        组内共享只覆盖来源团队本团队的分组；合作方共享只覆盖被授权的合作方分组。
        不同团队的许可不会被当成全部许可。
        """
        scope = license_row.get("共享范围")
        if scope == SCOPE_TEAM:
            return group.get("所属团队") == license_row.get("来源团队")
        if scope == SCOPE_PARTNER:
            return license_row.get("授权分组编号") == group.get("组编号")
        return False

    def _evaluate_license(self, license_row: dict[str, Any], on_date: date) -> dict[str, Any]:
        start = _parse_date(license_row.get("许可开始日期"))
        end = _parse_date(license_row.get("许可结束日期"))
        if license_row.get("许可状态") == STATUS_REVOKED:
            state, usable = "已撤回", False
        elif start and on_date < start:
            state, usable = "未生效", False
        elif end and on_date > end:
            state, usable = "已过期", False
        else:
            state, usable = "生效覆盖", True
        return {
            "许可编号": license_row.get("许可编号"),
            "来源团队": license_row.get("来源团队"),
            "共享范围": license_row.get("共享范围"),
            "授权分组编号": license_row.get("授权分组编号"),
            "最高汇总级别": license_row.get("最高汇总级别"),
            "许可开始日期": license_row.get("许可开始日期"),
            "许可结束日期": license_row.get("许可结束日期"),
            "许可状态": license_row.get("许可状态"),
            "命中情况": state,
            "是否可用": usable,
        }

    def evaluate_domain(self, domain_id: str, group: dict[str, Any], on_date: date) -> dict[str, Any]:
        """核算单个数据域对某个分组在指定日期的有效授权。

        关键口径：数据域的有效汇总级别只由「域归属团队」且范围命中该分组的
        许可链决定；其他团队对同一数据域的许可独立评估、仅留痕展示，既不抬升
        也不拉低归属团队的定级——不同团队的许可不会被当成该域的全部许可。
        （多数据域之间的授权交集在 precheck 层取 min_level。）
        """
        domain = self._get_domain(domain_id)
        owner_team = (domain or {}).get("归属团队")
        candidates = [
            row for row in store.rows(LICENSE_MODULE)
            if row.get("数据域编号") == domain_id and self._license_matches_group(row, group)
        ]
        evaluations = [self._evaluate_license(row, on_date) for row in candidates]

        owner_evals = [item for item in evaluations if item["来源团队"] == owner_team]
        other_evals = [item for item in evaluations if item["来源团队"] != owner_team]
        owner_revoked = [item for item in owner_evals if item["命中情况"] == "已撤回"]
        owner_usable = [item for item in owner_evals if item["是否可用"]]
        effective = min_level([item["最高汇总级别"] for item in owner_usable]) if owner_usable else NONE_LEVEL

        blockers: list[str] = []
        if not candidates:
            blockers.append("该分组在本数据域没有任何来源许可（组内/合作方范围均未命中）")
        elif not owner_evals:
            blockers.append(
                f"命中的许可全部来自非归属团队（{('、'.join(sorted({i['来源团队'] for i in other_evals})))}），"
                f"不能当成数据域归属团队「{owner_team}」的全部许可"
            )
        elif owner_revoked and not owner_usable:
            blockers.append("归属团队的命中许可已撤回且无其他独立有效许可，组合看板不得隐藏该撤回结果")
        elif owner_revoked:
            blockers.append(
                f"归属团队存在已撤回许可 {('、'.join(item['许可编号'] for item in owner_revoked))}，"
                "当前由归属团队其他独立有效许可覆盖，撤回仍留痕"
            )
        elif owner_evals and not owner_usable:
            blockers.append("归属团队命中的许可均不在合作方允许的起止日期内（未生效或已过期）")

        return {
            "数据域编号": domain_id,
            "数据域名称": (domain or {}).get("数据域名称"),
            "归属团队": owner_team,
            "有效汇总级别": effective,
            "是否存在撤回": any(item["命中情况"] == "已撤回" for item in evaluations),
            "归属团队命中许可": owner_evals,
            "非归属团队许可留痕": other_evals,
            "阻断原因": blockers,
            "命中许可明细": evaluations,
        }

    # ------------------------------------------------------------------ 发布预检
    def precheck(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        dashboard_no = str(values.get("看板编号") or "").strip()
        group_id = str(values.get("请求人分组编号") or "").strip()
        domains = values.get("数据域") or []
        if not dashboard_no or not group_id:
            return None, ["看板编号", "请求人分组编号"]
        if not isinstance(domains, list) or not domains:
            return None, ["数据域（至少一个数据域及其请求级别）"]

        group = self._get_group(group_id)
        if group is None:
            return None, [f"请求人分组 {group_id} 不存在"]

        on_date = _parse_date(values.get("核对日期")) or _today()
        requested_default = values.get("请求汇总级别") or "明细"

        domain_results: list[dict[str, Any]] = []
        for item in domains:
            domain_id = str(item.get("数据域编号") or "").strip()
            requested = item.get("请求汇总级别") or requested_default
            if not domain_id or self._get_domain(domain_id) is None:
                return None, [f"数据域 {domain_id or '(空)'} 不存在"]
            result = self.evaluate_domain(domain_id, group, on_date)
            result["请求汇总级别"] = requested
            result["该域是否满足请求"] = (
                requested in LEVEL_RANK
                and result["有效汇总级别"] in LEVEL_RANK
                and LEVEL_RANK[result["有效汇总级别"]] >= LEVEL_RANK[requested]
            )
            domain_results.append(result)

        # 交集：组合看板的有效级别是各数据域有效级别的最小值。
        effective_levels = [item["有效汇总级别"] for item in domain_results]
        combined_level = min_level(effective_levels)
        any_revoked = any(item["是否存在撤回"] for item in domain_results)
        hard_blocked = any(item["有效汇总级别"] == NONE_LEVEL for item in domain_results)
        requested_level = requested_default
        satisfies = (
            requested_level in LEVEL_RANK
            and combined_level in LEVEL_RANK
            and LEVEL_RANK[combined_level] >= LEVEL_RANK[requested_level]
        )

        is_partner = group.get("共享类型") == SCOPE_PARTNER
        recommendation = self._recommend_method(is_partner, hard_blocked, combined_level)

        return {
            "看板编号": dashboard_no,
            "请求人分组编号": group_id,
            "请求人分组名称": group.get("组名称"),
            "共享类型": group.get("共享类型"),
            "核对日期": on_date.isoformat(),
            "请求汇总级别": requested_level,
            "组合有效汇总级别": combined_level,
            "组合是否满足请求": satisfies,
            "是否存在撤回许可": any_revoked,
            "是否硬阻断": hard_blocked,
            "建议发布方式": recommendation["方式"],
            "建议说明": recommendation["说明"],
            "数据域核算": domain_results,
        }, []

    def _recommend_method(self, is_partner: bool, hard_blocked: bool, combined_level: str) -> dict[str, str]:
        if not is_partner:
            return {"方式": "组内按授权范围发布", "说明": "组内共享分组，按组合有效级别直接发布只读页面。"}
        if hard_blocked or combined_level == NONE_LEVEL:
            return {
                "方式": "收回组合页并按数据域独立交付",
                "说明": "存在数据域对该合作方无任何有效许可，组合页必须收回；各数据域仅交付自身允许的范围。",
            }
        return {
            "方式": "组合页降级到双方共同许可粒度",
            "说明": f"合作方仍持有共同粒度许可，组合页降级到「{combined_level}」交付，不暴露明细。",
        }

    # ------------------------------------------------------------------ 签收发布
    def create_signoff(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        precheck_result, errors = self.precheck(values)
        if precheck_result is None:
            return None, errors

        strategy = str(values.get("发布方式") or precheck_result["建议发布方式"]).strip()
        group_id = precheck_result["请求人分组编号"]
        dashboard_no = precheck_result["看板编号"]

        allowed = {"组合页降级到双方共同许可粒度", "收回组合页并按数据域独立交付", "组内按授权范围发布"}
        if strategy not in allowed:
            return None, [f"发布方式 {strategy} 不受支持"]

        domains = precheck_result["数据域核算"]
        delivered: list[dict[str, Any]] = []
        if strategy == "收回组合页并按数据域独立交付":
            for item in domains:
                delivered.append({
                    "数据域编号": item["数据域编号"],
                    "交付级别": item["有效汇总级别"] if item["有效汇总级别"] in LEVEL_RANK else NONE_LEVEL,
                    "交付形态": "独立页面",
                })
            combined_deliver_level = NONE_LEVEL
        else:
            # 组合（含降级）交付：所有数据域统一压到共同粒度。
            combined = precheck_result["组合有效汇总级别"]
            if combined not in LEVEL_RANK or precheck_result["是否硬阻断"]:
                return None, [
                    "组合有效级别为「无」或存在数据域硬阻断，不能以组合页发布，"
                    "请改用「收回组合页并按数据域独立交付」"
                ]
            for item in domains:
                delivered.append({"数据域编号": item["数据域编号"], "交付级别": combined, "交付形态": "组合只读页面"})
            combined_deliver_level = combined

        rows = store.rows(SIGNOFF_MODULE)
        record = {
            "id": max((int(row.get("id", 0)) for row in rows), default=0) + 1,
            "签收编号": f"SIGN-{max((int(row.get('id', 0)) for row in rows), default=0) + 1:04d}",
            "看板编号": dashboard_no,
            "授权分组编号": group_id,
            "授权分组名称": precheck_result["请求人分组名称"],
            "发布方式": strategy,
            "组合交付级别": combined_deliver_level,
            "各域交付范围": delivered,
            "组合有效汇总级别": precheck_result["组合有效汇总级别"],
            "请求汇总级别": precheck_result["请求汇总级别"],
            "是否含撤回许可": precheck_result["是否存在撤回许可"],
            "签收时间": _today().isoformat(),
            "签收依据": self._build_basis(precheck_result),
            "签收状态": "已签收",
        }
        rows.append(record)
        return record, []

    def _build_basis(self, precheck_result: dict[str, Any]) -> list[dict[str, Any]]:
        basis: list[dict[str, Any]] = []
        for item in precheck_result["数据域核算"]:
            # 只把域归属团队的有效许可作为签收依据；非归属团队许可不参与定级。
            usable = [
                detail for detail in item.get("归属团队命中许可", [])
                if detail["是否可用"]
            ]
            basis.append({
                "数据域编号": item["数据域编号"],
                "归属团队": item["归属团队"],
                "有效汇总级别": item["有效汇总级别"],
                "依据许可": [detail["许可编号"] for detail in usable],
            })
        return basis

    def last_approved_level(self, group_id: str, dashboard_no: str) -> dict[str, Any]:
        """解除共享后再次申请：回查该分组对该看板上次批准的数据层级。"""
        history = [
            row for row in store.rows(SIGNOFF_MODULE)
            if row.get("授权分组编号") == group_id and row.get("看板编号") == dashboard_no
        ]
        if not history:
            return {"授权分组编号": group_id, "看板编号": dashboard_no, "是否有历史签收": False}
        last = history[-1]
        return {
            "授权分组编号": group_id,
            "看板编号": dashboard_no,
            "是否有历史签收": True,
            "上次签收编号": last["签收编号"],
            "上次批准组合级别": last["组合交付级别"],
            "上次发布方式": last["发布方式"],
            "上次各域交付范围": last["各域交付范围"],
            "上次签收时间": last["签收时间"],
        }

    # ------------------------------------------------------------------ 消费范围
    def group_consumption(self, group_id: str, on_date: date | None = None) -> dict[str, Any]:
        """用户组消费视角：按当前授权范围计算可接收的只读页面与汇总数据范围。"""
        group = self._get_group(group_id)
        if group is None:
            return {"授权分组编号": group_id, "存在": False}
        on_date = on_date or _today()
        domain_scopes: list[dict[str, Any]] = []
        for domain in store.rows(DOMAIN_MODULE):
            result = self.evaluate_domain(domain["数据域编号"], group, on_date)
            domain_scopes.append({
                "数据域编号": result["数据域编号"],
                "数据域名称": result["数据域名称"],
                "可读取最高级别": result["有效汇总级别"],
                "只读页面": self._page_for_level(result["有效汇总级别"]),
                "是否含撤回": result["是否存在撤回"],
            })
        effective = min_level([item["可读取最高级别"] for item in domain_scopes])
        return {
            "授权分组编号": group_id,
            "授权分组名称": group.get("组名称"),
            "共享类型": group.get("共享类型"),
            "核对日期": on_date.isoformat(),
            "组合只读页面": self._page_for_level(effective),
            "组合可接收最高级别": effective,
            "各数据域消费范围": domain_scopes,
        }

    @staticmethod
    def _page_for_level(level: str) -> str:
        if level == "明细":
            return "明细只读页 + 地区级汇总页 + 总量汇总页"
        if level == "地区级汇总":
            return "地区级汇总页 + 总量汇总页（明细页拒绝）"
        if level == "总量汇总":
            return "总量汇总页（明细与地区页拒绝）"
        return "无可接收页面（访问拒绝）"

    # ------------------------------------------------------------------ 访问核验
    def verify_access(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        """用同一组外账户验证撤回后组合统计能否读取，并回查旧签收依据。"""
        group_id = str(values.get("请求人分组编号") or "").strip()
        domain_id = str(values.get("数据域编号") or "").strip()
        level = str(values.get("请求汇总级别") or "").strip()
        if not group_id or not domain_id or not level:
            return None, ["请求人分组编号", "数据域编号", "请求汇总级别"]
        group = self._get_group(group_id)
        if group is None:
            return None, [f"请求人分组 {group_id} 不存在"]
        on_date = _parse_date(values.get("核对日期")) or _today()
        result = self.evaluate_domain(domain_id, group, on_date)
        allowed = (
            level in LEVEL_RANK
            and result["有效汇总级别"] in LEVEL_RANK
            and LEVEL_RANK[result["有效汇总级别"]] >= LEVEL_RANK[level]
        )
        signoff_basis = [
            {
                "签收编号": row["签收编号"],
                "看板编号": row["看板编号"],
                "组合交付级别": row["组合交付级别"],
                "发布方式": row["发布方式"],
                "签收时间": row["签收时间"],
                "签收依据": row["签收依据"],
            }
            for row in store.rows(SIGNOFF_MODULE)
            if row.get("授权分组编号") == group_id
        ]
        return {
            "请求人分组编号": group_id,
            "请求人分组名称": group.get("组名称"),
            "数据域编号": domain_id,
            "请求汇总级别": level,
            "核对日期": on_date.isoformat(),
            "读取结论": "允许读取" if allowed else "拒绝读取",
            "当前有效汇总级别": result["有效汇总级别"],
            "是否因撤回拒绝": result["是否存在撤回"] and not allowed,
            "阻断原因": result["阻断原因"],
            "命中许可明细": result["命中许可明细"],
            "旧签收依据": signoff_basis,
        }, []
