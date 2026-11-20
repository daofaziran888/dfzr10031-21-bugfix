"""发布授权预检的端到端规则验证脚本（只依赖标准库，离线可跑）。

运行：python3 -I verify_publish_auth.py
覆盖用户提出的全部核对点：
 1. 多数据域授权交集（组合有效级别取各域最小值）
 2. 不同团队对同一域的许可不得当成全部许可（组内/合作方范围隔离）
 3. 同时检查来源许可与请求人分组；起止日期窗口（过期不续命）
 4. 撤回许可在组合看板显式阻断、不得隐藏
 5. 组外两种发布方式的裁决：降级组合页 vs 收回组合页独立交付
 6. 用户组消费范围（只读页面 + 汇总数据范围）
 7. 同一组外账户验证撤回后组合统计拒绝读取，且旧签收依据可回查
 8. 两个组 + 两个数据域重叠期限，撤回一项后核对聚合可访问、明细拒绝、签收记录留存
"""
from __future__ import annotations

import sys

sys.path.insert(0, "/workspace/backend")

from app.services.publish_auth import (  # noqa: E402
    LEVEL_RANK,
    NONE_LEVEL,
    PublishAuthService,
)

CHECK_DATE = "2026-11-20"
NEXT_WEEK = "2026-11-25"
DASH = "DASH-COMBO-01"
ORDER = "DOMAIN-ORDER"
RISK = "DOMAIN-RISK"
ANALYST = "GROUP-ANALYST"
PARTNER = "GROUP-PARTNER-A"

service = PublishAuthService()
_passed = 0
_failed: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        global _passed
        _passed += 1
        print(f"  [PASS] {name}")
    else:
        _failed.append(f"{name} {detail}")
        print(f"  [FAIL] {name} {detail}")


def combo_payload(group: str, level: str = "明细", date: str = CHECK_DATE) -> dict:
    return {
        "看板编号": DASH,
        "请求人分组编号": group,
        "核对日期": date,
        "请求汇总级别": level,
        "数据域": [
            {"数据域编号": ORDER, "请求汇总级别": level},
            {"数据域编号": RISK, "请求汇总级别": level},
        ],
    }


def domain_of(result: dict, domain_id: str) -> dict:
    return next(item for item in result["数据域核算"] if item["数据域编号"] == domain_id)


print("== 场景1 撤回前：组外合作方组合看板预检，授权交集 + 发布方式裁决 ==")
pre, errs = service.precheck(combo_payload(PARTNER))
check("预检成功无错误", pre is not None, str(errs))
order_before = domain_of(pre, ORDER)
risk_before = domain_of(pre, RISK)
check("订单域合作方有效级别=地区级汇总", order_before["有效汇总级别"] == "地区级汇总",
      order_before["有效汇总级别"])
check("风控域合作方有效级别=明细（许可覆盖到下周之后）", risk_before["有效汇总级别"] == "明细",
      risk_before["有效汇总级别"])
check("组合有效级别取交集=地区级汇总", pre["组合有效汇总级别"] == "地区级汇总", pre["组合有效汇总级别"])
check("明细请求不被满足", pre["组合是否满足请求"] is False)
check("裁决=组合页降级到共同粒度", pre["建议发布方式"] == "组合页降级到双方共同许可粒度",
      pre["建议发布方式"])
check("过期的明细许可 LIC-0006 不续命",
      all(not d["是否可用"] for d in order_before["命中许可明细"] if d["许可编号"] == "LIC-0006"))
next_pre, next_errs = service.precheck(combo_payload(PARTNER, date=NEXT_WEEK))
check("下周核对日预检成功", next_pre is not None, str(next_errs))
check("下周核对日风控域仍覆盖明细",
      next_pre and domain_of(next_pre, RISK)["有效汇总级别"] == "明细")

print("== 场景2 组内分析组：跨团队许可隔离，不同团队许可不被当成全部许可 ==")
inside, errs = service.precheck(combo_payload(ANALYST))
check("组内预检成功", inside is not None, str(errs))
check("分析组订单域=明细(LIC-0001)", domain_of(inside, ORDER)["有效汇总级别"] == "明细")
check("分析组风控域=地区级汇总(LIC-0004)", domain_of(inside, RISK)["有效汇总级别"] == "地区级汇总",
      domain_of(inside, RISK)["有效汇总级别"])
