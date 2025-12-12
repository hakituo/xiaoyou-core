#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数学基础题型自动生成器
覆盖高考核心模块，支持难度设置和多种导出格式
"""

import random
import math
from typing import List, Dict, Any, Tuple
from datetime import datetime
from ..common.utils import generate_unique_id
from ..common.data_io import DataIO
from ..common.gui_base import GUIApp, BaseFrame, MessageBox, FileDialog


class MathProblemGenerator:
    """数学基础题型生成器"""
    
    def __init__(self):
        """初始化数学题型生成器"""
        self.modules = {
            "三角函数": self.generate_trigonometry,
            "立体几何": self.generate_geometry,
            "概率统计": self.generate_probability,
            "导数": self.generate_calculus,
            "解析几何": self.generate_analytic_geometry
        }
        
        self.difficulty_levels = ["基础", "中档", "难题"]
        self.export_modes = ["仅题目", "题目+答案", "题目+分步解析"]
    
    def generate_problems(self, module: str, difficulty: str, count: int) -> List[Dict[str, Any]]:
        """
        生成指定模块的题目
        
        Args:
            module: 模块名称
            difficulty: 难度级别
            count: 题目数量
        
        Returns:
            List[Dict[str, Any]]: 生成的题目列表
        """
        if module not in self.modules:
            raise ValueError(f"不支持的模块: {module}")
        
        if difficulty not in self.difficulty_levels:
            raise ValueError(f"不支持的难度: {difficulty}")
        
        problems = []
        generated_problems = set()  # 用于避免重复
        
        while len(problems) < count:
            problem = self.modules[module](difficulty)
            # 生成唯一标识
            problem_id = self._generate_problem_id(problem)
            
            if problem_id not in generated_problems:
                generated_problems.add(problem_id)
                problems.append(problem)
        
        return problems
    
    def _generate_problem_id(self, problem: Dict[str, Any]) -> str:
        """
        生成题目的唯一标识
        
        Args:
            problem: 题目数据
        
        Returns:
            str: 唯一标识
        """
        return f"{problem['模块']}_{problem['难度']}_{hash(problem['题目'])}"
    
    def generate_mixed_problems(self, modules: List[str], difficulty: str, count: int) -> List[Dict[str, Any]]:
        """
        生成混合模块的题目
        
        Args:
            modules: 模块列表
            difficulty: 难度级别
            count: 题目数量
        
        Returns:
            List[Dict[str, Any]]: 生成的题目列表
        """
        # 确保模块有效
        valid_modules = [m for m in modules if m in self.modules]
        if not valid_modules:
            raise ValueError("没有有效的模块")
        
        # 计算每个模块的题目数量
        module_counts = {}
        for i in range(count):
            module = valid_modules[i % len(valid_modules)]
            module_counts[module] = module_counts.get(module, 0) + 1
        
        # 生成题目
        all_problems = []
        for module, cnt in module_counts.items():
            problems = self.generate_problems(module, difficulty, cnt)
            all_problems.extend(problems)
        
        # 打乱顺序
        random.shuffle(all_problems)
        return all_problems
    
    def generate_trigonometry(self, difficulty: str) -> Dict[str, Any]:
        """
        生成三角函数题目
        
        Args:
            difficulty: 难度级别
        
        Returns:
            Dict[str, Any]: 题目数据
        """
        if difficulty == "基础":
            # 基础题：公式应用
            a = random.randint(2, 10)
            b = random.randint(2, 10)
            angle = random.choice([30, 45, 60, 90, 120, 135, 150, 180])
            
            # 正弦定理或余弦定理
            problem_type = random.choice(["正弦定理", "余弦定理"])
            
            if problem_type == "正弦定理":
                question = f"在△ABC中，已知a={a}，∠A={angle}°，∠B=60°，求b的值。"
                answer = f"b = {a} * sin(60°) / sin({angle}°) = {a} * (√3/2) / {math.sin(math.radians(angle))} = {a * (math.sqrt(3)/2) / math.sin(math.radians(angle)):.2f}"
                steps = [
                    f"1. 应用正弦定理：a/sinA = b/sinB",
                    f"2. 代入已知值：{a}/sin({angle}°) = b/sin(60°)",
                    f"3. 解方程求b：b = {a} * sin(60°) / sin({angle}°)",
                    f"4. 计算结果：b = {a} * (√3/2) / {math.sin(math.radians(angle))} = {a * (math.sqrt(3)/2) / math.sin(math.radians(angle)):.2f}"
                ]
            else:
                question = f"在△ABC中，已知a={a}，b={b}，∠C=60°，求c的值。"
                answer = f"c = √({a}² + {b}² - 2*{a}*{b}*cos(60°)) = √({a}² + {b}² - {a}*{b}) = {math.sqrt(a**2 + b**2 - a*b):.2f}"
                steps = [
                    f"1. 应用余弦定理：c² = a² + b² - 2ab cosC",
                    f"2. 代入已知值：c² = {a}² + {b}² - 2*{a}*{b}*cos(60°)",
                    f"3. 计算：c² = {a}² + {b}² - {a}*{b}",
                    f"4. 开平方：c = {math.sqrt(a**2 + b**2 - a*b):.2f}"
                ]
        
        elif difficulty == "中档":
            # 中档题：综合应用
            a = random.randint(1, 5)
            b = random.randint(1, 5)
            angle = random.randint(0, 360)
            
            question = f"化简：{a}sinx + {b}cosx，并求其最大值。"
            R = math.sqrt(a**2 + b**2)
            phi = math.degrees(math.atan2(b, a))
            
            answer = f"{a}sinx + {b}cosx = {R:.2f}sin(x + {phi:.1f}°)，最大值为{R:.2f}"
            steps = [
                f"1. 提取公因子R：R = √({a}² + {b}²) = {R:.2f}",
                f"2. 令cosφ = {a}/{R:.2f}，sinφ = {b}/{R:.2f}，则φ = {phi:.1f}°",
                f"3. 利用两角和公式：{a}sinx + {b}cosx = R(sinxcosφ + cosxsinφ) = Rsin(x + φ)",
                f"4. 化简结果：{R:.2f}sin(x + {phi:.1f}°)",
                f"5. 正弦函数最大值为1，故原式最大值为{R:.2f}"
            ]
        
        else:  # 难题
            # 难题：综合考点
            a = random.randint(1, 3)
            b = random.randint(1, 3)
            
            question = f"已知函数f(x) = {a}sin2x + {b}cos2x，求其单调递增区间及在区间[0, π]上的最大值和最小值。"
            R = math.sqrt(a**2 + b**2)
            phi = math.degrees(math.atan2(b, a))
            
            answer = f"f(x) = {R:.2f}sin(2x + {phi:.1f}°)，单调递增区间为[kπ - {phi/2 + 45:.1f}°, kπ + {45 - phi/2:.1f}°]，最大值为{R:.2f}，最小值为{-R:.2f}"
            steps = [
                f"1. 提取公因子R：R = √({a}² + {b}²) = {R:.2f}",
                f"2. 化简为正弦型函数：f(x) = {R:.2f}sin(2x + {phi:.1f}°)",
                f"3. 求单调递增区间：令-π/2 + 2kπ ≤ 2x + {phi:.1f}° ≤ π/2 + 2kπ",
                f"4. 解不等式：-π/2 - {phi:.1f}° + 2kπ ≤ 2x ≤ π/2 - {phi:.1f}° + 2kπ",
                f"5. 区间为：kπ - {phi/2 + 45:.1f}° ≤ x ≤ kπ + {45 - phi/2:.1f}°",
                f"6. 在区间[0, π]上，当2x + {phi:.1f}° = π/2时，f(x)取得最大值{R:.2f}",
                f"7. 当2x + {phi:.1f}° = 3π/2时，f(x)取得最小值{-R:.2f}"
            ]
        
        return {
            "题目": question,
            "答案": answer,
            "解析": "\n".join(steps),
            "模块": "三角函数",
            "难度": difficulty,
            "公式": ["正弦定理", "余弦定理", "两角和公式"],
            "采分点": ["公式应用", "计算过程", "结果正确"]
        }
    
    def generate_geometry(self, difficulty: str) -> Dict[str, Any]:
        """
        生成立体几何题目
        
        Args:
            difficulty: 难度级别
        
        Returns:
            Dict[str, Any]: 题目数据
        """
        if difficulty == "基础":
            # 基础题：体积计算
            a = random.randint(3, 10)
            b = random.randint(3, 10)
            h = random.randint(3, 10)
            
            question = f"已知长方体的长、宽、高分别为{a}、{b}、{h}，求其体积和表面积。"
            volume = a * b * h
            surface_area = 2 * (a*b + a*h + b*h)
            
            answer = f"体积：{volume}，表面积：{surface_area}"
            steps = [
                f"1. 长方体体积公式：V = 长×宽×高",
                f"2. 代入数值：V = {a}×{b}×{h} = {volume}",
                f"3. 长方体表面积公式：S = 2(长×宽 + 长×高 + 宽×高)",
                f"4. 代入数值：S = 2×({a}×{b} + {a}×{h} + {b}×{h}) = 2×({a*b} + {a*h} + {b*h}) = 2×{a*b + a*h + b*h} = {surface_area}"
            ]
        
        elif difficulty == "中档":
            # 中档题：线面关系
            a = random.randint(3, 8)
            
            question = f"在正方体ABCD-A1B1C1D1中，棱长为{a}，求直线AC与平面A1BD的距离。"
            # 正方体中，直线AC与平面A1BD的距离等于AC到平面A1BD的距离，即点A到平面A1BD的距离
            distance = a / math.sqrt(3)
            
            answer = f"直线AC与平面A1BD的距离为{a}/√3 = {distance:.2f}"
            steps = [
                f"1. 建立空间直角坐标系，设A为原点，AB为x轴，AD为y轴，AA1为z轴",
                f"2. 各点坐标：A(0,0,0), C({a},{a},0), A1(0,0,{a}), B({a},0,0), D(0,{a},0)",
                f"3. 求平面A1BD的法向量：向量A1B = ({a},0,-{a}), 向量A1D = (0,{a},-{a})",
                f"4. 法向量n = A1B × A1D = ({a**2}, {a**2}, {a**2})",
                f"5. 直线AC上一点A到平面A1BD的距离：d = |向量A1A · n| / |n| = |(0,0,-{a})·({a**2},{a**2},{a**2})| / √(3*{a**4}) = {a**3} / ({a**2}√3) = {a}/√3 = {distance:.2f}"
            ]
        
        else:  # 难题
            # 难题：二面角计算
            a = random.randint(4, 8)
            
            question = f"在三棱锥P-ABC中，PA⊥底面ABC，AB⊥BC，PA=AB=BC={a}，求二面角P-BC-A的大小。"
            answer = f"二面角P-BC-A的大小为45°"
            steps = [
                f"1. 分析线面关系：PA⊥底面ABC，故PA⊥BC",
                f"2. 又AB⊥BC，PA∩AB=A，故BC⊥平面PAB",
                f"3. 所以BC⊥PB，BC⊥AB",
                f"4. 二面角P-BC-A的平面角为∠PBA",
                f"5. 在Rt△PAB中，PA=AB={a}，故∠PBA=45°",
                f"6. 因此二面角P-BC-A的大小为45°"
            ]
        
        return {
            "题目": question,
            "答案": answer,
            "解析": "\n".join(steps),
            "模块": "立体几何",
            "难度": difficulty,
            "公式": ["长方体体积公式", "表面积公式", "点到平面距离公式", "二面角定义"],
            "采分点": ["线面关系分析", "公式应用", "计算过程", "结果正确"]
        }
    
    def generate_probability(self, difficulty: str) -> Dict[str, Any]:
        """
        生成概率统计题目
        
        Args:
            difficulty: 难度级别
        
        Returns:
            Dict[str, Any]: 题目数据
        """
        if difficulty == "基础":
            # 基础题：古典概型
            n = random.randint(5, 15)
            k = random.randint(2, 5)
            m = random.randint(1, k-1)
            
            question = f"盒子中有{n}个球，其中{k}个红球，其余为白球。从中任取一个球，求取出红球的概率。"
            probability = k / n
            
            answer = f"概率为{k}/{n} = {probability:.2f}"
            steps = [
                f"1. 确定总样本数：{n}个球",
                f"2. 确定事件A（取出红球）包含的样本数：{k}个红球",
                f"3. 应用古典概型公式：P(A) = 事件A包含的样本数 / 总样本数",
                f"4. 计算概率：P(A) = {k}/{n} = {probability:.2f}"
            ]
        
        elif difficulty == "中档":
            # 中档题：条件概率
            n = random.randint(10, 20)
            k = random.randint(3, 8)
            m = random.randint(1, k-1)
            
            question = f"盒子中有{n}个球，其中{k}个红球，{n-k}个白球。第一次取出一个红球后不放回，求第二次取出红球的概率。"
            probability = (k-1) / (n-1)
            
            answer = f"概率为({k-1})/({n-1}) = {probability:.2f}"
            steps = [
                f"1. 第一次取出红球后，盒子中剩余{n-1}个球",
                f"2. 剩余红球数为{k-1}个",
                f"3. 应用条件概率公式：P(A|B) = P(AB)/P(B) = [{k}/{n} * ({k-1})/({n-1})] / [{k}/{n}] = ({k-1})/({n-1})",
                f"4. 计算概率：P(A|B) = ({k-1})/({n-1}) = {probability:.2f}"
            ]
        
        else:  # 难题
            # 难题：分布列和期望
            p = random.uniform(0.3, 0.7)
            n = random.randint(3, 5)
            
            question = f"某射击运动员每次射击命中目标的概率为{p:.2f}，连续射击{n}次，求命中次数X的分布列和数学期望。"
            
            # 生成分布列
            distribution = []
            for k in range(n+1):
                # 二项分布概率
                prob = math.comb(n, k) * (p**k) * ((1-p)**(n-k))
                distribution.append(f"P(X={k}) = C({n},{k}) * ({p:.2f})^{k} * ({1-p:.2f})^{{n-k}} = {prob:.4f}")
            
            # 数学期望
            expectation = n * p
            
            answer = f"分布列：\n" + "\n".join(distribution) + f"\n数学期望：E(X) = {n} * {p:.2f} = {expectation:.2f}"
            steps = [
                f"1. 确定随机变量X服从二项分布：X ~ B({n}, {p:.2f})",
                f"2. 二项分布的概率公式：P(X=k) = C(n,k) * p^k * (1-p)^(n-k)",
                f"3. 计算各k值的概率：",
            ]
            steps.extend([f"   {item}" for item in distribution])
            steps.extend([
                f"4. 数学期望公式：E(X) = np",
                f"5. 计算期望：E(X) = {n} * {p:.2f} = {expectation:.2f}"
            ])
        
        return {
            "题目": question,
            "答案": answer,
            "解析": "\n".join(steps),
            "模块": "概率统计",
            "难度": difficulty,
            "公式": ["古典概型", "条件概率", "二项分布", "数学期望"],
            "采分点": ["概率类型判断", "公式应用", "计算过程", "分布列完整性", "期望计算正确"]
        }
    
    def generate_calculus(self, difficulty: str) -> Dict[str, Any]:
        """
        生成导数题目
        
        Args:
            difficulty: 难度级别
        
        Returns:
            Dict[str, Any]: 题目数据
        """
        if difficulty == "基础":
            # 基础题：导数计算
            a = random.randint(2, 6)
            b = random.randint(1, 5)
            c = random.randint(1, 4)
            
            question = f"求函数f(x) = {a}x³ + {b}x² + {c}x + 1的导数f'(x)。"
            answer = f"f'(x) = {3*a}x² + {2*b}x + {c}"
            steps = [
                f"1. 应用幂函数求导法则：(x^n)' = nx^(n-1)",
                f"2. 对各项分别求导：",
                f"   ({a}x³)' = {3*a}x²",
                f"   ({b}x²)' = {2*b}x",
                f"   ({c}x)' = {c}",
                f"   (1)' = 0",
                f"3. 合并结果：f'(x) = {3*a}x² + {2*b}x + {c}"
            ]
        
        elif difficulty == "中档":
            # 中档题：单调性分析
            a = random.randint(1, 3)
            b = random.randint(-5, 5)
            
            question = f"求函数f(x) = {a}x² + {b}x + 1的单调递增区间。"
            # 求导并分析
            f_prime = f"{2*a}x + {b}"
            critical_point = -b / (2*a)
            
            if a > 0:
                interval = f"({critical_point:.2f}, +∞)"
            else:
                interval = f"(-∞, {critical_point:.2f})"
            
            answer = f"单调递增区间为{interval}"
            steps = [
                f"1. 求导：f'(x) = {2*a}x + {b}",
                f"2. 令f'(x) > 0，解不等式：",
                f"   {2*a}x + {b} > 0",
                f"   {2*a}x > -{b}",
                f"3. 当a > 0时，x > {-b}/{2*a} = {critical_point:.2f}",
                f"4. 因此单调递增区间为{interval}"
            ]
        
        else:  # 难题
            # 难题：极值和最值
            a = random.randint(1, 2)
            b = random.randint(3, 6)
            
            question = f"求函数f(x) = {a}x³ - {b}x + 1在区间[-2, 2]上的最大值和最小值。"
            # 求导
            f_prime = f"{3*a}x² - {b}"
            # 临界点
            critical_points = []
            if b > 0:
                critical_points = [math.sqrt(b/(3*a)), -math.sqrt(b/(3*a))]
            
            # 计算端点和临界点的函数值
            points = [-2] + critical_points + [2]
            f_values = [a*x**3 - b*x + 1 for x in points]
            max_val = max(f_values)
            min_val = min(f_values)
            
            answer = f"最大值为{max_val:.2f}，最小值为{min_val:.2f}"
            steps = [
                f"1. 求导：f'(x) = {3*a}x² - {b}",
                f"2. 令f'(x) = 0，解得x = ±√({b}/{3*a}) = ±{math.sqrt(b/(3*a)):.2f}",
                f"3. 计算区间端点和临界点的函数值：",
                f"   f(-2) = {a*(-8) - b*(-2) + 1:.2f} = {-8*a + 2*b + 1:.2f}",
                f"   f({-math.sqrt(b/(3*a)):.2f}) = {a*(-math.sqrt(b/(3*a)))**3 - b*(-math.sqrt(b/(3*a))) + 1:.2f}",
                f"   f({math.sqrt(b/(3*a)):.2f}) = {a*(math.sqrt(b/(3*a)))**3 - b*(math.sqrt(b/(3*a))) + 1:.2f}",
                f"   f(2) = {a*8 - b*2 + 1:.2f} = {8*a - 2*b + 1:.2f}",
                f"4. 比较函数值，最大值为{max_val:.2f}，最小值为{min_val:.2f}"
            ]
        
        return {
            "题目": question,
            "答案": answer,
            "解析": "\n".join(steps),
            "模块": "导数",
            "难度": difficulty,
            "公式": ["幂函数求导法则", "导数的加减法则", "单调性判断", "极值求法"],
            "采分点": ["导数计算正确", "临界点求解", "单调性分析", "最值计算正确"]
        }
    
    def generate_analytic_geometry(self, difficulty: str) -> Dict[str, Any]:
        """
        生成解析几何题目
        
        Args:
            difficulty: 难度级别
        
        Returns:
            Dict[str, Any]: 题目数据
        """
        if difficulty == "基础":
            # 基础题：直线方程
            x1 = random.randint(-5, 5)
            y1 = random.randint(-5, 5)
            slope = random.randint(-3, 3)
            if slope == 0:
                slope = 1
            
            question = f"求过点({x1}, {y1})且斜率为{slope}的直线方程。"
            # 点斜式方程
            if slope > 0:
                equation = f"y - {y1} = {slope}(x - {x1})"
            else:
                equation = f"y - {y1} = ({slope})(x - {x1})"
            # 化为一般式
            general = f"{slope}x - y + ({y1} - {slope*x1}) = 0"
            
            answer = f"点斜式：{equation}\n一般式：{general}"
            steps = [
                f"1. 应用点斜式方程：y - y1 = k(x - x1)",
                f"2. 代入已知点({x1}, {y1})和斜率{k}：y - {y1} = {slope}(x - {x1})",
                f"3. 整理为一般式：{slope}x - y + ({y1} - {slope*x1}) = 0"
            ]
        
        elif difficulty == "中档":
            # 中档题：圆的方程
            h = random.randint(-3, 3)
            k = random.randint(-3, 3)
            r = random.randint(2, 5)
            
            question = f"求以点({h}, {k})为圆心，半径为{r}的圆的方程。"
            answer = f"(x - {h})² + (y - {k})² = {r}²"
            steps = [
                f"1. 应用圆的标准方程：(x - h)² + (y - k)² = r²",
                f"2. 代入圆心({h}, {k})和半径{r}：(x - {h})² + (y - {k})² = {r}²",
                f"3. 展开为一般式：x² - {2*h}x + {h}² + y² - {2*k}y + {k}² = {r}²",
                f"4. 整理得：x² + y² - {2*h}x - {2*k}y + ({h}² + {k}² - {r}²) = 0"
            ]
        
        else:  # 难题
            # 难题：椭圆与直线的位置关系
            a = random.randint(3, 5)
            b = random.randint(2, a-1)
            m = random.randint(1, 3)
            
            question = f"已知椭圆方程为x²/{a}² + y²/{b}² = 1，直线y = {m}x + 1与椭圆相切，求m的值。"
            
            # 联立方程
            # x²/a² + (mx + 1)²/b² = 1
            # (b² + a²m²)x² + 2a²mx + a²(1 - b²) = 0
            # 判别式Δ = 0
            # 4a⁴m² - 4(b² + a²m²)a²(1 - b²) = 0
            # 化简得：m² = (a² - b²)/(a²b²) * (b² - 1)
            # 假设b > 1
            m_squared = (a**2 - b**2) * (b**2 - 1) / (a**2 * b**2)
            m_value = math.sqrt(m_squared)
            
            answer = f"m = ±{m_value:.2f}"
            steps = [
                f"1. 联立椭圆和直线方程：x²/{a}² + (mx + 1)²/{b}² = 1",
                f"2. 两边同乘a²b²消去分母：b²x² + a²(mx + 1)² = a²b²",
                f"3. 展开整理：({b}² + {a}²{m}²)x² + 2{a}²{m}x + {a}²(1 - {b}²) = 0",
                f"4. 直线与椭圆相切，判别式Δ = 0",
                f"5. 计算判别式：Δ = (2{a}²{m})² - 4({b}² + {a}²{m}²){a}²(1 - {b}²) = 0",
                f"6. 化简得：{m}² = ({a}² - {b}²)({b}² - 1)/({a}²{b}²)",
                f"7. 代入数值计算：{m}² = ({a**2 - b**2})({b**2 - 1})/({a**2 * b**2}) = {m_squared:.4f}",
                f"8. 解得：m = ±{m_value:.2f}"
            ]
        
        return {
            "题目": question,
            "答案": answer,
            "解析": "\n".join(steps),
            "模块": "解析几何",
            "难度": difficulty,
            "公式": ["直线方程", "圆的方程", "椭圆方程", "判别式"],
            "采分点": ["方程联立正确", "判别式应用", "化简过程", "结果正确"]
        }
    
    def export_problems(self, problems: List[Dict[str, Any]], file_path: str, export_mode: str = "题目+分步解析") -> bool:
        """
        导出题目
        
        Args:
            problems: 题目列表
            file_path: 文件路径
            export_mode: 导出模式
        
        Returns:
            bool: 导出是否成功
        """
        try:
            # 准备导出数据
            export_data = []
            for i, problem in enumerate(problems, 1):
                if export_mode == "仅题目":
                    content = f"{i}. {problem['题目']}"
                elif export_mode == "题目+答案":
                    content = f"{i}. {problem['题目']}\n   答案：{problem['答案']}"
                else:  # 题目+分步解析
                    content = f"{i}. {problem['题目']}\n   答案：{problem['答案']}\n   解析：\n{problem['解析'].replace('\n', '\n   ')}"
                
                export_data.append({
                    "序号": i,
                    "模块": problem["模块"],
                    "难度": problem["难度"],
                    "内容": content
                })
            
            # 导出数据
            DataIO.export_data(export_data, file_path, title=f"数学基础题型 - {len(problems)}题")
            return True
        except Exception as e:
            print(f"导出失败: {e}")
            return False


class MathProblemGeneratorGUI(GUIApp):
    """数学基础题型生成器GUI界面"""
    
    def __init__(self):
        """
        初始化GUI界面
        """
        super().__init__("数学基础题型自动生成器", width=900, height=600)
        self.generator = MathProblemGenerator()
        self.generated_problems = []
        
        # 创建主界面
        self.create_main_frame()
        
        # 添加菜单
        self.add_menu("文件", [
            {"label": "导出题目", "command": self.export_problems},
            {"separator": True},
            {"label": "退出", "command": self.destroy}
        ])
    
    def create_main_frame(self):
        """
        创建主界面
        """
        # 清空主框架
        for widget in self.main_frame.winfo_children():
            widget.destroy()
        
        # 配置区域
        config_frame = BaseFrame(self.main_frame, padding="10")
        config_frame.pack(side=tk.TOP, fill=tk.X)
        
        # 模块选择
        config_frame.create_label("模块选择：", 0, 0, sticky="w", pady=5)
        self.module_var = tk.StringVar(value="三角函数")
        modules = list(self.generator.modules.keys())
        module_combo = config_frame.create_combobox(modules, 0, 1, width=20)
        module_combo.config(textvariable=self.module_var)
        
        # 混合模式
        self.mixed_var = tk.BooleanVar(value=False)
        mixed_check = config_frame.create_checkbutton("混合模块", self.mixed_var, 0, 2, sticky="w", padx=20)
        
        # 难度选择
        config_frame.create_label("难度级别：", 0, 3, sticky="w", padx=20)
        self.difficulty_var = tk.StringVar(value="基础")
        difficulty_combo = config_frame.create_combobox(self.generator.difficulty_levels, 0, 4, width=15)
        difficulty_combo.config(textvariable=self.difficulty_var)
        
        # 题量设置
        config_frame.create_label("题量：", 0, 5, sticky="w", padx=20)
        self.count_var = tk.StringVar(value="20")
        count_entry = config_frame.create_entry(0, 6, width=10)
        count_entry.config(textvariable=self.count_var)
        
        # 生成按钮
        self.generate_button = config_frame.create_button("生成题目", self.generate_problems, 0, 7, sticky="e", padx=20)
        
        # 导出选项
        config_frame.create_label("导出模式：", 1, 0, sticky="w", pady=10)
        self.export_mode_var = tk.StringVar(value="题目+分步解析")
        mode1_radio = config_frame.create_radiobutton("仅题目", self.export_mode_var, "仅题目", 1, 1, sticky="w")
        mode2_radio = config_frame.create_radiobutton("题目+答案", self.export_mode_var, "题目+答案", 1, 2, sticky="w", padx=20)
        mode3_radio = config_frame.create_radiobutton("题目+分步解析", self.export_mode_var, "题目+分步解析", 1, 3, sticky="w", padx=20)
        
        # 导出按钮
        self.export_button = config_frame.create_button("导出题目", self.export_problems, 1, 4, sticky="e", padx=20)
        
        # 生成的题目显示区域
        self.problem_text = tk.Text(self.main_frame, width=100, height=30, wrap=tk.WORD, font=(".SF NS Text", 11))
        self.problem_text.pack(fill=tk.BOTH, expand=True, pady=10, padx=10)
        
        # 添加滚动条
        scrollbar = ttk.Scrollbar(self.main_frame, orient=tk.VERTICAL, command=self.problem_text.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y, pady=10)
        self.problem_text.config(yscrollcommand=scrollbar.set)
    
    def generate_problems(self):
        """
        生成题目
        """
        try:
            # 获取配置
            module = self.module_var.get()
            difficulty = self.difficulty_var.get()
            count = int(self.count_var.get())
            mixed = self.mixed_var.get()
            
            # 验证题量范围
            if count < 10 or count > 100:
                MessageBox.warning("提示", "题量必须在10-100之间")
                return
            
            # 生成题目
            if mixed:
                # 混合模块
                modules = list(self.generator.modules.keys())
                self.generated_problems = self.generator.generate_mixed_problems(modules, difficulty, count)
            else:
                # 单个模块
                self.generated_problems = self.generator.generate_problems(module, difficulty, count)
            
            # 显示题目
            self.display_problems()
            
            MessageBox.info("成功", f"成功生成 {len(self.generated_problems)} 道题目")
        except Exception as e:
            MessageBox.error("失败", f"生成题目失败: {e}")
    
    def display_problems(self):
        """
        显示生成的题目
        """
        self.problem_text.delete("1.0", tk.END)
        
        for i, problem in enumerate(self.generated_problems, 1):
            # 显示题目
            self.problem_text.insert(tk.END, f"{i}. {problem['题目']}\n", "question")
            self.problem_text.insert(tk.END, f"   答案：{problem['答案']}\n", "answer")
            self.problem_text.insert(tk.END, f"   解析：\n", "analysis")
            self.problem_text.insert(tk.END, f"{problem['解析']}\n\n", "analysis")
        
        # 配置文本样式
        self.problem_text.tag_config("question", font=(".SF NS Text", 12, "bold"))
        self.problem_text.tag_config("answer", font=(".SF NS Text", 11, "italic"), foreground="#0066cc")
        self.problem_text.tag_config("analysis", font=(".SF NS Text", 11), foreground="#333333")
    
    def export_problems(self):
        """
        导出题目
        """
        if not self.generated_problems:
            MessageBox.warning("提示", "请先生成题目")
            return
        
        # 选择导出路径
        file_path = FileDialog.save_file(
            title="导出题目",
            defaultextension=".xlsx",
            filetypes=[("Excel文件", "*.xlsx"), ("PDF文件", "*.pdf"), ("文本文件", "*.txt")]
        )
        
        if file_path:
            export_mode = self.export_mode_var.get()
            if self.generator.export_problems(self.generated_problems, file_path, export_mode):
                MessageBox.info("成功", f"题目已导出到 {file_path}")
            else:
                MessageBox.error("失败", "导出题目失败")


if __name__ == "__main__":
    # 测试代码
    app = MathProblemGeneratorGUI()
    app.run()
