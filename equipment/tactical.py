"""
战术装备系统 - 核心模块

已修复问题：
- 闪光弹：实际降低玩家视野，持续时间/范围可配置，考虑玩家朝向（背对不受影响）
- 烟雾弹：实际阻挡视线，随时间扩散，持续时间可配置
- C4：支持遥控引爆，定时时间可调，拆除有反馈
- 阔剑地雷：扇形触发（背后不触发），带激光警告线，被拆除有提示
- 心跳传感器：检测所有玩家（含移动玩家），范围与更新频率可配置
"""
from typing import Dict, List, Optional, Tuple
import math

Vector = Tuple[float, float, float]

DEFAULT_CONFIG = {
    "flashbang_duration": 3.0,      # 闪光弹致盲持续时间（秒）
    "flashbang_radius": 10.0,       # 闪光弹有效半径（米）
    "smoke_duration": 15.0,         # 烟雾持续时间（秒）
    "smoke_initial_radius": 1.0,    # 烟雾初始半径（米）
    "smoke_max_radius": 5.0,        # 烟雾最大半径（米）
    "smoke_expand_rate": 1.0,       # 烟雾扩散速度（米/秒）
    "c4_timer": 30.0,               # C4 默认定时（秒）
    "claymore_angle": 60.0,         # 阔剑触发扇形角（度，全角）
    "claymore_range": 8.0,          # 阔剑触发距离（米）
    "sensor_range": 10.0,           # 心跳传感器范围（米）
    "sensor_interval": 0.5,         # 心跳传感器更新间隔（秒）
    "sensor_position": (0.0, 0.0, 0.0),  # 传感器位置
}


def _sub(a: Vector, b: Vector) -> Vector:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _add(a: Vector, b: Vector) -> Vector:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _scale(a: Vector, s: float) -> Vector:
    return (a[0] * s, a[1] * s, a[2] * s)


def _dot(a: Vector, b: Vector) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _length(a: Vector) -> float:
    return math.sqrt(_dot(a, a))


def _normalize(a: Vector) -> Vector:
    n = _length(a)
    if n == 0:
        return (0.0, 0.0, 0.0)
    return (a[0] / n, a[1] / n, a[2] / n)


def _segment_intersects_sphere(a: Vector, b: Vector, center: Vector, radius: float) -> bool:
    """判断线段 ab 是否与球体相交（用于视线遮挡判定）"""
    d = _sub(b, a)
    f = _sub(a, center)
    A = _dot(d, d)
    if A == 0:
        return _length(f) <= radius
    B = 2.0 * _dot(f, d)
    C = _dot(f, f) - radius * radius
    disc = B * B - 4.0 * A * C
    if disc < 0:
        return False
    disc = math.sqrt(disc)
    t1 = (-B - disc) / (2.0 * A)
    t2 = (-B + disc) / (2.0 * A)
    if 0.0 <= t1 <= 1.0 or 0.0 <= t2 <= 1.0:
        return True
    return t1 < 0.0 and t2 > 1.0