risk_analyst = domain_of(inside, RISK)
check("合作方专属许可 LIC-0003/0005 不命中组内分组",
      all(d["许可编号"] not in ("LIC-0003", "LIC-0005") for d in risk_analyst["命中许可明细"]))
check("组内按授权范围发布", inside["建议发布方式"] == "组内按授权范围发布", inside["建议发布方式"])

print("== 场景3 按裁决签收：降级组合页（共同粒度 地区级汇总） ==")
sign, errs = service.create_signoff(combo_payload(PARTNER))
check("降级签收成功", sign is not None, str(errs))
check("签收组合交付级别=地区级汇总", sign and sign["组合交付级别"] == "地区级汇总")
check("两个数据域都以组合只读页面交付",
      sign and all(d["交付形态"] == "组合只读页面" and d["交付级别"] == "地区级汇总"
                   for d in sign["各域交付范围"]))
check("签收依据记录了命中的来源许可编号",
      sign and any(b["依据许可"] == ["LIC-0002"] for b in sign["签收依据"]))

print("== 场景4 撤回一项来源许可 LIC-0002（订单域合作方许可） ==")
lic, msg = service.revoke_license(2, "合作方共享范围调整，撤回订单域地区汇总许可")
check("撤回成功", lic is not None and lic["许可状态"] == "已撤回", msg)
again, _ = service.revoke_license(2, "重复撤回")
check("重复撤回幂等不报错", again is not None)

print("== 场景5 撤回后再预检：组合看板不得隐藏撤回，硬阻断并改判独立交付 ==")
post, errs = service.precheck(combo_payload(PARTNER))
check("撤回后预检仍成功返回（不隐藏结果）", post is not None, str(errs))
order_after = domain_of(post, ORDER)
risk_after = domain_of(post, RISK)
check("订单域有效级别降为无", order_after["有效汇总级别"] == NONE_LEVEL, order_after["有效汇总级别"])
check("订单域显式标记存在撤回", order_after["是否存在撤回"] is True)
check("阻断原因明确写出撤回且无替代许可", any("撤回" in b for b in order_after["阻断原因"]),
      str(order_after["阻断原因"]))
check("风控域许可到下周后仍覆盖明细", risk_after["有效汇总级别"] == "明细", risk_after["有效汇总级别"])
check("组合级别=无（硬阻断）", post["组合有效汇总级别"] == NONE_LEVEL and post["是否硬阻断"] is True)
check("整体标记存在撤回许可", post["是否存在撤回许可"] is True)
check("裁决=收回组合页并按数据域独立交付",
      post["建议发布方式"] == "收回组合页并按数据域独立交付", post["建议发布方式"])

print("== 场景6 撤回后禁止再发组合页，只允许独立交付 ==")
bad, errs = service.create_signoff({**combo_payload(PARTNER), "发布方式": "组合页降级到双方共同许可粒度"})
check("组合页发布被拒绝", bad is None, str(errs))
split, errs = service.create_signoff({**combo_payload(PARTNER), "发布方式": "收回组合页并按数据域独立交付"})
check("独立交付签收成功", split is not None, str(errs))
check("订单域独立交付级别=无（拒绝）",
      split and next(d for d in split["各域交付范围"] if d["数据域编号"] == ORDER)["交付级别"] == NONE_LEVEL)
check("风控域独立交付级别=明细（不受订单域撤回影响）",
      split and next(d for d in split["各域交付范围"] if d["数据域编号"] == RISK)["交付级别"] == "明细")
check("独立交付形态为独立页面", split and all(d["交付形态"] == "独立页面" for d in split["各域交付范围"]))

