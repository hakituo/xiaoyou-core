# -*- coding: utf-8 -*-
"""商城-gift 类商品。"""
from core.food.models import ShopItem

GIFTS: list[ShopItem] = [
    ShopItem(
            id="red_rose", name="红玫瑰", description="热烈而经典的红玫瑰，永恒的爱意表达",
            price=50, category="gift", sub_type="",
            icon="🌹", rarity="common",
            effect_desc="送礼时心情值+10",
        ),

    ShopItem(
            id="pink_rose", name="粉玫瑰", description="温柔甜蜜的粉玫瑰，初恋般的悸动",
            price=45, category="gift", sub_type="",
            icon="🌸", rarity="common",
            effect_desc="送礼时心情值+8",
        ),

    ShopItem(
            id="white_rose", name="白玫瑰", description="纯洁无瑕的白玫瑰，真挚的祝福",
            price=48, category="gift", sub_type="",
            icon="🤍", rarity="common",
            effect_desc="送礼时心情值+8",
        ),

    ShopItem(
            id="sunflower", name="向日葵", description="阳光灿烂的向日葵，温暖又充满希望",
            price=35, category="gift", sub_type="",
            icon="🌻", rarity="common",
            effect_desc="送礼时心情值+6",
        ),

    ShopItem(
            id="lily", name="百合花", description="高雅淡然的百合，纯洁与优雅的象征",
            price=40, category="gift", sub_type="",
            icon="💐", rarity="common",
            effect_desc="送礼时心情值+7",
        ),

    ShopItem(
            id="tulip", name="郁金香", description="高贵典雅的郁金香，完美的爱的告白",
            price=42, category="gift", sub_type="",
            icon="🌷", rarity="common",
            effect_desc="送礼时心情值+7",
        ),

    ShopItem(
            id="carnation", name="康乃馨", description="温馨感恩的康乃馨，母爱般的温暖",
            price=30, category="gift", sub_type="",
            icon="🌼", rarity="common",
            effect_desc="送礼时心情值+5",
        ),

    ShopItem(
            id="lavender", name="薰衣草", description="宁静安神的薰衣草，紫色浪漫花海",
            price=38, category="gift", sub_type="",
            icon="💜", rarity="common",
            effect_desc="送礼时心情值+6, 压力-5",
        ),

    ShopItem(
            id="daisy", name="雏菊", description="天真烂漫的雏菊，藏在心底的爱意",
            price=25, category="gift", sub_type="",
            icon="🌸", rarity="common",
            effect_desc="送礼时心情值+4",
        ),

    ShopItem(
            id="orchid", name="兰花", description="清幽脱俗的兰花，高洁与典雅的代表",
            price=80, category="gift", sub_type="",
            icon="🌺", rarity="rare",
            effect_desc="送礼时心情值+12",
        ),

    ShopItem(
            id="bouquet_mixed", name="混搭花束", description="精心搭配的混搭花束，每一朵都是心意",
            price=120, category="gift", sub_type="",
            icon="💐", rarity="rare",
            effect_desc="送礼时心情值+15",
        ),

    ShopItem(
            id="bouquet_99", name="九十九朵玫瑰", description="九十九朵玫瑰，天长地久的承诺",
            price=520, category="gift", sub_type="",
            icon="💝", rarity="epic",
            effect_desc="送礼时心情值+30, 好感度+5",
        ),

    ShopItem(
            id="chocolate_box", name="巧克力礼盒", description="精美包装的进口巧克力礼盒",
            price=88, category="gift", sub_type="",
            icon="🍫", rarity="common",
            effect_desc="送礼时心情值+10",
        ),

    ShopItem(
            id="handmade_chocolate", name="手工巧克力", description="亲手制作的巧克力，满满的心意",
            price=66, category="gift", sub_type="",
            icon="🍫", rarity="common",
            effect_desc="送礼时心情值+12",
        ),

    ShopItem(
            id="macaron_gift_box", name="马卡龙礼盒", description="色彩缤纷的法式马卡龙礼盒",
            price=128, category="gift", sub_type="",
            icon="🫧", rarity="rare",
            effect_desc="送礼时心情值+13",
        ),

    ShopItem(
            id="necklace_pearl", name="珍珠项链", description="圆润光泽的淡水珍珠项链",
            price=380, category="gift", sub_type="",
            icon="📿", rarity="epic",
            effect_desc="送礼时心情值+25, 好感度+3",
        ),

    ShopItem(
            id="necklace_crystal", name="水晶项链", description="璀璨水晶吊坠项链",
            price=280, category="gift", sub_type="",
            icon="💎", rarity="rare",
            effect_desc="送礼时心情值+18",
        ),

    ShopItem(
            id="bracelet_silver", name="银手链", description="简约精致的925银手链",
            price=150, category="gift", sub_type="",
            icon="⛓️", rarity="rare",
            effect_desc="送礼时心情值+15",
        ),

    ShopItem(
            id="bracelet_charm", name="串饰手链", description="可自由搭配串饰的手链",
            price=200, category="gift", sub_type="",
            icon="✨", rarity="rare",
            effect_desc="送礼时心情值+16",
        ),

    ShopItem(
            id="earrings_pearl", name="珍珠耳环", description="优雅的淡水珍珠耳环",
            price=120, category="gift", sub_type="",
            icon="💎", rarity="common",
            effect_desc="送礼时心情值+10",
        ),

    ShopItem(
            id="ring_silver", name="银戒指", description="简约设计的925银戒指",
            price=180, category="gift", sub_type="",
            icon="💍", rarity="rare",
            effect_desc="送礼时心情值+16",
        ),

    ShopItem(
            id="hairpin_crystal", name="水晶发簪", description="流光溢彩的水晶发簪",
            price=95, category="gift", sub_type="",
            icon="📋", rarity="common",
            effect_desc="送礼时心情值+10",
        ),

    ShopItem(
            id="music_box", name="八音盒", description="复古旋转木马八音盒",
            price=160, category="gift", sub_type="",
            icon="🎵", rarity="rare",
            effect_desc="送礼时心情值+18, 放松+10",
        ),

    ShopItem(
            id="photo_album", name="手工相册", description="可以自己DIY的手工相册",
            price=55, category="gift", sub_type="",
            icon="📷", rarity="common",
            effect_desc="送礼时心情值+10",
        ),

    ShopItem(
            id="polaroid_camera", name="拍立得相机", description="即拍即得的拍立得相机",
            price=320, category="gift", sub_type="",
            icon="📸", rarity="epic",
            effect_desc="送礼时心情值+25",
        ),

    ShopItem(
            id="plush_giant_gift", name="巨型抱抱熊", description="一米二的超大毛绒熊",
            price=260, category="gift", sub_type="",
            icon="🧸", rarity="rare",
            effect_desc="送礼时心情值+22, 安全感+15",
        ),

    ShopItem(
            id="handwrite_letter", name="手写信", description="亲笔书写的信，最朴实的浪漫",
            price=5, category="gift", sub_type="",
            icon="✉️", rarity="common",
            effect_desc="送礼时心情值+15, 好感度+2",
        ),

    ShopItem(
            id="scrapbook", name="手工剪贴本", description="记录美好回忆的剪贴本",
            price=45, category="gift", sub_type="",
            icon="📖", rarity="common",
            effect_desc="送礼时心情值+8",
        ),

    ShopItem(
            id="custom_puzzle_gift", name="定制拼图", description="用照片定制的拼图",
            price=78, category="gift", sub_type="",
            icon="🧩", rarity="common",
            effect_desc="送礼时心情值+10",
        ),

    ShopItem(
            id="star_map", name="星空图", description="定制某天星空的装饰画",
            price=130, category="gift", sub_type="",
            icon="✨", rarity="rare",
            effect_desc="送礼时心情值+14",
        ),

    ShopItem(
            id="moon_lamp", name="月球灯", description="3D打印月球造型夜灯",
            price=110, category="gift", sub_type="",
            icon="🌙", rarity="rare",
            effect_desc="送礼时心情值+12, 助眠+8",
        ),

    ShopItem(
            id="galaxy_projector", name="星空投影灯", description="房间秒变星空的投影灯",
            price=145, category="gift", sub_type="",
            icon="🌌", rarity="rare",
            effect_desc="送礼时心情值+15, 放松+12",
        ),

    ShopItem(
            id="essential_oil_set", name="精油套装", description="薰衣草甜橙茶树精油套装",
            price=90, category="gift", sub_type="",
            icon="🌸", rarity="common",
            effect_desc="送礼时心情值+10, 放松+10",
        ),

    ShopItem(
            id="bath_bomb_set", name="沐浴球套装", description="多彩泡泡浴球套装",
            price=65, category="gift", sub_type="",
            icon="🛁", rarity="common",
            effect_desc="送礼时心情值+8, 放松+8",
        ),

    ShopItem(
            id="scented_candle", name="香薰蜡烛", description="天然大豆香薰蜡烛",
            price=48, category="gift", sub_type="",
            icon="🕯️", rarity="common",
            effect_desc="送礼时心情值+7, 放松+6",
        ),

    ShopItem(
            id="hand_cream_set", name="护手霜套装", description="滋润保湿护手霜三支装",
            price=58, category="gift", sub_type="",
            icon="🧴", rarity="common",
            effect_desc="送礼时心情值+7",
        ),

    ShopItem(
            id="lip_balm_set", name="润唇膏套装", description="天然滋润润唇膏礼盒",
            price=42, category="gift", sub_type="",
            icon="💄", rarity="common",
            effect_desc="送礼时心情值+6",
        ),

    ShopItem(
            id="tea_gift_box", name="茶叶礼盒", description="精选龙井大红袍白茶礼盒",
            price=138, category="gift", sub_type="",
            icon="🍵", rarity="rare",
            effect_desc="送礼时心情值+12",
        ),

    ShopItem(
            id="coffee_bean_gift", name="咖啡豆礼盒", description="精选手冲咖啡豆礼盒",
            price=115, category="gift", sub_type="",
            icon="☕", rarity="rare",
            effect_desc="送礼时心情值+12",
        ),

    ShopItem(
            id="wine_red", name="红酒", description="法国进口波尔多红酒",
            price=298, category="gift", sub_type="",
            icon="🍷", rarity="epic",
            effect_desc="送礼时心情值+20",
        ),

    ShopItem(
            id="sake_japanese", name="日本清酒", description="纯米大吟酿清酒",
            price=268, category="gift", sub_type="",
            icon="🍶", rarity="epic",
            effect_desc="送礼时心情值+18",
        ),

    ShopItem(
            id="keychain_custom", name="定制钥匙扣", description="刻字定制情侣钥匙扣",
            price=28, category="gift", sub_type="",
            icon="🔑", rarity="common",
            effect_desc="送礼时心情值+5",
        ),

    ShopItem(
            id="phone_case_custom", name="定制手机壳", description="照片定制手机壳",
            price=55, category="gift", sub_type="",
            icon="📱", rarity="common",
            effect_desc="送礼时心情值+7",
        ),

    ShopItem(
            id="bookmark_metal", name="金属书签", description="古风金属镂空书签",
            price=35, category="gift", sub_type="",
            icon="🔖", rarity="common",
            effect_desc="送礼时心情值+5",
        ),

    ShopItem(
            id="pen_fountain", name="钢笔", description="凌美钢笔礼盒装",
            price=180, category="gift", sub_type="",
            icon="🖊️", rarity="rare",
            effect_desc="送礼时心情值+15",
        ),

    ShopItem(
            id="notebook_leather", name="真皮笔记本", description="意大利真皮封面笔记本",
            price=128, category="gift", sub_type="",
            icon="📓", rarity="rare",
            effect_desc="送礼时心情值+12",
        ),

    ShopItem(
            id="wallet_leather", name="真皮钱包", description="手工制作真皮短款钱包",
            price=220, category="gift", sub_type="",
            icon="👛", rarity="rare",
            effect_desc="送礼时心情值+18",
        ),

    ShopItem(
            id="watch_couple", name="情侣手表", description="简约情侣对表",
            price=520, category="gift", sub_type="",
            icon="⌚", rarity="epic",
            effect_desc="送礼时心情值+28, 好感度+3",
        ),

    ShopItem(
            id="scarf_cashmere", name="羊绒围巾", description="100%山羊绒围巾",
            price=260, category="gift", sub_type="",
            icon="🧣", rarity="rare",
            effect_desc="送礼时心情值+18",
        ),

    ShopItem(
            id="glasses_chain", name="眼镜链", description="复古珍珠眼镜链",
            price=45, category="gift", sub_type="",
            icon="👓", rarity="common",
            effect_desc="送礼时心情值+6",
        ),

    ShopItem(
            id="hand_mirror_vintage", name="复古手持镜", description="欧式复古雕花手持镜",
            price=88, category="gift", sub_type="",
            icon="🪞", rarity="rare",
            effect_desc="送礼时心情值+10",
        ),

    ShopItem(
            id="music_crystal", name="音乐水晶球", description="旋转发条水晶雪花球",
            price=95, category="gift", sub_type="",
            icon="🔮", rarity="common",
            effect_desc="送礼时心情值+10",
        ),

    ShopItem(
            id="dream_catcher", name="捕梦网", description="手工编织羽毛捕梦网",
            price=42, category="gift", sub_type="",
            icon="🪶", rarity="common",
            effect_desc="送礼时心情值+7, 助眠+5",
        ),

    ShopItem(
            id="wind_chime", name="风铃", description="日式玻璃风铃",
            price=58, category="gift", sub_type="",
            icon="🎐", rarity="common",
            effect_desc="送礼时心情值+8, 放松+6",
        ),

    ShopItem(
            id="terracotta_pot", name="多肉盆栽", description="手工陶盆多肉植物",
            price=35, category="gift", sub_type="",
            icon="🪴", rarity="common",
            effect_desc="送礼时心情值+6",
        ),

    ShopItem(
            id="bonsai", name="迷你盆景", description="日式桧柏迷你盆景",
            price=150, category="gift", sub_type="",
            icon="🌳", rarity="rare",
            effect_desc="送礼时心情值+14, 放松+10",
        ),

    ShopItem(
            id="lucky_cat", name="招财猫", description="招财招福招财猫摆件",
            price=68, category="gift", sub_type="",
            icon="🐱", rarity="common",
            effect_desc="送礼时心情值+8",
        ),

    ShopItem(
            id="music_box_wood", name="木制音乐盒", description="胡桃木手摇音乐盒",
            price=130, category="gift", sub_type="",
            icon="🎶", rarity="rare",
            effect_desc="送礼时心情值+14",
        ),

    ShopItem(
            id="coupon_book", name="兑换券本", description="自制各种特权兑换券",
            price=10, category="gift", sub_type="",
            icon="🎫", rarity="common",
            effect_desc="送礼时心情值+20, 好感度+3",
        ),

]
