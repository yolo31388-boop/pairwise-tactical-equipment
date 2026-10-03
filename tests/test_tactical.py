"""
战术装备系统 - 验收测试

运行方式：python -m pytest tests/test_tactical.py -q
共 13 个测试用例
"""
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from equipment.tactical import TacticalEquipment


class TestTacticalEquipment:
    """战术装备系统测试套件"""

    def setup_method(self):
        """每个测试前的初始化"""
        self.system = TacticalEquipment()

    # ---------------- 闪光弹 ----------------

    def test_case_01(self):
        """闪光弹实际影响视野：面向爆炸的玩家视野下降且屏幕泛白"""
        result = self.system.flashbang_effect(
            "p1", player_pos=(0, 0, 0), player_facing=(1, 0, 0),
            flash_pos=(5, 0, 0))
        assert result["blinded"] is True
        assert self.system.get_player_vision("p1") < 1.0
        assert self.system.get_screen_white("p1") > 0.0

    def test_case_02(self):
        """闪光弹持续时间可配置，且不是写死的 0.1 秒"""
        self.system.flashbang_effect(
            "p1", (0, 0, 0), (1, 0, 0), (5, 0, 0), duration=3.0)
        self.system.update(1.0)
        assert self.system.get_player_vision("p1") < 1.0  # 1 秒后仍未恢复
        self.system.update(2.5)
        assert self.system.get_player_vision("p1") == 1.0  # 超时后恢复
        assert self.system.get_screen_white("p1") == 0.0

    def test_case_03(self):
        """闪光弹朝向判断：背对爆炸的玩家不被闪"""
        result = self.system.flashbang_effect(
            "p1", player_pos=(0, 0, 0), player_facing=(-1, 0, 0),
            flash_pos=(5, 0, 0))
        assert result["blinded"] is False
        assert self.system.get_player_vision("p1") == 1.0
        assert self.system.get_screen_white("p1") == 0.0

    # ---------------- 烟雾弹 ----------------

    def test_case_04(self):
        """烟雾弹真实阻挡视线：穿过烟雾云的视线被阻断"""
        self.system.smoke_grenade("s1", position=(5, 0, 0))
        self.system.update(3.0)  # 扩散完成
        assert self.system.is_line_of_sight_blocked((0, 0, 0), (10, 0, 0)) is True
        # 不经过烟雾的视线不受影响
        assert self.system.is_line_of_sight_blocked((0, 50, 0), (10, 50, 0)) is False

    def test_case_05(self):
        """烟雾随时间扩散，半径逐渐增大"""
        self.system.smoke_grenade("s1", position=(0, 0, 0), max_radius=5.0)
        self.system.update(1.5)
        r1 = self.system.get_smoke("s1")["radius"]
        self.system.update(1.5)
        r2 = self.system.get_smoke("s1")["radius"]
        assert 0.0 < r1 < r2
        assert r2 == pytest.approx(5.0)

    def test_case_06(self):
        """烟雾持续时间可配置，到期后消散且不再阻挡视线"""
        self.system.smoke_grenade("s1", position=(5, 0, 0), duration=10.0)
        self.system.update(5.0)
        assert self.system.get_smoke("s1")["active"] is True
        self.system.update(6.0)
        assert self.system.get_smoke("s1")["active"] is False
        assert self.system.is_line_of_sight_blocked((0, 0, 0), (10, 0, 0)) is False

    # ---------------- C4 ----------------

    def test_case_07(self):
        """C4 支持遥控引爆"""
        self.system.c4_plant("c1", position=(0, 0, 0), timer=60.0)
        result = self.system.c4_detonate("c1")
        assert result["detonated"] is True
        assert result["method"] == "remote"
        assert self.system.get_c4("c1")["status"] == "exploded"
        assert self.system.get_c4("c1")["explode_method"] == "remote"

    def test_case_08(self):
        """C4 定时时间可调，到时间自动爆炸"""
        self.system.c4_plant("c1", position=(0, 0, 0), timer=5.0)
        assert self.system.get_c4("c1")["timer"] == 5.0
        self.system.update(4.0)
        assert self.system.get_c4("c1")["status"] == "armed"
        self.system.update(1.5)
        c4 = self.system.get_c4("c1")
        assert c4["status"] == "exploded"
        assert c4["explode_method"] == "timer"

    def test_case_09(self):
        """C4 拆除有明确反馈，且拆除后不再爆炸"""
        self.system.c4_plant("c1", position=(0, 0, 0), timer=5.0)
        result = self.system.c4_defuse("c1")
        assert result["defused"] is True
        assert "拆除" in result["message"]
        self.system.update(10.0)
        assert self.system.get_c4("c1")["status"] == "defused"

    # ---------------- 阔剑地雷 ----------------

    def test_case_10(self):
        """阔剑扇形触发：正面扇区内目标触发爆炸"""
        self.system.claymore_plant("m1", position=(0, 0, 0), facing=(1, 0, 0))
        assert self.system.claymore_check("m1", (5, 1, 0)) is True
        assert self.system.get_claymore("m1")["status"] == "exploded"

    def test_case_11(self):
        """阔剑背后不触发（扇形而非球形），且有红色激光警告线"""
        self.system.claymore_plant("m1", position=(0, 0, 0), facing=(1, 0, 0))
        # 背后目标不触发
        assert self.system.claymore_check("m1", (-3, 0, 0)) is False
        assert self.system.get_claymore("m1")["status"] == "armed"
        # 警告线可见且为红色
        warning = self.system.claymore_warning("m1")
        assert warning["visible"] is True
        assert len(warning["lasers"]) == 2
        assert all(l["color"] == "red" for l in warning["lasers"])

    def test_case_12(self):
        """阔剑被敌方拆除时有明确提示，拆除后不再触发"""
        self.system.claymore_plant("m1", position=(0, 0, 0), facing=(1, 0, 0))
        result = self.system.claymore_defuse("m1", by_enemy=True)
        assert result["defused"] is True
        assert "敌方" in result["notification"]
        assert self.system.claymore_check("m1", (5, 0, 0)) is False

    # ---------------- 心跳传感器 ----------------

    def test_case_13(self):
        """心跳传感器：检测移动玩家，范围与更新频率可配置"""
        system = TacticalEquipment(config={
            "heartbeat_range": 15.0,
            "heartbeat_interval": 0.2,
        })
        players = [
            {"id": "static", "position": (5, 0, 0), "moving": False},
            {"id": "runner", "position": (8, 0, 0), "moving": True},
            {"id": "far", "position": (30, 0, 0), "moving": True},
        ]
        detected = system.heartbeat_sensor((0, 0, 0), players)
        ids = {d["id"] for d in detected}
        assert ids == {"static", "runner"}  # 移动玩家也能检测到，超范围的排除

        # 更新频率限制：间隔内重复扫描返回缓存（玩家已移动也不刷新）
        players[1]["position"] = (14, 0, 0)
        cached = system.heartbeat_sensor((0, 0, 0), players)
        assert cached[1]["position"] == (8, 0, 0)

        # 经过一个更新间隔后重新扫描，位置刷新
        system.update(0.3)
        refreshed = system.heartbeat_sensor((0, 0, 0), players)
        pos = {d["id"]: d["position"] for d in refreshed}
        assert pos["runner"] == (14, 0, 0)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