print("== 场景7 同一组外账户验证：撤回后组合统计/明细拒绝读取，旧签收依据可回查 ==")
verify, errs = service.verify_access({
    "请求人分组编号": PARTNER, "数据域编号": ORDER,
    "请求汇总级别": "明细", "核对日期": CHECK_DATE,
})
check("访问核验成功", verify is not None, str(errs))
check("明细读取结论=拒绝读取", verify and verify["读取结论"] == "拒绝读取", verify and verify["读取结论"])
check("标记为因撤回而拒绝", verify and verify["是否因撤回拒绝"] is True)
check("当前有效级别=无", verify and verify["当前有效汇总级别"] == NONE_LEVEL)
check("旧签收依据仍可回查（含 SIGN-0001 与新签收）",
      verify and len(verify["旧签收依据"]) >= 2
      and any(s["签收编号"] == "SIGN-0001" for s in verify["旧签收依据"]))
verify_agg, _ = service.verify_access({
    "请求人分组编号": PARTNER, "数据域编号": RISK,
    "请求汇总级别": "地区级汇总", "核对日期": CHECK_DATE,
})
check("风控域地区级汇总仍允许读取", verify_agg and verify_agg["读取结论"] == "允许读取",
      verify_agg and verify_agg["读取结论"])
verify_risk_detail, _ = service.verify_access({
    "请求人分组编号": PARTNER, "数据域编号": RISK,
    "请求汇总级别": "明细", "核对日期": NEXT_WEEK,
})
check("下周风控域明细仍允许读取", verify_risk_detail and verify_risk_detail["读取结论"] == "允许读取")

print("== 场景8 用户组消费范围：每个组可接收的只读页面与汇总数据范围 ==")
consume_partner = service.group_consumption(PARTNER)
consume_analyst = service.group_consumption(ANALYST)
check("合作方组合页面=访问拒绝（订单域已无许可）",
      "拒绝" in consume_partner["组合只读页面"], consume_partner["组合只读页面"])
partner_order = next(d for d in consume_partner["各数据域消费范围"] if d["数据域编号"] == ORDER)
partner_risk = next(d for d in consume_partner["各数据域消费范围"] if d["数据域编号"] == RISK)
check("合作方订单域无可接收页面且标记撤回", partner_order["只读页面"].startswith("无可接收") and partner_order["是否含撤回"])
check("合作方风控域可接收明细只读页", "明细只读页" in partner_risk["只读页面"], partner_risk["只读页面"])
analyst_risk = next(d for d in consume_analyst["各数据域消费范围"] if d["数据域编号"] == RISK)
check("分析组风控域只到地区级页面、明细页拒绝", "明细页拒绝" in analyst_risk["只读页面"], analyst_risk["只读页面"])

print("== 场景9 解除共享后再次申请：回查上次批准的数据层级与完整历史 ==")
last = service.last_approved_level(PARTNER, DASH)
check("存在历史签收", last["是否有历史签收"] is True)
# 最新一条是撤回后的独立交付：组合级别为无，按域分别交付。
check("最新签收=按数据域独立交付", last["上次发布方式"] == "收回组合页并按数据域独立交付",
      last.get("上次发布方式"))
check("最新签收组合级别=无（组合页已收回）", last["上次批准组合级别"] == NONE_LEVEL,
      last.get("上次批准组合级别"))
check("最新签收仍可回查各域独立交付范围", len(last["上次各域交付范围"]) == 2)
# 完整历史里仍能回查到解除前那次「地区级汇总」降级批准的数据层级。
history = service.list_signoffs(group_id=PARTNER, dashboard_no=DASH)
downgrade = [s for s in history if s["组合交付级别"] == "地区级汇总"]
check("可追溯到解除前地区级汇总的批准层级", len(downgrade) >= 1)
none_last = service.last_approved_level(PARTNER, "DASH-NOT-EXIST")
check("无历史时明确返回无签收", none_last["是否有历史签收"] is False)

print("== 场景10 已签收发布记录只追加不改写 ==")
signoffs = service.list_signoffs(group_id=PARTNER)
check("签收记录累计 3 条（初始1 + 降级1 + 独立1）", len(signoffs) == 3, str(len(signoffs)))
check("最早的 SIGN-0001 撤回后仍保留", any(s["签收编号"] == "SIGN-0001" for s in signoffs))

print()
print(f"通过 {_passed} 项，失败 {len(_failed)} 项")
if _failed:
    for item in _failed:
        print("  -", item)
    sys.exit(1)
print("全部规则验证通过。")