class TacticalEquipment:
    """战术装备系统核心类"""

    def __init__(self, config: Optional[Dict] = None):
        self.config = dict(DEFAULT_CONFIG)
        if config:
            self.config.update(config)
        self._state = {}
        self._history = []
        self._smokes: List[Dict] = []
        self._c4s: Dict[str, Dict] = {}
        self._mines: Dict[str, Dict] = {}
        self._blinded: List[Dict] = []
        self._c4_seq = 0
        self._mine_seq = 0
        self._sensor_elapsed = float("inf")  # 首次扫描立即执行
        self._sensor_cache: List[str] = []

    # ------------------------------------------------------------------ #
    # 帧更新
    # ------------------------------------------------------------------ #
    def update(self, dt: float):
        """每帧更新：致盲恢复、烟雾扩散/消散、C4 倒计时、传感器计时"""
        # 致盲恢复：视野随剩余时间线性恢复
        for player in list(self._blinded):
            player["blind_remaining"] -= dt
            ratio = max(0.0, player["blind_remaining"] / player["blind_duration"])
            player["vision"] = 1.0 - player["blind_intensity"] * ratio
            if player["blind_remaining"] <= 0:
                player["vision"] = 1.0
                for key in ("blind_remaining", "blind_duration", "blind_intensity"):
                    player.pop(key, None)
                self._blinded.remove(player)

        # 烟雾扩散与消散
        for smoke in list(self._smokes):
            smoke["radius"] = min(
                smoke["max_radius"], smoke["radius"] + smoke["expand_rate"] * dt
            )
            smoke["remaining"] -= dt
            if smoke["remaining"] <= 0:
                self._smokes.remove(smoke)

        # C4 定时倒计时，到时自动爆炸
        for c4 in self._c4s.values():
            if c4["exploded"] or c4["defused"]:
                continue
            c4["remaining"] -= dt
            if c4["remaining"] <= 0:
                self._explode_c4(c4, remote=False)

        # 传感器计时
        self._sensor_elapsed += dt

    def reset(self):
        """重置状态"""
        self._state = {}
        self._history = []
        self._smokes = []
        self._c4s = {}
        self._mines = {}
        self._blinded = []
        self._sensor_elapsed = float("inf")
        self._sensor_cache = []

    def get_events(self) -> List[Dict]:
        """获取历史事件（爆炸、拆除等反馈）"""
        return list(self._history)

    # ------------------------------------------------------------------ #
    # 闪光弹
    # ------------------------------------------------------------------ #
    def flashbang_effect(
        self,
        position: Vector,
        players: List[Dict],
        duration: Optional[float] = None,
        radius: Optional[float] = None,
    ) -> List[str]:
        """
        闪光弹爆炸：实际降低面向闪光的玩家视野。
        - 背对闪光的玩家不受影响（朝向判断）
        - 致盲强度随距离衰减，持续时间可配置
        返回受影响玩家 id 列表。
        """
        duration = duration if duration is not None else self.config["flashbang_duration"]
        radius = radius if radius is not None else self.config["flashbang_radius"]
        affected = []
        for player in players:
            to_flash = _sub(position, player["position"])
            dist = _length(to_flash)
            if dist > radius:
                continue
            view_dir = _normalize(player.get("view_dir", (1.0, 0.0, 0.0)))
            cos_angle = _dot(view_dir, _normalize(to_flash)) if dist > 0 else 1.0
            if cos_angle <= 0:
                continue  # 背对闪光弹，不被闪
            intensity = min(1.0, cos_angle * (1.0 - dist / radius))
            player["vision"] = max(0.0, 1.0 - intensity)
            player["blind_intensity"] = intensity
            player["blind_remaining"] = duration
            player["blind_duration"] = duration
            if player not in self._blinded:
                self._blinded.append(player)
            affected.append(player["id"])
        self._history.append({"type": "flashbang", "position": position, "affected": affected})
        return affected

    # ------------------------------------------------------------------ #
    # 烟雾弹
    # ------------------------------------------------------------------ #
    def smoke_grenade(
        self,
        position: Vector,
        duration: Optional[float] = None,
        initial_radius: Optional[float] = None,
        max_radius: Optional[float] = None,
        expand_rate: Optional[float] = None,
    ) -> Dict:
        """
        烟雾弹：生成真实阻挡视线的烟雾云，随时间扩散，持续时间可配置。
        返回烟雾实体。
        """
        smoke = {
            "position": position,
            "radius": initial_radius if initial_radius is not None else self.config["smoke_initial_radius"],
            "max_radius": max_radius if max_radius is not None else self.config["smoke_max_radius"],
            "expand_rate": expand_rate if expand_rate is not None else self.config["smoke_expand_rate"],
            "remaining": duration if duration is not None else self.config["smoke_duration"],
        }
        self._smokes.append(smoke)
        self._history.append({"type": "smoke", "position": position})
        return smoke

    def is_line_blocked(self, a: Vector, b: Vector) -> bool:
        """判断 a 到 b 的视线是否被任一烟雾云阻挡"""
        for smoke in self._smokes:
            if _segment_intersects_sphere(a, b, smoke["position"], smoke["radius"]):
                return True
        return False

    @property
    def smokes(self) -> List[Dict]:
        return list(self._smokes)

    # ------------------------------------------------------------------ #
    # C4
    # ------------------------------------------------------------------ #
    def c4_explosive(self, position: Vector, timer: Optional[float] = None) -> str:
        """
        安装 C4：定时时间可调，支持遥控引爆。
        返回 C4 id。
        """
        self._c4_seq += 1
        c4_id = "c4_%d" % self._c4_seq
        self._c4s[c4_id] = {
            "id": c4_id,
            "position": position,
            "timer": timer if timer is not None else self.config["c4_timer"],
            "remaining": timer if timer is not None else self.config["c4_timer"],
            "exploded": False,
            "defused": False,
        }
        return c4_id

    def detonate_c4(self, c4_id: str) -> bool:
        """遥控引爆 C4，成功返回 True"""
        c4 = self._c4s.get(c4_id)
        if not c4 or c4["exploded"] or c4["defused"]:
            return False
        self._explode_c4(c4, remote=True)
        return True

    def defuse_c4(self, c4_id: str) -> Dict:
        """拆除 C4，返回拆除结果反馈"""
        c4 = self._c4s.get(c4_id)
        if not c4:
            return {"success": False, "message": "C4 不存在"}
        if c4["exploded"]:
            return {"success": False, "message": "C4 已爆炸，无法拆除"}
        if c4["defused"]:
            return {"success": False, "message": "C4 已被拆除"}
        c4["defused"] = True
        event = {"type": "c4_defused", "id": c4_id, "message": "C4 已成功拆除"}
        self._history.append(event)
        return {"success": True, "message": "C4 已成功拆除"}

    def get_c4(self, c4_id: str) -> Optional[Dict]:
        return self._c4s.get(c4_id)

    def _explode_c4(self, c4: Dict, remote: bool):
        c4["exploded"] = True
        self._history.append({
            "type": "c4_exploded",
            "id": c4["id"],
            "position": c4["position"],
            "remote": remote,
        })

    # ------------------------------------------------------------------ #
    # 阔剑地雷
    # ------------------------------------------------------------------ #
    def claymore_mine(
        self,
        position: Vector,
        direction: Vector,
        trigger_angle: Optional[float] = None,
        trigger_range: Optional[float] = None,
    ) -> str:
        """
        布置阔剑地雷：扇形触发（仅面向方向），带激光警告线。
        返回地雷 id。
        """
        self._mine_seq += 1
        mine_id = "mine_%d" % self._mine_seq
        self._mines[mine_id] = {
            "id": mine_id,
            "position": position,
            "direction": _normalize(direction),
            "trigger_angle": trigger_angle if trigger_angle is not None else self.config["claymore_angle"],
            "trigger_range": trigger_range if trigger_range is not None else self.config["claymore_range"],
            "active": True,
        }
        return mine_id

    def check_claymore(self, mine_id: str, target_position: Vector) -> bool:
        """
        扇形触发判定：目标必须在触发距离内且位于朝向扇形内，
        背后目标不触发。
        """
        mine = self._mines.get(mine_id)
        if not mine or not mine["active"]:
            return False
        to_target = _sub(target_position, mine["position"])
        dist = _length(to_target)
        if dist > mine["trigger_range"]:
            return False
        if dist == 0:
            return True
        cos_angle = _dot(mine["direction"], _normalize(to_target))
        cos_half = math.cos(math.radians(mine["trigger_angle"] / 2.0))
        return cos_angle >= cos_half

    def get_claymore_laser(self, mine_id: str) -> Optional[Tuple[Vector, Vector]]:
        """获取阔剑激光警告线的起点和终点（玩家可见的红线）"""
        mine = self._mines.get(mine_id)
        if not mine or not mine["active"]:
            return None
        end = _add(mine["position"], _scale(mine["direction"], mine["trigger_range"]))
        return (mine["position"], end)

    def defuse_claymore(self, mine_id: str, by_enemy: bool = False) -> Dict:
        """拆除阔剑地雷，拆除时给出明确提示（敌方拆除会警告布雷者）"""
        mine = self._mines.get(mine_id)
        if not mine:
            return {"success": False, "message": "阔剑地雷不存在"}
        if not mine["active"]:
            return {"success": False, "message": "阔剑地雷已被拆除"}
        mine["active"] = False
        notification = (
            "警告：你的阔剑地雷正在被敌方拆除！" if by_enemy else "阔剑地雷已拆除"
        )
        event = {
            "type": "claymore_defused",
            "id": mine_id,
            "by_enemy": by_enemy,
            "notification": notification,
        }
        self._history.append(event)
        return {"success": True, "message": "阔剑地雷已拆除", "notification": notification}

    # ------------------------------------------------------------------ #
    # 心跳传感器
    # ------------------------------------------------------------------ #
    def heartbeat_sensor(
        self,
        players: List[Dict],
        max_range: Optional[float] = None,
        interval: Optional[float] = None,
        position: Optional[Vector] = None,
    ) -> List[str]:
        """
        心跳传感器扫描：检测范围内所有玩家（静止和移动均可检测）。
        - 范围与更新频率可配置
        - 距上次扫描不足 interval 时返回缓存结果（更新频率节流）
        返回检测到的玩家 id 列表。
        """
        if max_range is not None:
            self.config["sensor_range"] = max_range
        if interval is not None:
            self.config["sensor_interval"] = interval
        if position is not None:
            self.config["sensor_position"] = position

        if self._sensor_elapsed < self.config["sensor_interval"]:
            return list(self._sensor_cache)
        self._sensor_elapsed = 0.0

        origin = self.config["sensor_position"]
        max_dist = self.config["sensor_range"]
        detected = [
            p["id"] for p in players
            if _length(_sub(p["position"], origin)) <= max_dist
        ]
        self._sensor_cache = detected
        return list(detected)
