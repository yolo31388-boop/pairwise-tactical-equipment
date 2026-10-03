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

    # ---------------- 闪光弹 ---------------- #

    def test_case_01(self):
        """闪光弹实际降低面向玩家的视野（不只是标志位）"""
        player = {"id": "p1", "position": (3.0, 0.0, 0.0), "view_dir": (1.0, 0.0, 0.0)}
        affected = self.system.flashbang_effect((4.0, 0.0, 0.0), [player])
        assert "p1" in affected
        assert player["vision"] < 0.5
        assert player["blind_remaining"] > 0.1

    def test_case_02(self):
        """背对闪光弹的玩家不被闪（朝向判断）"""
        player = {"id": "p1", "position": (3.0, 0.0, 0.0), "view_dir": (-1.0, 0.0, 0.0)}
        affected = self.system.flashbang_effect((4.0, 0.0, 0.0), [player])
        assert affected == []
        assert player.get("vision", 1.0) == 1.0

    def test_case_03(self):
        """闪光弹持续时间可配置，且视野在持续时间结束后恢复"""
        system = TacticalEquipment({"flashbang_duration": 2.0})
        player = {"id": "p1", "position": (0.0, 0.0, 0.0), "view_dir": (1.0, 0.0, 0.0)}
        system.flashbang_effect((1.0, 0.0, 0.0), [player])
        assert player["blind_remaining"] == 2.0
        system.update(1.0)
        assert player["vision"] < 1.0
        system.update(2.0)
        assert player.get("vision", 1.0) == 1.0
        assert "blind_remaining" not in player

    # ---------------- 烟雾弹 ---------------- #

    def test_case_04(self):
        """烟雾弹实际阻挡视线"""
        self.system.smoke_grenade((0.0, 0.0, 0.0))
        assert self.system.is_line_blocked((-5.0, 0.0, 0.0), (5.0, 0.0, 0.0))
        assert not self.system.is_line_blocked((20.0, 0.0, 0.0), (25.0, 0.0, 0.0))

    def test_case_05(self):
        """烟雾随时间扩散，半径增大到上限"""
        smoke = self.system.smoke_grenade((0.0, 0.0, 0.0))
        initial_radius = smoke["radius"]
        self.system.update(2.0)
        assert smoke["radius"] > initial_radius
        self.system.update(100.0)
        assert smoke["radius"] == smoke["max_radius"]

    def test_case_06(self):
        """烟雾持续时间可配置，到期后消散且不再阻挡视线"""
        system = TacticalEquipment({"smoke_duration": 3.0})
        system.smoke_grenade((0.0, 0.0, 0.0))
        system.update(2.0)
        assert system.smokes
        assert system.is_line_blocked((-5.0, 0.0, 0.0), (5.0, 0.0, 0.0))
        system.update(2.0)
        assert system.smokes == []
        assert not system.is_line_blocked((-5.0, 0.0, 0.0), (5.0, 0.0, 0.0))

    # ---------------- C4 ---------------- #

    def test_case_07(self):
        """C4 安装后支持遥控引爆"""
        c4_id = self.system.c4_explosive((0.0, 0.0, 0.0))
        assert self.system.detonate_c4(c4_id)
        assert self.system.get_c4(c4_id)["exploded"]
        event = self.system.get_events()[-1]
        assert event["type"] == "c4_exploded"
        assert event["remote"] is True

    def test_case_08(self):
        """C4 定时时间可调，到时间才自动爆炸"""
        c4_id = self.system.c4_explosive((0.0, 0.0, 0.0), timer=2.0)
        self.system.update(1.0)
        assert not self.system.get_c4(c4_id)["exploded"]
        self.system.update(1.5)
        assert self.system.get_c4(c4_id)["exploded"]
        assert self.system.get_events()[-1]["remote"] is False

    def test_case_09(self):
        """C4 被拆除后有反馈，且不会再定时爆炸"""
        c4_id = self.system.c4_explosive((0.0, 0.0, 0.0), timer=1.0)
        result = self.system.defuse_c4(c4_id)
        assert result["success"]
        assert "拆除" in result["message"]
        assert self.system.get_c4(c4_id)["defused"]
        self.system.update(5.0)
        assert not self.system.get_c4(c4_id)["exploded"]
        assert self.system.get_events()[-1]["type"] == "c4_defused"

    # ---------------- 阔剑地雷 ---------------- #

    def test_case_10(self):
        """阔剑扇形触发：前方触发、背后不触发"""
        mine_id = self.system.claymore_mine(
            (0.0, 0.0, 0.0), (1.0, 0.0, 0.0), trigger_angle=60.0, trigger_range=8.0
        )
        assert self.system.check_claymore(mine_id, (5.0, 0.0, 0.0))
        assert not self.system.check_claymore(mine_id, (-5.0, 0.0, 0.0))
        assert not self.system.check_claymore(mine_id, (20.0, 0.0, 0.0))

    def test_case_11(self):
        """阔剑布置后有可见的激光警告线"""
        mine_id = self.system.claymore_mine((0.0, 0.0, 0.0), (1.0, 0.0, 0.0))
        laser = self.system.get_claymore_laser(mine_id)
        assert laser is not None
        start, end = laser
        assert start == (0.0, 0.0, 0.0)
        assert end[0] > 0
        assert self.system.get_claymore_laser("not_exist") is None

    def test_case_12(self):
        """阔剑被敌人拆除时有明确提示"""
        mine_id = self.system.claymore_mine((0.0, 0.0, 0.0), (1.0, 0.0, 0.0))
        result = self.system.defuse_claymore(mine_id, by_enemy=True)
        assert result["success"]
        assert result["notification"]
        assert not self.system.check_claymore(mine_id, (5.0, 0.0, 0.0))
        assert self.system.get_events()[-1]["by_enemy"] is True

    # ---------------- 心跳传感器 ---------------- #

    def test_case_13(self):
        """心跳传感器检测移动玩家，范围与更新频率可配置"""
        system = TacticalEquipment({"sensor_range": 6.0, "sensor_interval": 1.0})
        moving_near = {"id": "near", "position": (3.0, 0.0, 0.0), "moving": True}
        moving_far = {"id": "far", "position": (20.0, 0.0, 0.0), "moving": True}
        detected = system.heartbeat_sensor([moving_near, moving_far])
        assert "near" in detected
        assert "far" not in detected

        # 更新频率未到：目标已移出范围，仍返回缓存
        moving_near["position"] = (100.0, 0.0, 0.0)
        assert system.heartbeat_sensor([moving_near, moving_far]) == ["near"]

        # 到达更新间隔后重新扫描
        system.update(1.0)
        assert system.heartbeat_sensor([moving_near, moving_far]) == []

        # 范围可运行时调整
        system.update(1.0)
        assert "far" in system.heartbeat_sensor([moving_near, moving_far], max_range=30.0)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
