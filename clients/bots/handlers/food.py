import logging
import time
from clients.bots.handlers.base import BaseHandler
from clients.bots.qq.utils import _truncate_text

logger = logging.getLogger(__name__)

class FoodHandler(BaseHandler):
    def _resolve_persona_payload(self, prefs: dict | None) -> dict[str, str]:
        prefs = prefs if isinstance(prefs, dict) else {}
        adapter_cfg = getattr(self.adapter, "cfg", None)
        persona_filename = str(
            prefs.get("persona_filename")
            or getattr(adapter_cfg, "persona_filename", "")
            or ""
        ).strip()
        role_id = str(getattr(adapter_cfg, "role_id", "") or "").strip().lower()
        if role_id in {"aveline", "ling"}:
            return {
                "role_id": role_id,
                "persona_filename": persona_filename,
            }

        try:
            from core.services.dual_role.personas import resolve_role_id_from_persona

            role_id = str(
                resolve_role_id_from_persona(persona_filename=persona_filename)
            ).strip().lower()
        except Exception:
            role_id = ""
        return {
            "role_id": role_id if role_id in {"aveline", "ling"} else "",
            "persona_filename": persona_filename,
        }

    async def show_food_menu(self, session_id: str, rest: str = ""):
        status, data = await self.api_request("GET", "/api/v1/food/menu")
        if status != 200 or not isinstance(data, list):
            await self.send_text(session_id, "获取食物菜单失败")
            return

        keyword = str(rest or "").strip()
        items = data
        if keyword:
            k = keyword.lower()
            filtered = []
            for it in items:
                if not isinstance(it, dict):
                    continue
                name = str(it.get("name") or "").lower()
                fid = str(it.get("id") or "").lower()
                if k in name or k in fid:
                    filtered.append(it)
            items = filtered

        lines = ["[食物菜单]", "用法：/买 <序号/ID> [数量] 或 /买 序号*数量  |  /吃 <序号/ID>  |  /库存"]
        show_items = items[:30]
        for idx, it in enumerate(show_items, start=1):
            try:
                fid = str(it.get("id") or "").strip()
                name = str(it.get("name") or "").strip()
                icon = str(it.get("icon") or "").strip()
                price = int(it.get("price") or 0)
                nutrition = it.get("nutrition") if isinstance(it, dict) else {}
                hunger = float((nutrition or {}).get("hunger") or 0.0)
                thirst = float((nutrition or {}).get("thirst") or 0.0)
                energy = float((nutrition or {}).get("energy") or 0.0)
                health = float((nutrition or {}).get("health") or 0.0)
            except Exception:
                continue
            if not fid or not name:
                continue
            lines.append(
                f"{idx}. {icon}{name} 🪙{price} ({fid})  饱+{hunger:g} 渴+{thirst:g} 能+{energy:g} 健{health:+g}"
            )

        if len(items) > len(show_items):
            lines.append(f"...（共 {len(items)} 个，已显示前 {len(show_items)} 个；可用 /食物 <关键词> 过滤）")

        await self.send_text(session_id, _truncate_text("\n".join(lines), 1800))

    async def show_food_inventory(self, session_id: str):
        status, data = await self.api_request("GET", "/api/v1/food/inventory")
        if status != 200 or not isinstance(data, dict) or not data.get("success"):
            await self.send_text(session_id, "获取背包失败")
            return

        items = data.get("data")
        if not isinstance(items, list) or not items:
            await self.send_text(session_id, "背包里还没有食物。先用 /食物 查看菜单，再用 /买 购买吧。")
            return

        now = time.time()
        lines = ["[食物背包]", "用法：/吃 <序号/ID>"]
        for idx, it in enumerate(items[:40], start=1):
            if not isinstance(it, dict):
                continue
            fid = str(it.get("food_id") or "").strip()
            name = str(it.get("name") or "").strip()
            icon = str(it.get("icon") or "").strip()
            try:
                qty = int(it.get("quantity") or 0)
            except Exception:
                qty = 0
            try:
                exp = float(it.get("expire_at") or 0.0)
            except Exception:
                exp = 0.0

            remain = "—"
            if exp > 0:
                delta = int(exp - now)
                if delta <= 0:
                    continue
                if delta < 3600:
                    remain = f"{max(1, delta // 60)}分钟"
                else:
                    remain = f"{delta / 3600.0:.1f}小时"

            if not fid or qty <= 0:
                continue
            lines.append(f"{idx}. {icon}{name} x{qty}  剩余:{remain}  ({fid})")

        await self.send_text(session_id, _truncate_text("\n".join(lines), 1800))

    async def _resolve_food_id(self, token: str) -> str:
        t = str(token or "").strip()
        if not t:
            return ""

        if t.isdigit():
            idx = int(t)
            status, data = await self.api_request("GET", "/api/v1/food/menu")
            if status == 200 and isinstance(data, list) and 1 <= idx <= len(data):
                it = data[idx - 1]
                if isinstance(it, dict):
                    return str(it.get("id") or "").strip()
            return ""

        return t

    async def handle_food_buy(self, session_id: str, rest: str):
        arg = str(rest or "").strip()
        if not arg:
            await self.send_text(session_id, "用法：/买 <序号/ID> [数量]\n支持：/买 19 10 或 /买 19*10\n先用 /食物 查看菜单")
            return

        # 支持 "19*10" 和 "19 10" 两种写法
        if "*" in arg and " " not in arg:
            star_parts = arg.split("*", 1)
            food_token = star_parts[0].strip()
            qty_token = star_parts[1].strip() if len(star_parts) > 1 else "1"
        else:
            parts = arg.split()
            food_token = parts[0] if parts else ""
            qty_token = parts[1] if len(parts) >= 2 else "1"

        food_id = await self._resolve_food_id(food_token)
        if not food_id:
            await self.send_text(session_id, "未找到对应的食物。先用 /食物 查看菜单。")
            return

        try:
            qty = int(qty_token)
        except Exception:
            qty = 1
        qty = max(1, min(99, qty))

        logger.info(f"购买食物: food_token={food_token}, food_id={food_id}, qty={qty}")
        status, data = await self.api_request("POST", f"/api/v1/food/buy/{food_id}", params={"quantity": qty})
        if status != 200 or not isinstance(data, dict) or not data.get("success"):
            msg = "购买失败"
            if isinstance(data, dict):
                msg = str(data.get("message") or data.get("error") or data.get("detail") or msg)
            await self.send_friendly_error(session_id, "购买食物", msg)
            return

        await self.send_text(session_id, str(data.get("message") or "购买成功"))

    async def handle_food_eat(self, session_id: str, rest: str, prefs: dict | None = None):
        arg = str(rest or "").strip()
        if not arg:
            await self.send_text(session_id, "用法：/吃 <序号/ID>\n背包优先消耗；无则花金币")
            return

        food_token = arg.split()[0]
        food_id = await self._resolve_food_id(food_token)
        logger.info(f"进食指令: token={food_token}, resolved_id={food_id}")
        if not food_id:
            await self.send_text(session_id, "未找到对应的食物。先用 /食物 查看菜单。")
            return

        persona_payload = self._resolve_persona_payload(prefs)
        status, data = await self.api_request(
            "POST",
            f"/api/v1/food/eat/{food_id}",
            params={
                "from_inventory": "true",
                "eater": "user",
                "role_id": persona_payload["role_id"],
                "persona_filename": persona_payload["persona_filename"],
            },
        )

        logger.info(f"进食API响应: status={status}, data={data}")

        if status != 200 or not isinstance(data, dict) or not data.get("success"):
            msg = "进食失败"
            if isinstance(data, dict):
                msg = str(data.get("message") or data.get("error") or data.get("detail") or msg)
            if status != 200:
                msg += f" (HTTP {status})"
            logger.warning(f"进食失败: status={status}, data={data}")
            await self.send_friendly_error(session_id, "进食", msg)
            return

        msg = str(data.get("message") or "进食成功")
        used_inv = bool(data.get("used_inventory"))
        try:
            spent = int(data.get("coins_spent") or 0)
        except Exception:
            spent = 0
        if used_inv:
            msg += "（已从背包消耗 1 份）"
        elif spent > 0:
            msg += f"（花费 🪙{spent}）"
        await self.send_text(session_id, msg)
