import os
import markdown
import traceback

def convert_md_to_html(md_file_path, output_html_path):
    try:
        print(f"正在处理文件: {md_file_path}")
        
        # 检查文件是否存在
        if not os.path.exists(md_file_path):
            print(f"错误: 文件不存在 - {md_file_path}")
            return False
        
        # 读取Markdown文件内容
        print("正在读取文件内容...")
        with open(md_file_path, 'r', encoding='utf-8') as f:
            md_content = f.read()
        print(f"成功读取文件，内容长度: {len(md_content)} 字符")
        
        # 转换为HTML（使用基本功能）
        print("正在转换为HTML...")
        html_content = markdown.markdown(md_content)
        print(f"成功转换为HTML，HTML长度: {len(html_content)} 字符")
        
        # 添加基本的HTML头部和样式
        print("正在添加HTML头部和样式...")
        # 简化样式，使用简单字符串拼接
        html_head = """
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <title>论文转换</title>
            <style>
                body { font-family: Arial, sans-serif; line-height: 1.6; max-width: 210mm; margin: 0 auto; padding: 2cm; }
                h1, h2, h3, h4, h5, h6 { color: #333; margin-top: 1.5em; }
                table { border-collapse: collapse; width: 100%; margin: 20px 0; }
                th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }
                th { background-color: #f2f2f2; }
                code { background-color: #f5f5f5; padding: 2px 4px; border-radius: 4px; }
                pre { background-color: #f5f5f5; padding: 1em; border-radius: 4px; overflow-x: auto; }
            </style>
        </head>
        <body>
        """
        
        html_foot = """
        </body>
        </html>
        """
        
        # 构建完整HTML
        full_html = html_head + html_content + html_foot
        
        # 确保输出目录存在
        output_dir = os.path.dirname(output_html_path)
        if not os.path.exists(output_dir):
            print(f"创建输出目录: {output_dir}")
            os.makedirs(output_dir)
        
        # 写入HTML文件
        print(f"正在写入HTML文件: {output_html_path}")
        with open(output_html_path, 'w', encoding='utf-8') as f:
            f.write(full_html)
        print(f"HTML文件写入完成，文件大小: {len(full_html)} 字符")
        
        # 验证文件是否成功创建
        if os.path.exists(output_html_path):
            print(f"转换成功！HTML文件已保存至: {output_html_path}")
            return True
        else:
            print(f"警告: HTML文件似乎没有成功创建: {output_html_path}")
            return False
    except Exception as e:
        print(f"转换失败: {str(e)}")
        print("详细错误信息:")
        traceback.print_exc()
        return False

if __name__ == "__main__":
    # 英文论文路径
    en_paper_path = "d:\\AI\\xiaoyou-core\\Thesis\\EN\\High-Performance_Asynchronous_AI_Agent_Core_System_Design_and_Implementation_for_Resource-Constrained_Environments.md"
    en_output_html = "d:\\AI\\xiaoyou-core\\Thesis\\EN\\paper_en.html"
    
    print("开始转换英文论文...")
    convert_md_to_html(en_paper_path, en_output_html)
    
    # 检查是否存在中文论文目录
    cn_dir = "d:\\AI\\xiaoyou-core\\Thesis\\CN"
    if os.path.exists(cn_dir):
        # 尝试找到中文论文文件
        cn_files = [f for f in os.listdir(cn_dir) if f.endswith('.md')]
        if cn_files:
            cn_paper_path = os.path.join(cn_dir, cn_files[0])
            cn_output_html = "d:\\AI\\xiaoyou-core\\Thesis\\CN\\paper_cn.html"
            print(f"\n开始转换中文论文: {cn_files[0]}...")
            convert_md_to_html(cn_paper_path, cn_output_html)
    
    print("\n转换完成！请注意，生成的是HTML文件。要获取PDF或DOCX格式，您可以：")
    print("1. 在浏览器中打开HTML文件，然后打印为PDF")
    print("2. 使用Word等办公软件打开HTML文件，然后另存为DOCX格式")
    print("3. 安装pandoc工具，使用命令: pandoc input.md -o output.pdf 或 pandoc input.md -o output.docx")