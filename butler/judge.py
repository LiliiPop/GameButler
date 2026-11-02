"""成败判定依据（MaaFramework 项目）：游戏记录里的 judge，只有两类。

  "judge": {
    "fail":    {"*": ["停止任务", "任务出错，已停止"], "任务名": [...]},
    "success": {"*": [{"match": "次数不足", "result": "exhausted"}],
                "任务名": ["Flag_签到完成", {"match": "活跃值达100", "required": false}, {"verify": "gb_verify_好友体力"}]}
  }

- 键 "*" = 这个游戏的所有任务；其他键 = 某个任务（任务名，不是任务键）。
- match：识别命中过的节点名，或脚本提示文字里出现的字。
- fail 命中 → 失败（即使框架报成功）。
- success 命中 → 完成。
- 写在某个任务下的完成依据默认是「必须命中」：一个都没命中、框架报成功 → 失败（流程走完了但没做成）。
  不想这样的写 "required": false（只在命中时改判完成）。"*" 下的从来不是必须的。
- 到这里还是失败的：命中标了 "result": "exhausted" 的 = 完成（无可做，例如次数用完）；
  否则运行 verify 节点核对画面，通过 = 完成（无可做，今天已经做过）。
- 脚本信号（[GB_DONE] / [GB_FAIL] / [GB_MANUAL] / [GB_PAUSE] / [GB_FUSE]）比这些都优先；熔断只认信号。
"""
from __future__ import annotations


def _entry(e, scope: str) -> dict:
    if isinstance(e, str):
        return {"match": e, "required": scope != "*"}
    if not isinstance(e, dict) or not (e.get("match") or e.get("verify")):
        raise ValueError(f"判定依据写法不对：{e!r}")
    out = {k: e[k] for k in ("match", "verify", "result") if e.get(k)}
    if out.get("result") not in (None, "exhausted"):
        raise ValueError(f"result 只能是 exhausted：{e!r}")
    if out.get("match"):
        out["required"] = scope != "*" and out.get("result") != "exhausted" and e.get("required", True) is not False
    return out


def validate(judge: dict) -> dict:
    """检查并规范写法；不对直接报错。"""
    judge = judge or {}
    extra = set(judge) - {"fail", "success"}
    if extra:
        raise ValueError(f"judge 只有 fail 和 success 两类，多了：{'、'.join(extra)}")
    for part in ("fail", "success"):
        if not isinstance(judge.get(part) or {}, dict) or not all(isinstance(x, list) for x in (judge.get(part) or {}).values()):
            raise ValueError(f"judge 的 {part} 要写成 {{任务名: [依据…]}}")
    for scope, lst in (judge.get("fail") or {}).items():
        if not all(isinstance(x, str) and x for x in lst):
            raise ValueError(f"失败依据要写成文字列表：{scope}")
    for scope, lst in (judge.get("success") or {}).items():
        for e in lst:
            _entry(e, scope)
    return judge


def for_task(g: dict, task: str) -> dict:
    """某个任务实际用的依据：{"fail": [文字…], "success": [条目…]}。"""
    j = g.get("judge") or {}
    fail = list((j.get("fail") or {}).get("*", [])) + list((j.get("fail") or {}).get(task, []))
    succ = [_entry(e, task) for e in (j.get("success") or {}).get(task, [])]
    succ += [_entry(e, "*") for e in (j.get("success") or {}).get("*", [])]
    return {"fail": fail, "success": succ}
