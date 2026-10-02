# -*- coding: utf-8 -*-
"""商城-luxury 类商品。"""
from core.food.models import ShopItem

LUXURY: list[ShopItem] = [
    ShopItem(id="watch_rolex", name="劳力士手表", description="劳力士水鬼潜航者型", price=88888, category="luxury", sub_type="", icon="⌚", rarity="legendary", effect_desc="身份+30, 品味+20"),

    ShopItem(id="watch_omega", name="欧米茄手表", description="欧米茄超霸月球表", price=58000, category="luxury", sub_type="", icon="⌚", rarity="epic", effect_desc="身份+25, 品味+15"),

    ShopItem(id="watch_cartier_lux", name="卡地亚手表", description="卡地亚蓝气球", price=42000, category="luxury", sub_type="", icon="⌚", rarity="epic", effect_desc="身份+22, 优雅+15"),

    ShopItem(id="watch_iwc", name="万国手表", description="IWC葡萄牙计时", price=68000, category="luxury", sub_type="", icon="⌚", rarity="epic", effect_desc="身份+25, 品味+18"),

    ShopItem(id="watch_audemars", name="爱彼手表", description="AP皇家橡树离岸型", price=158000, category="luxury", sub_type="", icon="⌚", rarity="legendary", effect_desc="身份+35, 奢华+25"),

    ShopItem(id="watch_patek", name="百达翡丽", description="百达翡丽鹦鹉螺", price=288000, category="luxury", sub_type="", icon="⌚", rarity="legendary", effect_desc="身份+40, 传承+30"),

    ShopItem(id="bag_hermes_birkin", name="爱马仕铂金包", description="Hermes Birkin 30", price=150000, category="luxury", sub_type="", icon="👜", rarity="legendary", effect_desc="身份+35, 奢华+25"),

    ShopItem(id="bag_hermes_kelly", name="爱马仕凯莉包", description="Hermes Kelly 28", price=120000, category="luxury", sub_type="", icon="👜", rarity="legendary", effect_desc="身份+32, 优雅+20"),

    ShopItem(id="bag_chanel_classic", name="香奈儿经典款", description="Chanel Classic Flap", price=68000, category="luxury", sub_type="", icon="👜", rarity="epic", effect_desc="身份+25, 时尚+18"),

    ShopItem(id="bag_lv_neverfull", name="LV Neverfull", description="Louis Vuitton Neverfull MM", price=15500, category="luxury", sub_type="", icon="👜", rarity="rare", effect_desc="身份+15, 时尚+12"),

    ShopItem(id="bag_dior_lady", name="Dior戴妃包", description="Christian Dior Lady Dior", price=38000, category="luxury", sub_type="", icon="👜", rarity="epic", effect_desc="身份+22, 优雅+15"),

    ShopItem(id="bag_gucci_marmont", name="Gucci Marmont", description="Gucci GG Marmont链条包", price=22000, category="luxury", sub_type="", icon="👜", rarity="rare", effect_desc="身份+18, 时尚+12"),

    ShopItem(id="bag_prada_reedition", name="Prada Hobo", description="Prada Re-Edition Hobo", price=9800, category="luxury", sub_type="", icon="👜", rarity="rare", effect_desc="身份+12, 潮流+10"),

    ShopItem(id="bag_celine_triomphe", name="Celine Triomphe", description="Celine Triomphe Canvas", price=16500, category="luxury", sub_type="", icon="👜", rarity="rare", effect_desc="身份+15, 简约+10"),

    ShopItem(id="bag_bottega_veneta", name="BV编织包", description="Bottega Veneta Cassette", price=22000, category="luxury", sub_type="", icon="👜", rarity="rare", effect_desc="身份+15, 品味+12"),

    ShopItem(id="bag_saint_laurent", name="YSL包", description="Saint Laurent Niki", price=19800, category="luxury", sub_type="", icon="👜", rarity="rare", effect_desc="身份+14, 时尚+10"),

    ShopItem(id="bag_fendi_baguette", name="Fendi法棍包", description="Fendi Baguette", price=18000, category="luxury", sub_type="", icon="👜", rarity="rare", effect_desc="身份+14, 潮流+10"),

    ShopItem(id="bag_loewe_puzzle", name="Loewe Puzzle", description="Loewe Puzzle Edge", price=22000, category="luxury", sub_type="", icon="👜", rarity="rare", effect_desc="身份+15, 设计+12"),

    ShopItem(id="bag_goyard", name="Goyard托特", description="Goyard Saint Louis", price=12500, category="luxury", sub_type="", icon="👜", rarity="rare", effect_desc="身份+12, 低调+10"),

    ShopItem(id="bag_delvaux", name="Delvaux包", description="Delvaux Brillant", price=45000, category="luxury", sub_type="", icon="👜", rarity="epic", effect_desc="身份+20, 品味+15"),

    ShopItem(id="wallet_hermes", name="爱马仕钱包", description="Hermes Bearnsfords长款钱包", price=8500, category="luxury", sub_type="", icon="👛", rarity="rare", effect_desc="身份+12, 品味+8"),

    ShopItem(id="wallet_chanel", name="香奈儿钱包", description="Chanel长款拉链钱包", price=6800, category="luxury", sub_type="", icon="👛", rarity="rare", effect_desc="身份+10, 时尚+8"),

    ShopItem(id="wallet_lv", name="LV钱包", description="Louis Vuitton Victorine钱包", price=4200, category="luxury", sub_type="", icon="👛", rarity="common", effect_desc="身份+8, 时尚+6"),

    ShopItem(id="belt_hermes", name="爱马仕皮带", description="Hermes H型皮带", price=6800, category="luxury", sub_type="", icon="👗", rarity="rare", effect_desc="身份+10, 品味+8"),

    ShopItem(id="scarf_hermes", name="爱马仕丝巾", description="90cm真丝方巾", price=4200, category="luxury", sub_type="", icon="🧣", rarity="rare", effect_desc="身份+10, 优雅+8"),

    ShopItem(id="sunglasses_chanel", name="香奈儿墨镜", description="Chanel猫眼墨镜", price=3800, category="luxury", sub_type="", icon="🕶️", rarity="rare", effect_desc="时尚+12, 气场+8"),

    ShopItem(id="sunglasses_dior", name="Dior墨镜", description="DiorClub系列墨镜", price=3200, category="luxury", sub_type="", icon="🕶️", rarity="rare", effect_desc="时尚+10, 气场+6"),

    ShopItem(id="sunglasses_gentle", name="Gentle Monster", description="Gentle Monster潮款墨镜", price=2200, category="luxury", sub_type="", icon="🕶️", rarity="rare", effect_desc="时尚+8, 潮流+6"),

    ShopItem(id="perfume_chanel_no5", name="香奈儿5号", description="Chanel N5经典淡香水", price=1200, category="luxury", sub_type="", icon="🧴", rarity="rare", effect_desc="魅力+12, 优雅+8"),

    ShopItem(id="perfume_tomford", name="Tom Ford香水", description="Tom Ford黑兰花", price=2800, category="luxury", sub_type="", icon="🧴", rarity="epic", effect_desc="魅力+15, 奢华+10"),

    ShopItem(id="perfume_creeds", name="Creed香水", description="Creed银色山泉", price=2200, category="luxury", sub_type="", icon="🧴", rarity="rare", effect_desc="魅力+12, 清新+8"),

    ShopItem(id="perfume_jomalone", name="祖马龙香水", description="Jo Malone鼠尾草海盐", price=980, category="luxury", sub_type="", icon="🧴", rarity="rare", effect_desc="魅力+10, 清新+6"),

    ShopItem(id="perfume_diptyque", name="Diptyque香水", description="Diptyque檀道淡香水", price=1280, category="luxury", sub_type="", icon="🧴", rarity="rare", effect_desc="魅力+10, 安神+6"),

    ShopItem(id="perfume_byredo", name="Byredo香水", description="Byredo吉普赛之水", price=1800, category="luxury", sub_type="", icon="🧴", rarity="rare", effect_desc="魅力+12, 个性+8"),

    ShopItem(id="jewelry_tiffany_ring", name="蒂芙尼戒指", description="Tiffany T系列戒指", price=8800, category="luxury", sub_type="", icon="💍", rarity="epic", effect_desc="魅力+15, 品味+10"),

    ShopItem(id="jewelry_cartier_love", name="卡地亚戒指", description="Cartier Love系列戒指", price=12800, category="luxury", sub_type="", icon="💍", rarity="epic", effect_desc="魅力+18, 奢华+12"),

    ShopItem(id="jewelry_vca", name="梵克雅宝", description="VCA Alhambra四叶草", price=28000, category="luxury", sub_type="", icon="🍀", rarity="epic", effect_desc="魅力+20, 优雅+15"),

    ShopItem(id="jewelry_bvlgari", name="宝格丽戒指", description="Bvlgari Bzero1戒指", price=9800, category="luxury", sub_type="", icon="💍", rarity="epic", effect_desc="魅力+15, 时尚+10"),

    ShopItem(id="jewelry_harry_winston", name="海瑞温斯顿", description="HW钻戒", price=88000, category="luxury", sub_type="", icon="💎", rarity="legendary", effect_desc="魅力+30, 奢华+25"),

    ShopItem(id="necklace_tiffany", name="蒂芙尼项链", description="Tiffany Smile项链", price=9800, category="luxury", sub_type="", icon="📿", rarity="epic", effect_desc="魅力+15, 优雅+10"),

    ShopItem(id="necklace_cartier", name="卡地亚项链", description="Cartier Clash项链", price=22000, category="luxury", sub_type="", icon="📿", rarity="epic", effect_desc="魅力+18, 奢华+12"),

    ShopItem(id="necklace_vca", name="梵克雅宝项链", description="VCA Sweet Alhambra项链", price=32000, category="luxury", sub_type="", icon="📿", rarity="epic", effect_desc="魅力+20, 优雅+15"),

    ShopItem(id="earrings_cartier", name="卡地亚耳环", description="Cartier Juste un Clou耳环", price=12000, category="luxury", sub_type="", icon="💎", rarity="epic", effect_desc="魅力+15, 时尚+10"),

    ShopItem(id="earrings_vca", name="梵克雅宝耳环", description="VCA单颗四叶草耳环", price=18000, category="luxury", sub_type="", icon="💎", rarity="epic", effect_desc="魅力+18, 优雅+12"),

    ShopItem(id="bracelet_cartier", name="卡地亚手镯", description="Cartier Love手镯", price=15800, category="luxury", sub_type="", icon="⛓️", rarity="epic", effect_desc="魅力+18, 奢华+12"),

    ShopItem(id="bracelet_tiffany", name="蒂芙尼手链", description="Tiffany HardWear手链", price=8800, category="luxury", sub_type="", icon="⛓️", rarity="epic", effect_desc="魅力+15, 时尚+10"),

    ShopItem(id="bracelet_bvlgari", name="宝格丽手链", description="Bvlgari Serpenti手链", price=18000, category="luxury", sub_type="", icon="🐍", rarity="epic", effect_desc="魅力+18, 奢华+12"),

    ShopItem(id="diamond_ring", name="钻戒", description="1克拉Tiffany钻戒", price=88000, category="luxury", sub_type="", icon="💎", rarity="legendary", effect_desc="浪漫+30, 承诺+25"),

    ShopItem(id="diamond_necklace", name="钻石项链", description="HW梨形钻石项链", price=158000, category="luxury", sub_type="", icon="💎", rarity="legendary", effect_desc="奢华+30, 魅力+25"),

    ShopItem(id="fur_coat", name="皮草大衣", description="Sable紫貂皮草大衣", price=280000, category="luxury", sub_type="", icon="🧥", rarity="legendary", effect_desc="奢华+25, 身份+20"),

    ShopItem(id="cashmere_coat", name="羊绒大衣", description="Loro Piana驼羊毛大衣", price=38000, category="luxury", sub_type="", icon="🧥", rarity="epic", effect_desc="温暖+18, 品味+15"),

    ShopItem(id="silk_dress_luxury", name="真丝礼服", description="Valentino高定真丝礼服", price=28000, category="luxury", sub_type="", icon="👗", rarity="epic", effect_desc="魅力+18, 气场+15"),

    ShopItem(id="leather_bag_crocodile", name="鳄鱼皮包", description="Hermes鳄鱼皮Birkin", price=280000, category="luxury", sub_type="", icon="🐊", rarity="legendary", effect_desc="身份+35, 奢华+30"),

    ShopItem(id="cufflinks_cartier", name="卡地亚袖扣", description="Cartier Santos袖扣", price=8800, category="luxury", sub_type="", icon="👔", rarity="epic", effect_desc="品味+12, 身份+10"),

    ShopItem(id="pen_montblanc", name="万宝龙钢笔", description="Montblanc大班149钢笔", price=6800, category="luxury", sub_type="", icon="🖊️", rarity="epic", effect_desc="品味+12, 仪式+10"),

    ShopItem(id="pen_alessi", name="豪华钢笔套装", description="Tibaldi豪华钢笔套装", price=28000, category="luxury", sub_type="", icon="🖊️", rarity="epic", effect_desc="品味+15, 收藏+12"),

    ShopItem(id="lighter_dupont", name="都彭打火机", description="S.T.Dupont朗声打火机", price=3800, category="luxury", sub_type="", icon="🔥", rarity="rare", effect_desc="品味+10, 仪式+8"),

    ShopItem(id="umbrella_luxury", name="高端雨伞", description="Burberry经典格纹伞", price=2800, category="luxury", sub_type="", icon="☂️", rarity="rare", effect_desc="品味+8, 优雅+6"),

]
