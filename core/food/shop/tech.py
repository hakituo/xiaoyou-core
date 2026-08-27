# -*- coding: utf-8 -*-
"""商城-tech 类商品。"""
from core.food.models import ShopItem

TECH: list[ShopItem] = [
    ShopItem(id="smartphone_flagship", name="旗舰手机", description="最新旗舰5G智能手机", price=6999, category="tech", sub_type="", icon="📱", rarity="epic", effect_desc="科技+20, 生活+10"),

    ShopItem(id="smartphone_fold", name="折叠屏手机", description="未来感折叠屏手机", price=9999, category="tech", sub_type="", icon="📱", rarity="legendary", effect_desc="科技+25, 潮流+15"),

    ShopItem(id="tablet_pro", name="平板电脑", description="12.9寸专业绘图平板", price=5888, category="tech", sub_type="", icon="📋", rarity="epic", effect_desc="效率+15, 创作+10"),

    ShopItem(id="laptop_thin", name="轻薄笔记本", description="1kg超轻薄笔记本", price=8888, category="tech", sub_type="", icon="💻", rarity="epic", effect_desc="效率+18, 科技+10"),

    ShopItem(id="laptop_gaming", name="游戏笔记本", description="RTX4090游戏本", price=15999, category="tech", sub_type="", icon="💻", rarity="legendary", effect_desc="游戏+20, 科技+15"),

    ShopItem(id="smartwatch_pro", name="智能手表Pro", description="钛合金智能运动手表", price=2999, category="tech", sub_type="", icon="⌚", rarity="epic", effect_desc="健康+15, 科技+10"),

    ShopItem(id="smartwatch_se", name="智能手表SE", description="性价比智能手表", price=1599, category="tech", sub_type="", icon="⌚", rarity="rare", effect_desc="健康+10, 科技+8"),

    ShopItem(id="earbuds_pro", name="降噪耳机", description="主动降噪真无线耳机", price=1299, category="tech", sub_type="", icon="🎧", rarity="rare", effect_desc="专注+12, 放松+8"),

    ShopItem(id="earbuds_max", name="头戴耳机", description="空间音频头戴耳机", price=3999, category="tech", sub_type="", icon="🎧", rarity="epic", effect_desc="专注+15, 沉浸+12"),

    ShopItem(id="speaker_smart", name="智能音箱", description="高保真智能音箱", price=899, category="tech", sub_type="", icon="🔊", rarity="rare", effect_desc="生活+10, 科技+8"),

    ShopItem(id="speaker_portable", name="便携蓝牙音箱", description="防水便携音箱", price=399, category="tech", sub_type="", icon="🔊", rarity="common", effect_desc="心情+8, 户外+6"),

    ShopItem(id="keyboard_mech", name="机械键盘", description="客制化机械键盘", price=699, category="tech", sub_type="", icon="⌨️", rarity="rare", effect_desc="效率+10, 专注+8"),

    ShopItem(id="mouse_gaming", name="游戏鼠标", description="16000DPI游戏鼠标", price=499, category="tech", sub_type="", icon="🖱️", rarity="rare", effect_desc="游戏+10, 精准+8"),

    ShopItem(id="monitor_4k", name="4K显示器", description="32寸4K专业显示器", price=3999, category="tech", sub_type="", icon="🖥️", rarity="epic", effect_desc="效率+15, 视觉+12"),

    ShopItem(id="monitor_curved", name="曲面显示器", description="49寸超宽曲面屏", price=5999, category="tech", sub_type="", icon="🖥️", rarity="epic", effect_desc="沉浸+18, 效率+12"),

    ShopItem(id="camera_mirrorless", name="微单相机", description="全画幅微单套机", price=12888, category="tech", sub_type="", icon="📷", rarity="legendary", effect_desc="审美+20, 创作+15"),

    ShopItem(id="camera_compact", name="卡片相机", description="便携大底卡片机", price=3999, category="tech", sub_type="", icon="📷", rarity="epic", effect_desc="审美+12, 旅行+10"),

    ShopItem(id="camera_action", name="运动相机", description="4K防水运动相机", price=1999, category="tech", sub_type="", icon="📷", rarity="rare", effect_desc="运动+12, 户外+10"),

    ShopItem(id="drone_pro", name="航拍无人机", description="8K航拍无人机", price=6888, category="tech", sub_type="", icon="🚁", rarity="epic", effect_desc="探索+18, 创作+15"),

    ShopItem(id="projector_home", name="家用投影仪", description="4K激光投影仪", price=5999, category="tech", sub_type="", icon="📽️", rarity="epic", effect_desc="沉浸+15, 家庭+10"),

    ShopItem(id="projector_portable", name="便携投影仪", description="口袋投影仪", price=1299, category="tech", sub_type="", icon="📽️", rarity="rare", effect_desc="心情+10, 旅行+8"),

    ShopItem(id="vr_headset", name="VR头显", description="4K VR一体机", price=2999, category="tech", sub_type="", icon="🥽", rarity="epic", effect_desc="沉浸+20, 科技+12"),

    ShopItem(id="console_ps5", name="游戏主机", description="次世代游戏主机", price=3999, category="tech", sub_type="", icon="🎮", rarity="epic", effect_desc="心情+20, 放松+15"),

    ShopItem(id="console_switch", name="掌机主机", description="掌上游戏主机", price=2399, category="tech", sub_type="", icon="🎮", rarity="rare", effect_desc="心情+15, 社交+10"),

    ShopItem(id="console_handheld", name="掌机PC", description="掌上PC游戏机", price=4999, category="tech", sub_type="", icon="🎮", rarity="epic", effect_desc="心情+18, 科技+10"),

    ShopItem(id="charger_wireless", name="无线充电器", description="15W快充无线充电板", price=199, category="tech", sub_type="", icon="🔌", rarity="common", effect_desc="便利+8"),

    ShopItem(id="charger_gan", name="氮化镓充电器", description="100W氮化镓四口充电器", price=299, category="tech", sub_type="", icon="🔌", rarity="common", effect_desc="效率+8, 科技+5"),

    ShopItem(id="powerbank_mag", name="磁吸充电宝", description="磁吸无线充电宝", price=199, category="tech", sub_type="", icon="🔋", rarity="common", effect_desc="便利+8, 出行+6"),

    ShopItem(id="powerbank_big", name="大容量充电宝", description="30000mAh充电宝", price=259, category="tech", sub_type="", icon="🔋", rarity="common", effect_desc="出行+10, 安全感+8"),

    ShopItem(id="hub_usb", name="扩展坞", description="11合1TypeC扩展坞", price=199, category="tech", sub_type="", icon="🔌", rarity="common", effect_desc="效率+6, 便利+6"),

    ShopItem(id="ssd_external", name="移动固态硬盘", description="1TB移动SSD", price=599, category="tech", sub_type="", icon="💾", rarity="rare", effect_desc="效率+10"),

    ShopItem(id="nas_home", name="家用NAS", description="4盘位家用NAS", price=2999, category="tech", sub_type="", icon="💽", rarity="epic", effect_desc="效率+15, 科技+10"),

    ShopItem(id="router_wifi7", name="WiFi7路由器", description="三频WiFi7路由器", price=1599, category="tech", sub_type="", icon="📡", rarity="rare", effect_desc="效率+10, 科技+8"),

    ShopItem(id="robot_vacuum", name="扫地机器人", description="自动集尘扫地机器人", price=2999, category="tech", sub_type="", icon="🤖", rarity="epic", effect_desc="便利+18, 生活+12"),

    ShopItem(id="robot_mop", name="拖地机器人", description="仿生拖地机器人", price=3999, category="tech", sub_type="", icon="🤖", rarity="epic", effect_desc="便利+20, 生活+15"),

    ShopItem(id="air_purifier", name="空气净化器", description="智能空气净化器", price=1599, category="tech", sub_type="", icon="🌬️", rarity="rare", effect_desc="健康+12, 生活+8"),

    ShopItem(id="humidifier", name="加湿器", description="智能恒湿加湿器", price=399, category="tech", sub_type="", icon="💧", rarity="common", effect_desc="健康+8, 舒适+6"),

    ShopItem(id="electric_toothbrush", name="电动牙刷", description="声波电动牙刷", price=299, category="tech", sub_type="", icon="🪥", rarity="common", effect_desc="健康+8"),

    ShopItem(id="water_flosser", name="冲牙器", description="便携冲牙器", price=199, category="tech", sub_type="", icon="🚿", rarity="common", effect_desc="健康+6"),

    ShopItem(id="hair_dryer", name="高速吹风机", description="10万转高速吹风机", price=1599, category="tech", sub_type="", icon="💨", rarity="rare", effect_desc="生活+10, 心情+6"),

    ShopItem(id="rice_cooker", name="电饭煲", description="IH压力电饭煲", price=899, category="tech", sub_type="", icon="🍚", rarity="rare", effect_desc="生活+10, 美食+8"),

    ShopItem(id="coffee_machine", name="咖啡机", description="全自动意式咖啡机", price=2999, category="tech", sub_type="", icon="☕", rarity="epic", effect_desc="生活+15, 心情+10"),

    ShopItem(id="oven_steam", name="蒸烤箱", description="嵌入式蒸烤箱", price=3999, category="tech", sub_type="", icon="🍳", rarity="epic", effect_desc="生活+15, 美食+10"),

    ShopItem(id="dishwasher", name="洗碗机", description="台式免安装洗碗机", price=1999, category="tech", sub_type="", icon="🍽️", rarity="rare", effect_desc="便利+15, 生活+10"),

    ShopItem(id="electric_kettle", name="电水壶", description="恒温电水壶", price=199, category="tech", sub_type="", icon="🫖", rarity="common", effect_desc="便利+6, 生活+4"),

    ShopItem(id="air_fryer", name="空气炸锅", description="无油空气炸锅", price=399, category="tech", sub_type="", icon="🍟", rarity="common", effect_desc="美食+8, 生活+6"),

    ShopItem(id="soy_milk_maker", name="破壁机", description="多功能破壁料理机", price=599, category="tech", sub_type="", icon="🥤", rarity="rare", effect_desc="美食+10, 生活+8"),

    ShopItem(id="smart_light", name="智能灯泡", description="彩色智能灯泡套装", price=199, category="tech", sub_type="", icon="💡", rarity="common", effect_desc="氛围+8, 科技+5"),

    ShopItem(id="smart_curtain", name="智能窗帘", description="电动智能窗帘电机", price=599, category="tech", sub_type="", icon="🪟", rarity="rare", effect_desc="便利+10, 科技+6"),

    ShopItem(id="smart_door_lock", name="智能门锁", description="3D人脸智能门锁", price=1999, category="tech", sub_type="", icon="🔐", rarity="epic", effect_desc="安全+15, 便利+10"),

    ShopItem(id="smart_scale", name="体脂秤", description="蓝牙体脂秤", price=159, category="tech", sub_type="", icon="⚖️", rarity="common", effect_desc="健康+8, 科技+4"),

    ShopItem(id="fitness_band", name="手环", description="AMOLED智能手环", price=299, category="tech", sub_type="", icon="⌚", rarity="common", effect_desc="健康+8, 科技+5"),

    ShopItem(id="translator_pen", name="翻译笔", description="多语言翻译笔", price=599, category="tech", sub_type="", icon="✒️", rarity="rare", effect_desc="学习+10, 旅行+8"),

    ShopItem(id="e_reader", name="电子书阅读器", description="300ppi电子墨水阅读器", price=999, category="tech", sub_type="", icon="📖", rarity="rare", effect_desc="阅读+15, 护眼+10"),

    ShopItem(id="recorder_pen", name="录音笔", description="智能录音笔", price=399, category="tech", sub_type="", icon="🎤", rarity="common", effect_desc="效率+8, 学习+6"),

    ShopItem(id="calculator_pro", name="科学计算器", description="可编程科学计算器", price=299, category="tech", sub_type="", icon="🧮", rarity="common", effect_desc="学习+8, 计算+10"),

    ShopItem(id="math_input_pen", name="手写板", description="USB手写输入板", price=199, category="tech", sub_type="", icon="✍️", rarity="common", effect_desc="学习+6, 效率+5"),

    ShopItem(id="ring_smart", name="智能戒指", description="健康监测智能戒指", price=1999, category="tech", sub_type="", icon="💍", rarity="epic", effect_desc="健康+12, 科技+10"),

    ShopItem(id="glasses_smart", name="智能眼镜", description="AR智能眼镜", price=4999, category="tech", sub_type="", icon="👓", rarity="epic", effect_desc="科技+18, 未来+15"),

]
