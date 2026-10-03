"""
战术装备系统 - 核心模块（修复版）

修复内容：
- 闪光弹：实际降低玩家视野/屏幕泛白，持续时间可配置，背对闪光弹不被闪
- 烟雾弹：生成真实阻挡视线的烟雾云，随时间扩散，持续时间可配置
- C4：支持遥控引爆，定时时间可调，拆除有反馈
- 阔剑地雷：扇形触发（背后不炸），有激光警告线，拆除有提示
- 心跳传感器：检测所有玩家（含移动），范围与更新频率可配置
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
import math

Vector = Tuple[float, ...]

DEFAULTS = {
    # 闪光弹
    "flashbang_duration": 3.0,      # 致盲持续时间（秒）
    "flashbang_max_range": 20.0,    # 有效范围（米）
    "flashbang_fov": 120.0,         # 受影响视角（度），视角外不受影响
    # 烟雾弹
    "smoke_duration": 15.0,         # 烟雾持续时间（秒）
    "smoke_max_radius": 5.0,        # 烟雾最大半径（米）
    "smoke_expand_time": 3.0,       # 扩散到最大半径所需时间（秒）
    # C4
    "c4_timer": 30.0,               # 默认定时（秒），可调整
    # 阔剑地雷
    "claymore_range": 10.0,         # 触发距离（米）
    "claymore_angle": 60.0,         # 扇形触发角（度）
    # 心跳传感器
    "heartbeat_range": 10.0,        # 检测范围（米）
    "heartbeat_interval": 0.5,      # 扫描更新间隔（秒）
}


def _sub(a: Vector, b: Vector) -> Vector:
    return tuple(x - y for x, y in zip(a, b))


def _length(v: Vector) -> float:
    return math.sqrt(sum(x * x for x in v))


def _distance(a: Vector, b: Vector) -> float:
    return _length(_sub(a, b))


def _dot(a: Vector, b: Vector) -> float:
    return sum(x * y for x, y in zip(a, b))


def _angle_between(a: Vector, b: Vector) -> float:
    """两向量夹角（度）。零向量返回 0。"""
    la, lb = _length(a), _length(b)
    if la == 0 or lb == 0:
        return 0.0
    cos = max(-1.0, min(1.0, _dot(a, b) / (la * lb)))
    return math.degrees(math.acos(cos))


def _segment_point_distance(a: Vector, b: Vector, p: Vector) -> float:
    """线段 ab 到点 p 的最短距离。"""
    ab = _sub(b, a)
    ap = _sub(p, a)
    denom = _dot(ab, ab)
    t = 0.0 if denom == 0 else max(0.0, min(1.0, _dot(ap, ab) / denom))
    closest = tuple(a[i] + t * ab[i] for i in range(len(a)))
    return _distance(closest, p)


@dataclass
class Config:
    """配置项"""
    pass


class TacticalEquipment:
    """战术装备系统核心类"""

    def __init__(self, config: Optional[Dict] = None):
        self.config = dict(DEFAULTS)
        if config:
            self.config.update(config)
        self._reset_state()

    def _reset_state(self):
        self._state = {
            "players": {},      # player_id -> 致盲/视野状态
            "smokes": {},       # smoke_id -> 烟雾云
            "c4": {},           # c4_id -> C4 状态
            "claymores": {},    # mine_id -> 阔剑状态
            "heartbeat": {"last_scan": None, "cache": [], "timer": 0.0},
        }
        self._history = []

    # ------------------------------------------------------------------
    # 帧更新
    # ------------------------------------------------------------------
    def update(self, dt: float):
        """每帧更新：推进致盲恢复、烟雾扩散/消散、C4 定时、传感器计时。"""
        # 玩家致盲恢复
        for player in self._state["players"].values():
            if player["blind_timer"] > 0:
                player["blind_timer"] = max(0.0, player["blind_timer"] - dt)
                if player["blind_timer"] == 0.0:
                    player["blindness"] = 0.0
                    player["screen_white"] = 0.0
                else:
                    frac = player["blind_timer"] / player["blind_duration"]
                    player["blindness"] = player["peak_blindness"] * frac
                    player["screen_white"] = player["peak_white"] * frac

        # 烟雾扩散与消散
        for smoke in self._state["smokes"].values():
            if not smoke["active"]:
                continue
            smoke["age"] += dt
            if smoke["age"] >= smoke["duration"]:
                smoke["active"] = False
                smoke["radius"] = 0.0
            else:
                expand = self.config["smoke_expand_time"]
                frac = min(1.0, smoke["age"] / expand) if expand > 0 else 1.0
                smoke["radius"] = smoke["max_radius"] * frac

        # C4 定时爆炸
        for c4 in self._state["c4"].values():
            if c4["status"] == "armed":
                c4["remaining"] -= dt
                if c4["remaining"] <= 0:
                    self._explode_c4(c4, method="timer")

        # 心跳传感器扫描计时
        self._state["heartbeat"]["timer"] += dt

    def reset(self):
        """重置状态"""
        self._reset_state()

    # ------------------------------------------------------------------
    # 闪光弹
    # ------------------------------------------------------------------
    def flashbang_effect(self, player_id: str, player_pos: Vector,
                         player_facing: Vector, flash_pos: Vector,
                         duration: Optional[float] = None) -> Dict:
        """闪光弹爆炸：根据距离与朝向实际修改玩家视野和屏幕效果。

        - 面向闪光弹（在 fov 内）：致盲，视野降为 0，屏幕泛白
        - 背对闪光弹：不受影响
        - 持续时间可配置，随时间恢复
        """
        duration = duration if duration is not None else self.config["flashbang_duration"]
        max_range = self.config["flashbang_max_range"]
        fov = self.config["flashbang_fov"]

        result = {"player_id": player_id, "blinded": False,
                  "intensity": 0.0, "duration": 0.0}

        dist = _distance(player_pos, flash_pos)
        if dist > max_range:
            return result

        to_flash = _sub(flash_pos, player_pos)
        angle = _angle_between(player_facing, to_flash)
        if angle > fov / 2:
            # 背对闪光弹，不被闪
            return result

        # 距离越近强度越高
        intensity = 1.0 - (dist / max_range) * 0.5
        player = self._state["players"].setdefault(player_id, {
            "blindness": 0.0, "screen_white": 0.0,
            "blind_timer": 0.0, "blind_duration": 1.0,
            "peak_blindness": 0.0, "peak_white": 0.0,
        })
        player["blindness"] = intensity
        player["screen_white"] = intensity
        player["peak_blindness"] = intensity
        player["peak_white"] = intensity
        player["blind_timer"] = duration
        player["blind_duration"] = duration

        result.update({"blinded": True, "intensity": intensity,
                       "duration": duration})
        self._history.append(("flashbang", player_id, intensity))
        return result

    def get_player_vision(self, player_id: str) -> float:
        """玩家视野清晰度：1.0 正常，0.0 完全致盲。"""
        player = self._state["players"].get(player_id)
        if not player:
            return 1.0
        return 1.0 - player["blindness"]

    def get_screen_white(self, player_id: str) -> float:
        """屏幕泛白程度：0.0 正常，1.0 全白。"""
        player = self._state["players"].get(player_id)
        if not player:
            return 0.0
        return player["screen_white"]

    # ------------------------------------------------------------------
    # 烟雾弹
    # ------------------------------------------------------------------
    def smoke_grenade(self, smoke_id: str, position: Vector,
                      duration: Optional[float] = None,
                      max_radius: Optional[float] = None) -> Dict:
        """投掷烟雾弹：生成持续扩散、真实阻挡视线的烟雾云。"""
        smoke = {
            "id": smoke_id,
            "position": tuple(position),
            "duration": duration if duration is not None else self.config["smoke_duration"],
            "max_radius": max_radius if max_radius is not None else self.config["smoke_max_radius"],
            "radius": 0.0,
            "age": 0.0,
            "active": True,
        }
        self._state["smokes"][smoke_id] = smoke
        self._history.append(("smoke", smoke_id))
        return dict(smoke)

    def get_smoke(self, smoke_id: str) -> Optional[Dict]:
        smoke = self._state["smokes"].get(smoke_id)
        return dict(smoke) if smoke else None

    def is_line_of_sight_blocked(self, start: Vector, end: Vector) -> bool:
        """视线是否被任意活跃烟雾云阻挡。"""
        for smoke in self._state["smokes"].values():
            if not smoke["active"] or smoke["radius"] <= 0:
                continue
            if _segment_point_distance(start, end, smoke["position"]) <= smoke["radius"]:
                return True
        return False

    # ------------------------------------------------------------------
    # C4
    # ------------------------------------------------------------------
    def c4_plant(self, c4_id: str, position: Vector,
                 timer: Optional[float] = None) -> Dict:
        """安装 C4，定时时间可调。"""
        c4 = {
            "id": c4_id,
            "position": tuple(position),
            "timer": timer if timer is not None else self.config["c4_timer"],
            "remaining": timer if timer is not None else self.config["c4_timer"],
            "status": "armed",
            "explode_method": None,
        }
        self._state["c4"][c4_id] = c4
        self._history.append(("c4_plant", c4_id))
        return dict(c4)

    def c4_detonate(self, c4_id: str) -> Dict:
        """遥控引爆 C4。"""
        c4 = self._state["c4"].get(c4_id)
        if not c4 or c4["status"] != "armed":
            return {"detonated": False, "reason": "not_armed"}
        self._explode_c4(c4, method="remote")
        return {"detonated": True, "method": "remote"}

    def c4_defuse(self, c4_id: str) -> Dict:
        """拆除 C4，返回明确反馈。"""
        c4 = self._state["c4"].get(c4_id)
        if not c4 or c4["status"] != "armed":
            return {"defused": False, "reason": "not_armed"}
        c4["status"] = "defused"
        self._history.append(("c4_defuse", c4_id))
        return {"defused": True,
                "message": f"C4 {c4_id} 已成功拆除"}

    def get_c4(self, c4_id: str) -> Optional[Dict]:
        c4 = self._state["c4"].get(c4_id)
        return dict(c4) if c4 else None

    def _explode_c4(self, c4: Dict, method: str):
        c4["status"] = "exploded"
        c4["explode_method"] = method
        c4["remaining"] = 0.0
        self._history.append(("c4_explode", c4["id"], method))

    # ------------------------------------------------------------------
    # 阔剑地雷
    # ------------------------------------------------------------------
    def claymore_plant(self, mine_id: str, position: Vector, facing: Vector,
                       trigger_range: Optional[float] = None,
                       trigger_angle: Optional[float] = None) -> Dict:
        """布置阔剑地雷：扇形触发区域 + 激光警告线。"""
        mine = {
            "id": mine_id,
            "position": tuple(position),
            "facing": tuple(facing),
            "range": trigger_range if trigger_range is not None else self.config["claymore_range"],
            "angle": trigger_angle if trigger_angle is not None else self.config["claymore_angle"],
            "status": "armed",
        }
        self._state["claymores"][mine_id] = mine
        self._history.append(("claymore_plant", mine_id))
        return dict(mine)

    def claymore_check(self, mine_id: str, target_pos: Vector) -> bool:
        """检测目标是否进入扇形触发区；进入则引爆并返回 True。"""
        mine = self._state["claymores"].get(mine_id)
        if not mine or mine["status"] != "armed":
            return False
        to_target = _sub(target_pos, mine["position"])
        if _length(to_target) > mine["range"]:
            return False
        if _angle_between(mine["facing"], to_target) > mine["angle"] / 2:
            # 扇形之外（含背后）不触发
            return False
        mine["status"] = "exploded"
        self._history.append(("claymore_explode", mine_id))
        return True

    def claymore_warning(self, mine_id: str) -> Dict:
        """阔剑的红外激光警告线（触发扇区两边界）。"""
        mine = self._state["claymores"].get(mine_id)
        if not mine or mine["status"] != "armed":
            return {"visible": False, "lasers": []}
        pos = mine["position"]
        facing = mine["facing"]
        base = math.atan2(facing[1], facing[0]) if len(facing) >= 2 else 0.0
        half = math.radians(mine["angle"] / 2)
        lasers = []
        for sign in (-1, 1):
            ang = base + sign * half
            end = (pos[0] + mine["range"] * math.cos(ang),
                   pos[1] + mine["range"] * math.sin(ang)) + tuple(pos[2:])
            lasers.append({"start": pos, "end": end, "color": "red"})
        return {"visible": True, "lasers": lasers}

    def claymore_defuse(self, mine_id: str, by_enemy: bool = True) -> Dict:
        """拆除阔剑，给出明确提示。"""
        mine = self._state["claymores"].get(mine_id)
        if not mine or mine["status"] != "armed":
            return {"defused": False, "reason": "not_armed"}
        mine["status"] = "defused"
        self._history.append(("claymore_defuse", mine_id, by_enemy))
        return {"defused": True,
                "notification": f"阔剑地雷 {mine_id} 已被{'敌方' if by_enemy else '友方'}拆除"}

    def get_claymore(self, mine_id: str) -> Optional[Dict]:
        mine = self._state["claymores"].get(mine_id)
        return dict(mine) if mine else None

    # ------------------------------------------------------------------
    # 心跳传感器
    # ------------------------------------------------------------------
    def heartbeat_sensor(self, sensor_pos: Vector, players: List[Dict],
                         detection_range: Optional[float] = None) -> List[Dict]:
        """扫描范围内所有玩家（静止和移动都检测）。

        players: [{"id": ..., "position": (x, y, z), "moving": bool}, ...]
        扫描频率受 heartbeat_interval 限制：间隔内重复调用返回缓存结果。
        """
        interval = self.config["heartbeat_interval"]
        hb = self._state["heartbeat"]
        if hb["last_scan"] is not None and hb["timer"] < interval:
            return list(hb["cache"])

        rng = detection_range if detection_range is not None else self.config["heartbeat_range"]
        detected = []
        for p in players:
            if _distance(sensor_pos, p["position"]) <= rng:
                detected.append({
                    "id": p["id"],
                    "position": tuple(p["position"]),
                    "moving": bool(p.get("moving", False)),
                    "distance": _distance(sensor_pos, p["position"]),
                })
        hb["cache"] = detected
        hb["last_scan"] = hb["timer"]
        hb["timer"] = 0.0
        self._history.append(("heartbeat_scan", len(detected)))
        return list(detected)
