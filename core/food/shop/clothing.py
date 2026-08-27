# -*- coding: utf-8 -*-
"""商城-clothing 类商品。"""
from core.food.models import ShopItem

CLOTHING: list[ShopItem] = [
    ShopItem(
            id="dress_floral", name="碎花连衣裙", description="清新碎花雪纺连衣裙",
            price=128, category="clothing", sub_type="",
            icon="👗", rarity="rare",
            effect_desc="心情+10, 自信+8",
        ),

    ShopItem(
            id="dress_black", name="黑色小礼裙", description="经典赫本风小黑裙",
            price=168, category="clothing", sub_type="",
            icon="🖤", rarity="rare",
            effect_desc="心情+12, 自信+10",
        ),

    ShopItem(
            id="dress_white", name="白色蕾丝裙", description="纯白蕾丝公主裙",
            price=158, category="clothing", sub_type="",
            icon="🤍", rarity="rare",
            effect_desc="心情+10, 自信+8",
        ),

    ShopItem(
            id="dress_knitted", name="针织连衣裙", description="温暖高领针织裙",
            price=138, category="clothing", sub_type="",
            icon="🧶", rarity="rare",
            effect_desc="心情+8, 温暖+10",
        ),

    ShopItem(
            id="dress_pleated_c", name="百褶裙", description="学院风百褶短裙",
            price=88, category="clothing", sub_type="",
            icon="👗", rarity="common",
            effect_desc="心情+8, 自信+6",
        ),

    ShopItem(
            id="top_hoodie", name="连帽卫衣", description="oversize宽松连帽卫衣",
            price=98, category="clothing", sub_type="",
            icon="👕", rarity="common",
            effect_desc="舒适+10, 休闲+8",
        ),

    ShopItem(
            id="top_sweater", name="毛衣", description="粗针织宽松毛衣",
            price=118, category="clothing", sub_type="",
            icon="🧶", rarity="rare",
            effect_desc="温暖+12, 舒适+10",
        ),

    ShopItem(
            id="top_blouse", name="雪纺衬衫", description="法式翻领雪纺衬衫",
            price=88, category="clothing", sub_type="",
            icon="👚", rarity="common",
            effect_desc="心情+6, 自信+6",
        ),

    ShopItem(
            id="top_tshirt", name="印花T恤", description="原创插画印花T恤",
            price=58, category="clothing", sub_type="",
            icon="👕", rarity="common",
            effect_desc="休闲+8, 心情+5",
        ),

    ShopItem(
            id="top_croptee", name="短款T恤", description="夏日短款露脐T恤",
            price=48, category="clothing", sub_type="",
            icon="👕", rarity="common",
            effect_desc="自信+6, 心情+5",
        ),

    ShopItem(
            id="top_cardigan", name="开衫毛衣", description="慵懒风长款针织开衫",
            price=108, category="clothing", sub_type="",
            icon="🧥", rarity="rare",
            effect_desc="温暖+10, 舒适+8",
        ),

    ShopItem(
            id="top_blazer", name="西装外套", description="修身小西装外套",
            price=168, category="clothing", sub_type="",
            icon="🤵", rarity="rare",
            effect_desc="自信+12, 气质+8",
        ),

    ShopItem(
            id="top_parka", name="派克大衣", description="保暖连帽派克大衣",
            price=288, category="clothing", sub_type="",
            icon="🧥", rarity="epic",
            effect_desc="温暖+18, 自信+10",
        ),

    ShopItem(
            id="top_down", name="羽绒服", description="轻量90%白鹅绒羽绒服",
            price=388, category="clothing", sub_type="",
            icon="🧥", rarity="epic",
            effect_desc="温暖+20",
        ),

    ShopItem(
            id="top_windbreaker", name="冲锋衣", description="三合一防水冲锋衣",
            price=258, category="clothing", sub_type="",
            icon="🧥", rarity="rare",
            effect_desc="温暖+12, 户外+10",
        ),

    ShopItem(
            id="bottom_jeans", name="牛仔裤", description="高弹力修身牛仔裤",
            price=128, category="clothing", sub_type="",
            icon="👖", rarity="rare",
            effect_desc="自信+8, 日常+6",
        ),

    ShopItem(
            id="bottom_plaid", name="格纹裙", description="苏格兰格纹半身裙",
            price=88, category="clothing", sub_type="",
            icon="👗", rarity="common",
            effect_desc="心情+6, 气质+5",
        ),

    ShopItem(
            id="bottom_shorts", name="牛仔短裤", description="高腰毛边牛仔短裤",
            price=68, category="clothing", sub_type="",
            icon="🩳", rarity="common",
            effect_desc="自信+6, 心情+5",
        ),

    ShopItem(
            id="bottom_wide_pants", name="阔腿裤", description="垂感高腰阔腿裤",
            price=98, category="clothing", sub_type="",
            icon="👖", rarity="rare",
            effect_desc="气质+8, 舒适+8",
        ),

    ShopItem(
            id="bottom_pleated_skirt", name="百褶半身裙", description="金属色百褶半身裙",
            price=88, category="clothing", sub_type="",
            icon="✨", rarity="common",
            effect_desc="心情+8, 气质+6",
        ),

    ShopItem(
            id="shoes_sneakers", name="运动鞋", description="轻量透气跑步鞋",
            price=168, category="clothing", sub_type="",
            icon="👟", rarity="rare",
            effect_desc="舒适+10, 运动+8",
        ),

    ShopItem(
            id="shoes_canvas", name="帆布鞋", description="经典高帮帆布鞋",
            price=88, category="clothing", sub_type="",
            icon="👟", rarity="common",
            effect_desc="休闲+8, 心情+5",
        ),

    ShopItem(
            id="shoes_boots", name="马丁靴", description="英伦风切尔西短靴",
            price=228, category="clothing", sub_type="",
            icon="👢", rarity="rare",
            effect_desc="自信+10, 气质+8",
        ),

    ShopItem(
            id="shoes_heels", name="高跟鞋", description="尖头细跟高跟鞋",
            price=188, category="clothing", sub_type="",
            icon="👠", rarity="rare",
            effect_desc="自信+12, 气质+10",
        ),

    ShopItem(
            id="shoes_flats", name="平底鞋", description="芭蕾风平底单鞋",
            price=98, category="clothing", sub_type="",
            icon="🥿", rarity="common",
            effect_desc="舒适+8, 日常+5",
        ),

    ShopItem(
            id="shoes_loafers", name="乐福鞋", description="复古乐福鞋",
            price=128, category="clothing", sub_type="",
            icon="👞", rarity="rare",
            effect_desc="气质+8, 舒适+6",
        ),

    ShopItem(
            id="shoes_slippers", name="毛绒拖鞋", description="可爱动物毛绒拖鞋",
            price=38, category="clothing", sub_type="",
            icon="🥿", rarity="common",
            effect_desc="舒适+8, 心情+5",
        ),

    ShopItem(
            id="shoes_platform", name="厚底鞋", description="厚底玛丽珍鞋",
            price=148, category="clothing", sub_type="",
            icon="👟", rarity="rare",
            effect_desc="自信+8, 心情+6",
        ),

    ShopItem(
            id="bag_tote", name="托特包", description="帆布大容量托特包",
            price=68, category="clothing", sub_type="",
            icon="👜", rarity="common",
            effect_desc="实用+8, 日常+6",
        ),

    ShopItem(
            id="bag_crossbody", name="斜挎包", description="迷你链条斜挎包",
            price=128, category="clothing", sub_type="",
            icon="👜", rarity="rare",
            effect_desc="心情+8, 气质+6",
        ),

    ShopItem(
            id="bag_backpack", name="双肩包", description="简约帆布双肩包",
            price=88, category="clothing", sub_type="",
            icon="🎒", rarity="common",
            effect_desc="实用+8, 日常+6",
        ),

    ShopItem(
            id="bag_clutch", name="手拿包", description="亮片晚宴手拿包",
            price=98, category="clothing", sub_type="",
            icon="👛", rarity="rare",
            effect_desc="气质+10, 心情+6",
        ),

    ShopItem(
            id="bag_bucket", name="水桶包", description="皮质抽绳水桶包",
            price=148, category="clothing", sub_type="",
            icon="👜", rarity="rare",
            effect_desc="心情+8, 气质+8",
        ),

    ShopItem(
            id="bag_clear", name="透明包", description="PVC透明果冻包",
            price=58, category="clothing", sub_type="",
            icon="👜", rarity="common",
            effect_desc="心情+6, 潮流+5",
        ),

    ShopItem(
            id="hat_beanie", name="毛线帽", description="粗针织毛线帽",
            price=38, category="clothing", sub_type="",
            icon="🧢", rarity="common",
            effect_desc="温暖+8, 心情+4",
        ),

    ShopItem(
            id="hat_beret", name="贝雷帽", description="法式羊毛贝雷帽",
            price=58, category="clothing", sub_type="",
            icon="🎩", rarity="common",
            effect_desc="气质+8, 心情+6",
        ),

    ShopItem(
            id="hat_bucket", name="渔夫帽", description="防晒宽檐渔夫帽",
            price=42, category="clothing", sub_type="",
            icon="🧢", rarity="common",
            effect_desc="实用+6, 休闲+5",
        ),

    ShopItem(
            id="hat_straw", name="草帽", description="编织宽檐草帽",
            price=35, category="clothing", sub_type="",
            icon="👒", rarity="common",
            effect_desc="心情+5, 户外+5",
        ),

    ShopItem(
            id="hat_baseball", name="棒球帽", description="简约刺绣棒球帽",
            price=45, category="clothing", sub_type="",
            icon="🧢", rarity="common",
            effect_desc="休闲+6, 日常+4",
        ),

    ShopItem(
            id="scarf_wool", name="羊毛围巾", description="格纹羊毛围巾",
            price=68, category="clothing", sub_type="",
            icon="🧣", rarity="common",
            effect_desc="温暖+10, 心情+5",
        ),

    ShopItem(
            id="scarf_silk", name="丝巾", description="复古真丝丝巾",
            price=88, category="clothing", sub_type="",
            icon="🧣", rarity="rare",
            effect_desc="气质+10, 心情+6",
        ),

    ShopItem(
            id="gloves_leather", name="皮手套", description="触屏真皮手套",
            price=98, category="clothing", sub_type="",
            icon="🧤", rarity="rare",
            effect_desc="温暖+10, 气质+6",
        ),

    ShopItem(
            id="gloves_wool", name="毛线手套", description="可爱毛线手套",
            price=35, category="clothing", sub_type="",
            icon="🧤", rarity="common",
            effect_desc="温暖+8, 心情+5",
        ),

    ShopItem(
            id="socks_cute", name="可爱袜子", description="动物图案棉花糖袜",
            price=18, category="clothing", sub_type="",
            icon="🧦", rarity="common",
            effect_desc="心情+5, 日常+3",
        ),

    ShopItem(
            id="socks_thigh", name="过膝袜", description="黑色过膝袜",
            price=28, category="clothing", sub_type="",
            icon="🧦", rarity="common",
            effect_desc="自信+6, 心情+4",
        ),

    ShopItem(
            id="belt_leather", name="皮带", description="简约自动扣皮带",
            price=68, category="clothing", sub_type="",
            icon="👔", rarity="common",
            effect_desc="实用+6, 气质+4",
        ),

    ShopItem(
            id="belt_chain", name="链条腰带", description="金属链条装饰腰带",
            price=58, category="clothing", sub_type="",
            icon="⛓️", rarity="common",
            effect_desc="潮流+6, 心情+5",
        ),

    ShopItem(
            id="hairband_bow", name="蝴蝶结发箍", description="丝绒蝴蝶结发箍",
            price=25, category="clothing", sub_type="",
            icon="🎀", rarity="common",
            effect_desc="心情+6, 可爱+5",
        ),

    ShopItem(
            id="hairpin_set", name="发夹套装", description="珍珠发夹9件套",
            price=35, category="clothing", sub_type="",
            icon="📌", rarity="common",
            effect_desc="心情+5, 可爱+4",
        ),

    ShopItem(
            id="scrunchie_set", name="大肠发圈", description="丝绒大肠发圈6件套",
            price=22, category="clothing", sub_type="",
            icon="🎀", rarity="common",
            effect_desc="心情+5, 日常+3",
        ),

    ShopItem(
            id="anklet_star", name="脚链", description="星星脚链",
            price=38, category="clothing", sub_type="",
            icon="⛓️", rarity="common",
            effect_desc="心情+5, 气质+4",
        ),

    ShopItem(
            id="earrings_stud", name="耳钉", description="迷你星星耳钉",
            price=28, category="clothing", sub_type="",
            icon="✨", rarity="common",
            effect_desc="心情+4, 气质+3",
        ),

    ShopItem(
            id="watch_casual", name="手表", description="简约真皮手表",
            price=138, category="clothing", sub_type="",
            icon="⌚", rarity="rare",
            effect_desc="气质+10, 实用+6",
        ),

    ShopItem(
            id="ring_simple_c", name="素圈戒指", description="钛钢素圈戒指",
            price=38, category="clothing", sub_type="",
            icon="💍", rarity="common",
            effect_desc="心情+5, 气质+4",
        ),

    ShopItem(
            id="glasses_frame", name="金丝眼镜", description="复古金丝圆框眼镜",
            price=58, category="clothing", sub_type="",
            icon="👓", rarity="common",
            effect_desc="气质+8, 心情+5",
        ),

    ShopItem(
            id="umbrella_clear", name="透明伞", description="鸟笼透明长柄伞",
            price=45, category="clothing", sub_type="",
            icon="☂️", rarity="common",
            effect_desc="实用+8, 心情+5",
        ),

    ShopItem(
            id="mask_set", name="口罩套装", description="立体口罩套装",
            price=15, category="clothing", sub_type="",
            icon="😷", rarity="common",
            effect_desc="实用+5",
        ),

    ShopItem(
            id="pajama_set", name="睡衣套装", description="法兰绒卡通睡衣套装",
            price=88, category="clothing", sub_type="",
            icon="🩱", rarity="common",
            effect_desc="舒适+10, 心情+6",
        ),

]
