# 战术装备系统

## 项目描述

战术装备系统的bug修复项目。核心模块 `equipment/tactical.py` 存在多个已知bug，需要修复后使测试全部通过。

## 已知问题

- 闪光弹只设标志位不实际影响视野
- 烟雾弹不阻挡视线且持续时间太短
- C4不能遥控引爆且时间不可调
- 阔剑地雷触发范围球形不是扇形
- 心跳传感器只能检测静止玩家

## 项目结构

```
├── equipment/tactical.py       # 核心模块（带bug）
├── tests/test_tactical.py    # 验收测试（红态）
├── pyproject.toml          # 项目配置
└── README.md               # 说明文档
```

## 运行测试

```bash
python -m pytest tests/test_tactical.py -q
```

修复目标：所有 13 个测试全部通过。

## 技术要求

- 纯Python标准库，不引入第三方依赖
- 不修改测试文件
- 保持现有API接口不变
- 修复所有已知bug
