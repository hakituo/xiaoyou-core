# 将小悠AI项目上传到GitHub指南

## 准备工作

1. **确保敏感信息已保护**
   - 已创建`.gitignore`文件，会自动忽略`.env`文件（包含API密钥）
   - 已忽略历史记录、语音文件和日志等敏感数据

2. **注册GitHub账号**
   - 如果你还没有GitHub账号，请先在 [GitHub官网](https://github.com/) 注册

## 上传步骤

### 1. 初始化Git仓库（在项目目录下执行）
```bash
git init
git add .
git commit -m "初始化小悠AI项目"
```

### 2. 在GitHub官网上创建新仓库（这一步必须在GitHub网站完成）
- 登录GitHub官网
- 点击右上角的"+"图标，选择"New repository"
- 填写仓库名称（如"xiaoyou-core"）
- 选择公共或私有仓库
- 不要勾选"Initialize this repository with a README"（因为我们已经有README了）
- 点击"Create repository"

### 3. 使用本地Git软件关联并推送（在本地执行）
```bash
git remote add origin https://github.com/你的GitHub用户名/你的仓库名.git
git branch -M main
git push -u origin main
```

## 关于Git软件的说明

如果你已经安装了Git软件，你只需要：
1. 先在GitHub官网创建仓库（这一步无法绕过）
2. 然后使用你安装的Git软件（在命令行或图形界面中）执行关联和推送命令

这样就能将你的代码上传到GitHub了。

## 注意事项

1. **API密钥安全**
   - `.env`文件已在`.gitignore`中，不会被上传
   - 其他开发者需要创建自己的`.env`文件并填入他们的API密钥

2. **后续更新**
   ```bash
   git add .
   git commit -m "描述你的更改"
   git push origin main
   ```

3. **README文件**
   - README.md已更新为项目完整文档
   - 包含了所有必要的使用说明和配置信息

## 开源说明

本项目使用MIT许可证开源，允许他人自由使用、修改和分发，但需保留原始版权声明。