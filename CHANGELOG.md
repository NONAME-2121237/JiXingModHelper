# Changelog

## 1.0.0

### 功能

- 本地安装 / 禁用 / 启用 / 卸载 Mod（文件夹、ZIP、RAR）
- 安装前自动备份，支持单 Mod 还原与一键全还原
- 浏览 Addressable 资源：贴图 / 文本 / 3D 模型 / 动画
- 贴图细分类（手牌、事件、筹码、格子、角色动作帧等）
- 导出：PNG/JPG、文本、OBJ、动画 JSON/二进制
- 替换：贴图、文本、动画（3D 模型仅导出；音效不在 bundle 内故不支持）
- 作品集：多资源打包、导出 ZIP、直接安装
- 默认 HTML + pywebview 界面；`--legacy` 可回退 customtkinter

### 安全说明

- 仅替换本地 `*.bundle` 文件，不注入进程、不读内存
