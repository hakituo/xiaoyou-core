# -*- coding: utf-8 -*-
"""商城-toy 类商品。"""
from core.food.models import ShopItem

TOYS: list[ShopItem] = [
    ShopItem(
            id="plush_bear", name="泰迪熊", description="经典棕色泰迪熊，柔软治愈",
            price=45, category="toy", sub_type="",
            icon="🧸", rarity="common",
            effect_desc="陪伴感+10",
        ),

    ShopItem(
            id="plush_bunny", name="兔子玩偶", description="长耳朵兔子玩偶，萌化人心",
            price=38, category="toy", sub_type="",
            icon="🐰", rarity="common",
            effect_desc="陪伴感+8",
        ),

    ShopItem(
            id="plush_cat", name="猫咪抱枕", description="胖橘猫造型抱枕",
            price=42, category="toy", sub_type="",
            icon="🐱", rarity="common",
            effect_desc="陪伴感+8",
        ),

    ShopItem(
            id="plush_penguin", name="企鹅玩偶", description="圆滚滚的企鹅毛绒玩具",
            price=40, category="toy", sub_type="",
            icon="🐧", rarity="common",
            effect_desc="陪伴感+8",
        ),

    ShopItem(
            id="plush_dragon", name="龙玩偶", description="紫色可爱小龙玩偶",
            price=55, category="toy", sub_type="",
            icon="🐲", rarity="common",
            effect_desc="陪伴感+10",
        ),

    ShopItem(
            id="plush_otter", name="水獭玩偶", description="手牵手水獭玩偶套装",
            price=48, category="toy", sub_type="",
            icon="🦦", rarity="common",
            effect_desc="陪伴感+10, 心情+5",
        ),

    ShopItem(
            id="plush_shark", name="鲨鱼玩偶", description="粉色鲨鱼抱枕",
            price=42, category="toy", sub_type="",
            icon="🦈", rarity="common",
            effect_desc="陪伴感+8",
        ),

    ShopItem(
            id="plush_axolotl", name="六角恐龙玩偶", description="墨西哥钝口螈玩偶",
            price=45, category="toy", sub_type="",
            icon="🦎", rarity="common",
            effect_desc="陪伴感+9",
        ),

    ShopItem(
            id="plush_corgi", name="柯基玩偶", description="电臀柯基毛绒玩具",
            price=40, category="toy", sub_type="",
            icon="🐶", rarity="common",
            effect_desc="陪伴感+8",
        ),

    ShopItem(
            id="plush_duck", name="小黄鸭", description="经典小黄鸭玩偶",
            price=25, category="toy", sub_type="",
            icon="🐤", rarity="common",
            effect_desc="陪伴感+5",
        ),

    ShopItem(
            id="plush_panda", name="熊猫玩偶", description="国宝大熊猫毛绒玩具",
            price=50, category="toy", sub_type="",
            icon="🐼", rarity="common",
            effect_desc="陪伴感+10",
        ),

    ShopItem(
            id="plush_frog", name="青蛙玩偶", description="悲伤青蛙玩偶",
            price=35, category="toy", sub_type="",
            icon="🐸", rarity="common",
            effect_desc="陪伴感+7",
        ),

    ShopItem(
            id="rubik_cube", name="魔方", description="3x3竞速魔方",
            price=30, category="toy", sub_type="",
            icon="🟦", rarity="common",
            effect_desc="智力+5, 专注+8",
        ),

    ShopItem(
            id="puzzle_500", name="500片拼图", description="梵高星空500片拼图",
            price=55, category="toy", sub_type="",
            icon="🧩", rarity="common",
            effect_desc="专注+10, 耐心+8",
        ),

    ShopItem(
            id="puzzle_1000", name="1000片拼图", description="莫奈花园1000片拼图",
            price=88, category="toy", sub_type="",
            icon="🧩", rarity="rare",
            effect_desc="专注+15, 耐心+12",
        ),

    ShopItem(
            id="puzzle_3d", name="3D立体拼图", description="3D水晶城堡立体拼图",
            price=68, category="toy", sub_type="",
            icon="🏰", rarity="rare",
            effect_desc="专注+12, 空间感+10",
        ),

    ShopItem(
            id="lego_city", name="积木城市", description="积木城市系列建筑套装",
            price=158, category="toy", sub_type="",
            icon="🏘️", rarity="rare",
            effect_desc="创造力+15, 专注+10",
        ),

    ShopItem(
            id="lego_flower", name="积木花束", description="积木花束创意套装",
            price=128, category="toy", sub_type="",
            icon="🌺", rarity="rare",
            effect_desc="创造力+12, 心情+8",
        ),

    ShopItem(
            id="lego_technic", name="积木机械", description="积木机械组跑车",
            price=288, category="toy", sub_type="",
            icon="🏎️", rarity="epic",
            effect_desc="创造力+20, 专注+15",
        ),

    ShopItem(
            id="model_gundam", name="高达模型", description="HG 1/144牛高达模型",
            price=98, category="toy", sub_type="",
            icon="🤖", rarity="rare",
            effect_desc="专注+15, 成就感+10",
        ),

    ShopItem(
            id="model_airplane", name="飞机模型", description="1:72战斗机拼装模型",
            price=120, category="toy", sub_type="",
            icon="✈️", rarity="rare",
            effect_desc="专注+12, 成就感+10",
        ),

    ShopItem(
            id="model_car_toy", name="合金车模", description="1:18合金跑车模型",
            price=168, category="toy", sub_type="",
            icon="🚗", rarity="rare",
            effect_desc="收藏+15, 心情+8",
        ),

    ShopItem(
            id="model_ship", name="帆船模型", description="木制帆船拼装模型",
            price=198, category="toy", sub_type="",
            icon="⛵", rarity="epic",
            effect_desc="专注+18, 耐心+15",
        ),

    ShopItem(
            id="figure_anime", name="动漫手办", description="1/7比例动漫手办",
            price=268, category="toy", sub_type="",
            icon="🎭", rarity="epic",
            effect_desc="收藏+20, 心情+15",
        ),

    ShopItem(
            id="figure_nendoroid", name="粘土人", description="Q版可动手办",
            price=88, category="toy", sub_type="",
            icon="🧙", rarity="rare",
            effect_desc="收藏+12, 心情+10",
        ),

    ShopItem(
            id="figure_funko", name="Funko Pop", description="大头娃娃收藏手办",
            price=78, category="toy", sub_type="",
            icon="🕺", rarity="rare",
            effect_desc="收藏+10, 心情+8",
        ),

    ShopItem(
            id="board_chess", name="国际象棋", description="木质国际象棋套装",
            price=85, category="toy", sub_type="",
            icon="♟️", rarity="rare",
            effect_desc="智力+12, 专注+10",
        ),

    ShopItem(
            id="board_go", name="围棋", description="云子围棋套装",
            price=120, category="toy", sub_type="",
            icon="⚫", rarity="rare",
            effect_desc="智力+15, 专注+12",
        ),

    ShopItem(
            id="board_monopoly", name="大富翁", description="经典大富翁桌游",
            price=68, category="toy", sub_type="",
            icon="🏘️", rarity="common",
            effect_desc="社交+10, 心情+8",
        ),

    ShopItem(
            id="board_uno", name="UNO", description="UNO卡牌游戏",
            price=25, category="toy", sub_type="",
            icon="🃏", rarity="common",
            effect_desc="社交+8, 心情+5",
        ),

    ShopItem(
            id="board_catan", name="卡坦岛", description="卡坦岛策略桌游",
            price=98, category="toy", sub_type="",
            icon="🏝️", rarity="rare",
            effect_desc="智力+10, 社交+12",
        ),

    ShopItem(
            id="cards_pokemon", name="宝可梦卡牌", description="宝可梦补充包",
            price=35, category="toy", sub_type="",
            icon="🃏", rarity="common",
            effect_desc="收藏+8, 心情+6",
        ),

    ShopItem(
            id="cards_yugioh", name="游戏王卡牌", description="游戏王卡组",
            price=48, category="toy", sub_type="",
            icon="🃏", rarity="common",
            effect_desc="收藏+8, 心情+6",
        ),

    ShopItem(
            id="ds_console", name="掌机", description="复古掌上游戏机",
            price=320, category="toy", sub_type="",
            icon="🎮", rarity="epic",
            effect_desc="心情+25, 放松+15",
        ),

    ShopItem(
            id="retro_console", name="复古主机", description="8位复古游戏主机",
            price=280, category="toy", sub_type="",
            icon="🕹️", rarity="epic",
            effect_desc="心情+20, 怀旧+15",
        ),

    ShopItem(
            id="arcade_machine", name="迷你街机", description="桌面迷你街机",
            price=180, category="toy", sub_type="",
            icon="🎰", rarity="rare",
            effect_desc="心情+15, 放松+12",
        ),

    ShopItem(
            id="drone_mini", name="迷你无人机", description="掌上迷你无人机",
            price=298, category="toy", sub_type="",
            icon="🚁", rarity="epic",
            effect_desc="心情+20, 探索+15",
        ),

    ShopItem(
            id="rc_car", name="遥控车", description="高速遥控越野车",
            price=168, category="toy", sub_type="",
            icon="🚙", rarity="rare",
            effect_desc="心情+12, 放松+10",
        ),

    ShopItem(
            id="rc_boat", name="遥控船", description="遥控快艇",
            price=138, category="toy", sub_type="",
            icon="🚤", rarity="rare",
            effect_desc="心情+10, 放松+8",
        ),

    ShopItem(
            id="kite", name="风筝", description="大号三角风筝",
            price=28, category="toy", sub_type="",
            icon="🪁", rarity="common",
            effect_desc="心情+6, 户外+8",
        ),

    ShopItem(
            id="yoyo", name="溜溜球", description="金属轴承溜溜球",
            price=45, category="toy", sub_type="",
            icon="🪀", rarity="common",
            effect_desc="技巧+8, 专注+6",
        ),

    ShopItem(
            id="spinning_top", name="陀螺", description="发光战斗陀螺",
            price=35, category="toy", sub_type="",
            icon="💫", rarity="common",
            effect_desc="心情+6, 竞技+5",
        ),

    ShopItem(
            id="slime", name="史莱姆", description="DIY史莱姆泥套装",
            price=22, category="toy", sub_type="",
            icon="🟢", rarity="common",
            effect_desc="解压+10, 放松+8",
        ),

    ShopItem(
            id="kinetic_sand", name="动力沙", description="彩色动力沙套装",
            price=38, category="toy", sub_type="",
            icon="🏖️", rarity="common",
            effect_desc="解压+8, 创造+6",
        ),

    ShopItem(
            id="bubble_machine", name="泡泡机", description="自动泡泡机",
            price=55, category="toy", sub_type="",
            icon="🫧", rarity="common",
            effect_desc="心情+10, 放松+8",
        ),

    ShopItem(
            id="water_gun", name="水枪", description="高压电动水枪",
            price=48, category="toy", sub_type="",
            icon="🔫", rarity="common",
            effect_desc="心情+8, 户外+8",
        ),

    ShopItem(
            id="frisbee", name="飞盘", description="专业运动飞盘",
            price=32, category="toy", sub_type="",
            icon="🥏", rarity="common",
            effect_desc="心情+6, 运动+8",
        ),

    ShopItem(
            id="darts", name="飞镖套装", description="磁吸安全飞镖套装",
            price=45, category="toy", sub_type="",
            icon="🎯", rarity="common",
            effect_desc="专注+8, 放松+6",
        ),

    ShopItem(
            id="table_tennis", name="便携乒乓球", description="便携乒乓球套装",
            price=58, category="toy", sub_type="",
            icon="🏓", rarity="common",
            effect_desc="运动+10, 心情+6",
        ),

    ShopItem(
            id="kendama", name="剑玉", description="日本传统剑玉",
            price=42, category="toy", sub_type="",
            icon="🪀", rarity="common",
            effect_desc="技巧+10, 专注+8",
        ),

    ShopItem(
            id="origami_set", name="折纸套装", description="千纸鹤折纸材料包",
            price=18, category="toy", sub_type="",
            icon="📄", rarity="common",
            effect_desc="创造+6, 专注+6",
        ),

    ShopItem(
            id="clay_set", name="粘土套装", description="超轻粘土DIY套装",
            price=28, category="toy", sub_type="",
            icon="🎨", rarity="common",
            effect_desc="创造+8, 放松+6",
        ),

    ShopItem(
            id="paint_by_numbers", name="数字油画", description="数字填色油画套装",
            price=45, category="toy", sub_type="",
            icon="🖼️", rarity="common",
            effect_desc="专注+10, 放松+8",
        ),

    ShopItem(
            id="crystal_growing", name="水晶种植", description="水晶生长实验套装",
            price=38, category="toy", sub_type="",
            icon="💎", rarity="common",
            effect_desc="探索+8, 耐心+6",
        ),

    ShopItem(
            id="ant_farm", name="蚂蚁工坊", description="透明蚂蚁观察巢",
            price=55, category="toy", sub_type="",
            icon="🐜", rarity="common",
            effect_desc="探索+10, 观察+8",
        ),

    ShopItem(
            id="telescope_mini", name="迷你望远镜", description="便携天文望远镜",
            price=168, category="toy", sub_type="",
            icon="🔭", rarity="rare",
            effect_desc="探索+15, 心情+10",
        ),

    ShopItem(
            id="microscope", name="显微镜", description="儿童科学显微镜",
            price=138, category="toy", sub_type="",
            icon="🔬", rarity="rare",
            effect_desc="探索+12, 专注+10",
        ),

    ShopItem(
            id="rc_robot", name="遥控机器人", description="可编程遥控机器人",
            price=258, category="toy", sub_type="",
            icon="🤖", rarity="epic",
            effect_desc="创造力+18, 专注+15",
        ),

]
