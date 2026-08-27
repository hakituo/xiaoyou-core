# -*- coding: utf-8 -*-
"""商城-book 类商品。"""
from core.food.models import ShopItem

BOOKS: list[ShopItem] = [
    ShopItem(
            id="novel_norwegian", name="挪威的森林", description="村上春树代表作，青春的迷失与救赎",
            price=38, category="book", sub_type="",
            icon="📚", rarity="common",
            effect_desc="沉浸+10, 心情+5",
        ),

    ShopItem(
            id="novel_kafka", name="变形记", description="卡夫卡经典，荒诞中的真实人性",
            price=28, category="book", sub_type="",
            icon="📖", rarity="common",
            effect_desc="思考+10",
        ),

    ShopItem(
            id="novel_pride", name="傲慢与偏见", description="简奥斯汀经典爱情小说",
            price=35, category="book", sub_type="",
            icon="📕", rarity="common",
            effect_desc="沉浸+8, 心情+5",
        ),

    ShopItem(
            id="novel_100years", name="百年孤独", description="马尔克斯魔幻现实主义巨著",
            price=45, category="book", sub_type="",
            icon="📗", rarity="rare",
            effect_desc="沉浸+15, 思考+10",
        ),

    ShopItem(
            id="novel_wizard", name="哈利波特全集", description="魔法世界的奇幻冒险",
            price=298, category="book", sub_type="",
            icon="🪄", rarity="epic",
            effect_desc="沉浸+25, 心情+15",
        ),

    ShopItem(
            id="novel_little_prince", name="小王子", description="写给大人的童话，纯粹而深刻",
            price=25, category="book", sub_type="",
            icon="👑", rarity="common",
            effect_desc="心情+10, 治愈+8",
        ),

    ShopItem(
            id="novel_alchemist", name="牧羊少年奇幻之旅", description="保罗柯艾略，追寻天命的旅程",
            price=32, category="book", sub_type="",
            icon="🐪", rarity="common",
            effect_desc="心情+8, 思考+6",
        ),

    ShopItem(
            id="novel_calligraphy", name="解忧杂货店", description="东野圭吾，温暖人心的奇幻推理",
            price=35, category="book", sub_type="",
            icon="📮", rarity="common",
            effect_desc="心情+10, 治愈+8",
        ),

    ShopItem(
            id="novel_threebody", name="三体全集", description="刘慈欣硬核科幻三部曲",
            price=128, category="book", sub_type="",
            icon="🌍", rarity="rare",
            effect_desc="思考+15, 沉浸+12",
        ),

    ShopItem(
            id="novel_dune", name="沙丘", description="弗兰克赫伯特科幻经典",
            price=58, category="book", sub_type="",
            icon="🏜️", rarity="rare",
            effect_desc="沉浸+12, 思考+10",
        ),

    ShopItem(
            id="novel_1984", name="1984", description="乔治奥威尔反乌托邦经典",
            price=32, category="book", sub_type="",
            icon="👁️", rarity="common",
            effect_desc="思考+12",
        ),

    ShopItem(
            id="novel_brave_new", name="美丽新世界", description="赫胥黎反乌托邦经典",
            price=30, category="book", sub_type="",
            icon="🌐", rarity="common",
            effect_desc="思考+10",
        ),

    ShopItem(
            id="novel_fahrenheit", name="华氏451度", description="布雷德伯里关于焚书的预言",
            price=28, category="book", sub_type="",
            icon="🔥", rarity="common",
            effect_desc="思考+10",
        ),

    ShopItem(
            id="manga_doraemon", name="哆啦A梦", description="藤子F不二雄经典漫画",
            price=25, category="book", sub_type="",
            icon="🔵", rarity="common",
            effect_desc="心情+12, 怀旧+8",
        ),

    ShopItem(
            id="manga_conan", name="名侦探柯南", description="青山刚昌推理漫画",
            price=25, category="book", sub_type="",
            icon="🔍", rarity="common",
            effect_desc="思考+8, 专注+6",
        ),

    ShopItem(
            id="manga_onepiece", name="海贼王", description="尾田荣一郎热血冒险漫画",
            price=28, category="book", sub_type="",
            icon="🏴", rarity="common",
            effect_desc="心情+10, 热血+8",
        ),

    ShopItem(
            id="manga_naruto", name="火影忍者", description="岸本齐史忍者世界漫画",
            price=25, category="book", sub_type="",
            icon="🥷", rarity="common",
            effect_desc="心情+8, 热血+8",
        ),

    ShopItem(
            id="manga_spy", name="间谍过家家", description="远藤达哉温馨喜剧漫画",
            price=28, category="book", sub_type="",
            icon="🕵️", rarity="common",
            effect_desc="心情+12, 治愈+6",
        ),

    ShopItem(
            id="manga_chainsaw", name="电锯人", description="藤本树黑暗奇幻漫画",
            price=30, category="book", sub_type="",
            icon="🪚", rarity="common",
            effect_desc="心情+8, 热血+6",
        ),

    ShopItem(
            id="manga_berserk", name="剑风传奇", description="三浦建太郎暗黑奇幻史诗",
            price=45, category="book", sub_type="",
            icon="⚔️", rarity="rare",
            effect_desc="沉浸+15, 震撼+10",
        ),

    ShopItem(
            id="manga_vagabond", name="浪客行", description="井上雄彦剑客物语",
            price=45, category="book", sub_type="",
            icon="🗡️", rarity="rare",
            effect_desc="沉浸+12, 思考+8",
        ),

    ShopItem(
            id="manga_slam_dunk", name="灌篮高手", description="井上雄彦热血篮球漫画",
            price=28, category="book", sub_type="",
            icon="🏀", rarity="common",
            effect_desc="心情+10, 热血+10",
        ),

    ShopItem(
            id="manga_yotsuba", name="悠悠式", description="轻松治愈的日常漫画",
            price=22, category="book", sub_type="",
            icon="🍀", rarity="common",
            effect_desc="心情+10, 治愈+8",
        ),

    ShopItem(
            id="manga_yotsuba_2", name="四叶妹妹", description="温馨日常漫画",
            price=22, category="book", sub_type="",
            icon="🌿", rarity="common",
            effect_desc="心情+10, 治愈+8",
        ),

    ShopItem(
            id="artbook_makoto", name="新海诚画集", description="你的名字天气之子美术画集",
            price=168, category="book", sub_type="",
            icon="🎨", rarity="epic",
            effect_desc="审美+15, 心情+12",
        ),

    ShopItem(
            id="artbook_ghibli", name="吉卜力画集", description="宫崎骏动画美术全集",
            price=198, category="book", sub_type="",
            icon="🌄", rarity="epic",
            effect_desc="审美+18, 心情+15",
        ),

    ShopItem(
            id="artbook_inoue", name="井上雄彦画集", description="浪客行灌篮高手画集",
            price=158, category="book", sub_type="",
            icon="🖌️", rarity="rare",
            effect_desc="审美+12, 专注+8",
        ),

    ShopItem(
            id="book_physics_quantum", name="量子力学导论", description="格里菲斯量子力学教材",
            price=68, category="book", sub_type="",
            icon="⚛️", rarity="rare",
            effect_desc="知识+15, 思考+12",
        ),

    ShopItem(
            id="book_physics_feynman", name="费曼物理学讲义", description="费曼经典物理讲座合集",
            price=128, category="book", sub_type="",
            icon="💡", rarity="epic",
            effect_desc="知识+20, 思考+15",
        ),

    ShopItem(
            id="book_math_linear", name="线性代数", description="MIT线性代数教材",
            price=58, category="book", sub_type="",
            icon="📐", rarity="rare",
            effect_desc="知识+12, 逻辑+10",
        ),

    ShopItem(
            id="book_math_calculus", name="微积分", description="托马斯微积分教材",
            price=65, category="book", sub_type="",
            icon="📊", rarity="rare",
            effect_desc="知识+12, 逻辑+10",
        ),

    ShopItem(
            id="book_cs_ai", name="人工智能现代方法", description="AIAMA经典AI教材",
            price=138, category="book", sub_type="",
            icon="🤖", rarity="epic",
            effect_desc="知识+18, 思考+15",
        ),

    ShopItem(
            id="book_cs_algo", name="算法导论", description="CLRS算法圣经",
            price=128, category="book", sub_type="",
            icon="📋", rarity="epic",
            effect_desc="知识+15, 逻辑+15",
        ),

    ShopItem(
            id="book_cs_clean_code", name="代码整洁之道", description="Robert Martin编程经典",
            price=58, category="book", sub_type="",
            icon="💻", rarity="rare",
            effect_desc="知识+12, 专注+8",
        ),

    ShopItem(
            id="book_cs_sicp", name="计算机程序的构造和解释", description="SICP编程启蒙",
            price=78, category="book", sub_type="",
            icon="🔧", rarity="rare",
            effect_desc="知识+15, 思考+10",
        ),

    ShopItem(
            id="book_psy_thinking", name="思考快与慢", description="卡尼曼行为经济学经典",
            price=45, category="book", sub_type="",
            icon="🧠", rarity="rare",
            effect_desc="思考+12, 认知+10",
        ),

    ShopItem(
            id="book_psy_flow", name="心流", description="契克森米哈赖积极心理学",
            price=38, category="book", sub_type="",
            icon="🌊", rarity="common",
            effect_desc="思考+10, 专注+8",
        ),

    ShopItem(
            id="book_psy_mindset", name="终身成长", description="德韦克成长型思维",
            price=35, category="book", sub_type="",
            icon="🌱", rarity="common",
            effect_desc="思考+8, 动力+6",
        ),

    ShopItem(
            id="book_his_brief", name="人类简史", description="赫拉利人类文明简史",
            price=45, category="book", sub_type="",
            icon="🏛️", rarity="rare",
            effect_desc="知识+12, 思考+10",
        ),

    ShopItem(
            id="book_his_sapiens", name="未来简史", description="赫拉利关于未来的预言",
            price=42, category="book", sub_type="",
            icon="🔮", rarity="rare",
            effect_desc="思考+12, 视野+10",
        ),

    ShopItem(
            id="book_his_3kingdoms", name="三国演义", description="罗贯中历史演义经典",
            price=38, category="book", sub_type="",
            icon="⚔️", rarity="common",
            effect_desc="知识+8, 沉浸+10",
        ),

    ShopItem(
            id="book_his_water_margin", name="水浒传", description="施耐庵英雄传奇",
            price=35, category="book", sub_type="",
            icon="🗡️", rarity="common",
            effect_desc="沉浸+8",
        ),

    ShopItem(
            id="book_his_journey", name="西游记", description="吴承恩神魔小说",
            price=35, category="book", sub_type="",
            icon="🐒", rarity="common",
            effect_desc="沉浸+10, 心情+5",
        ),

    ShopItem(
            id="book_his_dream", name="红楼梦", description="曹雪芹古典文学巅峰",
            price=48, category="book", sub_type="",
            icon="🌸", rarity="rare",
            effect_desc="沉浸+15, 审美+10",
        ),

    ShopItem(
            id="book_phil_sophie", name="苏菲的世界", description="乔斯坦贾德哲学入门",
            price=38, category="book", sub_type="",
            icon="🔮", rarity="common",
            effect_desc="思考+12, 知识+8",
        ),

    ShopItem(
            id="book_phil_tao", name="道德经", description="老子道家哲学经典",
            price=22, category="book", sub_type="",
            icon="☯️", rarity="common",
            effect_desc="思考+10, 心静+8",
        ),

    ShopItem(
            id="book_phil_zhuangzi", name="庄子", description="庄周逍遥游哲学",
            price=25, category="book", sub_type="",
            icon="🦋", rarity="common",
            effect_desc="思考+10, 心静+8",
        ),

    ShopItem(
            id="book_phil_meditations", name="沉思录", description="马可奥勒留斯多葛哲学",
            price=28, category="book", sub_type="",
            icon="🏛️", rarity="common",
            effect_desc="思考+10, 心静+6",
        ),

    ShopItem(
            id="book_essay_sakura", name="樱花庄的宠物女孩", description="鸭志田一轻小说",
            price=28, category="book", sub_type="",
            icon="🌸", rarity="common",
            effect_desc="心情+8, 沉浸+6",
        ),

    ShopItem(
            id="book_essay_kokoro", name="心", description="夏目漱石人性剖析",
            price=32, category="book", sub_type="",
            icon="💗", rarity="common",
            effect_desc="思考+10, 沉浸+8",
        ),

    ShopItem(
            id="book_science_cosmos", name="宇宙", description="卡尔萨根科普经典",
            price=45, category="book", sub_type="",
            icon="🌌", rarity="rare",
            effect_desc="知识+12, 视野+10",
        ),

    ShopItem(
            id="book_science_gene", name="基因传", description="辛达穆克吉基因科普",
            price=42, category="book", sub_type="",
            icon="🧬", rarity="rare",
            effect_desc="知识+10, 思考+8",
        ),

    ShopItem(
            id="book_science_time", name="时间简史", description="霍金宇宙学普及",
            price=38, category="book", sub_type="",
            icon="⏳", rarity="common",
            effect_desc="知识+10, 思考+8",
        ),

    ShopItem(
            id="book_magazine_natgeo", name="国家地理合订本", description="国家地理杂志年度合订",
            price=88, category="book", sub_type="",
            icon="🗺️", rarity="rare",
            effect_desc="视野+12, 审美+8",
        ),

    ShopItem(
            id="book_magazine_newtype", name="NewType", description="日本动漫情报杂志",
            price=45, category="book", sub_type="",
            icon="📺", rarity="common",
            effect_desc="心情+8, 资讯+6",
        ),

    ShopItem(
            id="book_cook_baking", name="烘焙圣经", description="全面的家庭烘焙指南",
            price=55, category="book", sub_type="",
            icon="🧁", rarity="rare",
            effect_desc="技能+10, 创造+8",
        ),

    ShopItem(
            id="book_cook_japanese", name="日式料理全书", description="经典日料制作指南",
            price=48, category="book", sub_type="",
            icon="🍣", rarity="common",
            effect_desc="技能+8, 创造+6",
        ),

    ShopItem(
            id="book_travel_japan", name="日本旅行手册", description="深度日本旅行指南",
            price=35, category="book", sub_type="",
            icon="🗻", rarity="common",
            effect_desc="视野+8, 心情+6",
        ),

    ShopItem(
            id="book_travel_iceland", name="冰岛旅行指南", description="极光与冰川之旅",
            price=38, category="book", sub_type="",
            icon="❄️", rarity="common",
            effect_desc="视野+8, 心情+6",
        ),

]
