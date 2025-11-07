#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import json
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle, KeepTogether, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY

class PDFReportGenerator:
    def __init__(self, results_file="comprehensive_results.json", output_file="comprehensive_experiment_report.pdf"):
        self.results_file = results_file
        self.output_file = output_file
        self.results = self._load_results()
        self.CHART_WIDTH = 15
        self.CHART_HEIGHT = 7.5
        self.temp_images = self._get_temp_images()
    
    def _load_results(self):
        """加载实验结果JSON文件"""
        if os.path.exists(self.results_file):
            with open(self.results_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}
    
    def _get_temp_images(self):
        """获取临时图表文件列表"""
        # 这里简化处理，实际可能需要根据具体情况修改
        return [
            "chart_0.png", # 隔离性 - 延迟
            "chart_1.png", # 隔离性 - 总时间
            "chart_2.png", # 异步I/O性能对比
            "chart_3.png", # 异步调度开销评估
            "chart_4.png", # 缓存策略测试
            "chart_5.png"  # 并发性能测试
        ]
    
    def _add_cover_page(self, elements, styles):
        """添加封面页"""
        title_style = ParagraphStyle('CustomTitle', parent=styles['Title'], fontSize=24, textColor=colors.HexColor('#333333'), alignment=1)
        subtitle_style = ParagraphStyle('CustomSubtitle', parent=styles['Heading1'], fontSize=18, textColor=colors.HexColor('#555555'), alignment=1)
        
        elements.append(Paragraph("综合实验报告", title_style))
        elements.append(Paragraph("高性能异步AI Agent核心系统性能测试", subtitle_style))
        elements.append(Spacer(1, 2*cm))
    
    def _add_page_number(self, canvas, doc):
        """添加页码"""
        canvas.saveState()
        canvas.setFont('Helvetica', 10)
        canvas.drawString(19*cm, 2.5*cm, f"页码: {doc.page}")
        canvas.restoreState()
    
    def generate_pdf(self):
        """生成PDF报告 - [已修正图表索引]"""
        print(f"正在生成PDF报告: {self.output_file}")
        
        # --- [样式定义... 保持不变] ---
        # 创建PDF文档 - 优化页边距
        doc = SimpleDocTemplate(
            self.output_file,
            pagesize=A4,
            rightMargin=2*cm,
            leftMargin=2*cm,
            topMargin=2*cm,
            bottomMargin=2.5*cm  # 增加底部边距以容纳页脚
        )
        
        # 创建样式
        styles = getSampleStyleSheet()
        
        # 定义统一的中文字体
        chinese_font = 'Helvetica'  # 默认字体
        if pdfmetrics.getRegisteredFontNames():
            for font_name in ['SimHei', 'MicrosoftYaHei', 'SimSun']:
                if font_name in pdfmetrics.getRegisteredFontNames():
                    chinese_font = font_name
                    break
        
        # 定义自定义样式 (保持不变)
        title_style = ParagraphStyle('CustomTitle', parent=styles['Title'], fontSize=24, textColor=colors.HexColor('#333333'), alignment=1, spaceAfter=2*cm, fontName=chinese_font)
        subtitle_style = ParagraphStyle('CustomSubtitle', parent=styles['Heading1'], fontSize=18, textColor=colors.HexColor('#555555'), spaceAfter=1*cm, spaceBefore=1.5*cm, fontName=chinese_font)
        section_style = ParagraphStyle('CustomSection', parent=styles['Heading2'], fontSize=16, textColor=colors.HexColor('#444444'), spaceAfter=0.8*cm, spaceBefore=1*cm, fontName=chinese_font)
        content_style = ParagraphStyle('CustomContent', parent=styles['Normal'], fontSize=12, leading=20, textColor=colors.HexColor('#333333'), leftIndent=20, spaceAfter=0.5*cm, fontName=chinese_font)
        info_style = ParagraphStyle('InfoStyle', parent=content_style, alignment=1)
        config_style = ParagraphStyle('ConfigStyle', parent=content_style, alignment=0, leftIndent=20, spaceAfter=0.3*cm)
        centered_title_style = ParagraphStyle('CenteredTitleStyle', parent=content_style, alignment=1, spaceAfter=0.5*cm)
        # --- [样式定义结束] ---

        # 创建内容列表
        elements = []
        
        # 添加封面页
        self._add_cover_page(elements, styles)
        
        # --- [实验信息 和 执行摘要 ... 保持不变] ---
        # (代码从 generate_pdf_report(3).py 复制，保持原样)
        combined_info_summary = []
        combined_info_summary.append(Paragraph("实验信息", subtitle_style))
        combined_info_summary.append(Paragraph(f"实验环境: {self.results.get('config', {}).get('working_directory', '未知')}", content_style))
        combined_info_summary.append(Paragraph(f"重复次数: {self.results.get('config', {}).get('repetitions', '未知')}", content_style))
        combined_info_summary.append(Spacer(1, 0.5*cm))
        combined_info_summary.append(Paragraph("实验配置:", content_style))
        combined_info_summary.append(Paragraph("● 处理器: AMD Ryzen 5 with Radeon Vega 8 Graphics", config_style))
        combined_info_summary.append(Paragraph("● 内存: 6GB DDR4 RAM", config_style))
        combined_info_summary.append(Paragraph("● 存储: 1TB SSD", config_style))
        combined_info_summary.append(Paragraph("● 网络: 通过Wi-Fi 5 (802.11ac)连接的局域网(LAN)，工作在5 GHz频段。客户端和服务器之间的一致链路速度为433 Mbps。", config_style))
        combined_info_summary.append(Paragraph("● 软件环境: Python 3.12.4, asyncio (内置模块), psutil 7.1.2, matplotlib 3.10.7, reportlab 4.4.4", config_style))
        combined_info_summary.append(Spacer(1, 0.5*cm))
        combined_info_summary.append(Paragraph("执行摘要", subtitle_style))
        combined_info_summary.append(Paragraph("关键发现:", section_style))
        isolation_summary = self.results['experiments']['experiment_isolation']['summary']
        combined_info_summary.append(Paragraph(f"• {isolation_summary['key_observation']}", content_style))
        combined_info_summary.append(Paragraph(f"• 同步模式短任务延迟: {isolation_summary['sync_short_latency']:.4f} 秒", content_style))
        combined_info_summary.append(Paragraph(f"• 异步模式短任务延迟: {isolation_summary['async_short_latency']:.4f} 秒", content_style))
        if 'experiment_1' in self.results['experiments']:
            asyncio_data = self.results['experiments']['experiment_1']
            max_improvement = 0
            max_improvement_key = ""
            for key, data in asyncio_data.items():
                improvement = data['aggregates'].get('improvement_pct', 0)
                if improvement > max_improvement:
                    max_improvement = improvement
                    max_improvement_key = key
            combined_info_summary.append(Paragraph(f"• 在 {max_improvement_key} 负载下，异步模式性能提升 {max_improvement:.2f}%", content_style))
        if 'experiment_4' in self.results['experiments']:
            concurrency_data = self.results['experiments']['experiment_4']
            max_concurrency = concurrency_data.get('max_successful_concurrency', 0)
            combined_info_summary.append(Paragraph(f"• 系统最大稳定并发用户数: {max_concurrency}", content_style))
        elements.append(KeepTogether(combined_info_summary))
        elements.append(PageBreak())
        # --- [摘要结束] ---
        
        # --- [以下是修正后的图表章节] ---
        
        # 1. 负载隔离性测试 (图表 0 和 1)
        elements.append(Paragraph("1. 负载隔离性测试", subtitle_style))
        elements.append(Paragraph("测试目标: 评估异步微服务架构在处理长耗时任务时对短任务响应时间的影响。", content_style))
        elements.append(Paragraph("测试方法:", content_style))
        elements.append(Paragraph("• 同步模式: 长任务完成后再执行短任务", content_style))
        elements.append(Paragraph("• 异步模式: 长任务在后台执行，短任务立即响应", content_style))
        elements.append(Spacer(1, 0.5*cm))
        
        isolation_content = []
        isolation_content.append(Paragraph("隔离性测试结果对比图:", centered_title_style))
        
        # 插入图表 0: 隔离性 - 延迟
        if len(self.temp_images) > 0 and os.path.exists(self.temp_images[0]):
            img_latency = Image(self.temp_images[0], width=self.CHART_WIDTH*cm, height=self.CHART_HEIGHT*cm)
            img_latency.hAlign = 'CENTER'
            isolation_content.append(img_latency)
            isolation_content.append(Spacer(1, 0.5*cm))
        
        # 插入图表 1: 隔离性 - 总时间
        if len(self.temp_images) > 1 and os.path.exists(self.temp_images[1]):
            img_total = Image(self.temp_images[1], width=self.CHART_WIDTH*cm, height=self.CHART_HEIGHT*cm)
            img_total.hAlign = 'CENTER'
            isolation_content.append(img_total)
            
        isolation_content.append(Spacer(1, 0.5*cm))
        isolation_content.append(Paragraph(f"结论: {isolation_summary['conclusion']}", content_style))
        
        elements.append(KeepTogether(isolation_content))
        elements.append(PageBreak())
        
        # 2. 异步I/O性能测试 (图表 2)
        elements.append(Paragraph("2. 异步I/O性能对比", subtitle_style))
        elements.append(Paragraph("测试目标: 评估不同负载大小和并发级别下，异步I/O操作相比同步I/O的性能提升。", content_style))
        
        asyncio_content = []
        asyncio_content.append(Spacer(1, 0.5*cm))
        asyncio_content.append(Paragraph("异步I/O性能对比图:", centered_title_style))
        
        # --- 修正: 从 temp_images[1] 改为 temp_images[2] ---
        if len(self.temp_images) > 2 and os.path.exists(self.temp_images[2]):
            img_async_io = Image(self.temp_images[2], width=self.CHART_WIDTH*cm, height=self.CHART_HEIGHT*cm)
            img_async_io.hAlign = 'CENTER'
            asyncio_content.append(img_async_io)
        
        asyncio_content.append(Spacer(1, 0.5*cm))
        
        # (详细数据表格... 保持不变)
        if 'experiment_1' in self.results['experiments']:
            asyncio_content.append(Paragraph("详细性能数据:", content_style))
            if 'small_10' in self.results['experiments']['experiment_1']:
                small_10_data = self.results['experiments']['experiment_1']['small_10']
                agg_data = small_10_data['aggregates']
                small_table_data = [['指标', '同步模式', '异步模式', '性能提升'],
                                    ['平均执行时间 (秒)', f"{agg_data['avg_sync_time']:.4f}", f"{agg_data['avg_async_time']:.4f}", f"{agg_data['improvement_pct']:.2f}%"]]
                col_widths = [140, 100, 100, 90]
                small_table = Table(small_table_data, colWidths=col_widths)
                small_table.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#f0f0f0')),
                    ('TEXTCOLOR', (0, 0), (-1, 0), colors.HexColor('#333333')),
                    ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                    ('FONTNAME', (0, 0), (-1, 0), chinese_font + '-Bold' if chinese_font + '-Bold' in pdfmetrics.getRegisteredFontNames() else chinese_font),
                    ('FONTNAME', (0, 1), (-1, -1), chinese_font),
                    ('FONTSIZE', (0, 0), (-1, -1), 10),
                    ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                    ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#cccccc'))
                ]))
                asyncio_content.append(small_table)
        
        elements.append(KeepTogether(asyncio_content))
        elements.append(PageBreak())
        
        # 3. 缓存策略测试 (图表 4)
        elements.append(Paragraph("3. 缓存策略测试", subtitle_style))
        elements.append(Paragraph("测试目标: 评估不同缓存策略对系统性能的影响。", content_style))
        
        caching_content = []
        caching_content.append(Spacer(1, 0.2*cm))
        caching_content.append(Paragraph("缓存性能测试图:", centered_title_style))
        
        # --- 修正: 从 temp_images[3] 改为 temp_images[4] ---
        if len(self.temp_images) > 4 and os.path.exists(self.temp_images[4]):
            img_caching = Image(self.temp_images[4], width=14*cm, height=6*cm) # 尺寸可以按需调整
            img_caching.hAlign = 'CENTER'
            caching_content.append(img_caching)
        
        if 'experiment_3' in self.results['experiments']:
            caching_data = self.results['experiments']['experiment_3']
            caching_content.append(Paragraph(f"• 缓存命中率: {caching_data.get('hit_rate', 0):.2f}%", content_style))
        
        elements.append(KeepTogether(caching_content))
        # (我们把这个和下一个实验放在同一页，如果空间允许)
        elements.append(Spacer(1, 1.0*cm))

        # 4. 异步调度开销评估 (图表 3)
        elements.append(Paragraph("4. 异步调度开销评估", subtitle_style))
        elements.append(Paragraph("测试目标: 量化异步调度层的单任务时间开销。", content_style))
        
        optimization_content = []
        optimization_content.append(Spacer(1, 0.2*cm))
        optimization_content.append(Paragraph("异步调度开销评估图:", centered_title_style))
        
        # --- 修正: 从 temp_images[4] 改为 temp_images[3] ---
        if len(self.temp_images) > 3 and os.path.exists(self.temp_images[3]):
            img_optimization = Image(self.temp_images[3], width=15*cm, height=7.5*cm)
            img_optimization.hAlign = 'CENTER'
            optimization_content.append(img_optimization)
        
        # (核心论断... 保持不变)
        p_bold = ParagraphStyle('BoldP', parent=content_style, fontName=chinese_font + '-Bold' if chinese_font + '-Bold' in pdfmetrics.getRegisteredFontNames() else chinese_font, fontSize=9, leading=12, alignment=TA_JUSTIFY)
        if 'experiment_2' in self.results['experiments']:
            experiment_2_data = self.results['experiments']['experiment_2']
            improvement_pct = experiment_2_data.get('improvement_pct', 0)
            conclusion_text = f"""
            <font color='red'><b>【核心论断：并行开销与权衡】</b></font> 异步调度增加了约 {abs(improvement_pct):.2f}% 的单任务开销，但确保了系统的实时交互能力。
            """
            optimization_content.append(Paragraph(conclusion_text, p_bold))
        
        elements.append(KeepTogether(optimization_content))
        elements.append(PageBreak())
        
        # 5. 并发性能测试 (图表 5)
        elements.append(Paragraph("5. 并发性能测试", subtitle_style))
        elements.append(Paragraph("测试目标: 评估系统在不同并发用户数下的稳定性和吞吐量。", content_style))
        
        concurrency_content = []
        concurrency_content.append(Spacer(1, 0.5*cm))
        concurrency_content.append(Paragraph("并发性能测试图:", centered_title_style))
        
        # --- 修正: 从 temp_images[2] 改为 temp_images[5] ---
        if len(self.temp_images) > 5 and os.path.exists(self.temp_images[5]):
            img_concurrency = Image(self.temp_images[5], width=self.CHART_WIDTH*cm, height=self.CHART_HEIGHT*cm)
            img_concurrency.hAlign = 'CENTER'
            concurrency_content.append(img_concurrency)
        
        concurrency_content.append(Spacer(1, 0.5*cm))
        
        # (并发测试数据... 保持不变)
        if 'experiment_4' in self.results['experiments']:
            concurrency_data = self.results['experiments']['experiment_4']
            concurrency_content.append(Paragraph("并发测试关键数据:", content_style))
            concurrency_content.append(Paragraph(f"• 最大稳定并发用户数: {concurrency_data.get('max_successful_concurrency', 0)}", content_style))
            max_throughput = max(concurrency_data['avg_throughput'])
            max_throughput_idx = concurrency_data['avg_throughput'].index(max_throughput)
            optimal_concurrency = concurrency_data['concurrency_levels'][max_throughput_idx]
            concurrency_content.append(Paragraph(f"• 最佳并发用户数: {optimal_concurrency}", content_style))
            concurrency_content.append(Paragraph(f"• 最大吞吐量: {max_throughput:.2f} 请求/秒", content_style))
        
        elements.append(KeepTogether(concurrency_content))
        elements.append(PageBreak())
        
        # --- [综合结论 ... 保持不变] ---
        elements.append(Paragraph("综合结论", subtitle_style))
        elements.append(Paragraph("基于本次综合实验的结果，我们得出以下结论:", content_style))
        elements.append(Spacer(1, 0.5*cm))
        elements.append(Paragraph("1. 负载隔离性:", section_style))
        elements.append(Paragraph(isolation_summary['conclusion'], content_style))
        elements.append(Paragraph("2. 异步性能:", section_style))
        elements.append(Paragraph("异步I/O操作在并发场景下展现出显著的性能优势，特别是在处理多个并发请求时。随着并发用户数的增加，性能提升更为明显。", content_style))
        elements.append(Paragraph("3. 并发能力:", section_style))
        elements.append(Paragraph("系统能够在保证低错误率的前提下，支持较高的并发用户访问。在最佳并发用户数下，系统能够提供最大的吞吐量。", content_style))
        elements.append(Paragraph("4. 优化建议:", section_style))
        elements.append(Paragraph("• 推荐采用异步微服务架构以提高系统的响应性和吞吐量", content_style))
        elements.append(Paragraph("• 在高并发场景下，应特别关注系统的错误率，避免服务过载", content_style))
        elements.append(Paragraph("• 可进一步优化缓存策略和资源分配以提升整体性能", content_style))
        elements.append(Paragraph("• 考虑引入GPU加速和多线程优化以应对更复杂的计算任务", content_style))
        
        # 生成PDF，添加页脚
        doc.build(elements, onFirstPage=self._add_page_number, onLaterPages=self._add_page_number)
        print(f"PDF报告生成完成: {self.output_file}")
        print(f"PDF文件大小: {os.path.getsize(self.output_file) / 1024:.2f} KB")

# 主函数入口
if __name__ == "__main__":
    print("开始生成PDF报告...")
    try:
        # 创建PDF生成器实例
        generator = PDFReportGenerator()
        # 生成PDF报告
        generator.generate_pdf()
        print("PDF报告生成成功！")
    except Exception as e:
        print(f"生成PDF报告时出错: {str(e)}")
        import traceback
        traceback.print_exc()