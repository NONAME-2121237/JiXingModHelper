# Changelog

## 1.0.1

### 修复

- 兼容新版 `%USERPROFILE%\AppData\LocalLow\feimo\AstralParty_CN\com.unity.addressables\AssetBundles` 热更新缓存
- 正确识别 Unity 缓存中的 `<缓存键>/<包哈希>/__data`，并映射回 Mod 使用的 `.bundle` 文件名
- 仅扫描最新 Addressables catalog 仍有效的缓存项，避免误用旧版本残留
- 安装、备份、还原、预览和作品集制作统一支持新版缓存布局
- 游戏资源版本变化后自动丢弃旧索引，避免显示已经失效的包

## 1.0.0

### 功能

- 本地安装、禁用、启用、卸载 Mod（文件夹、ZIP、RAR）
- 安装前自动备份，支持单 Mod 还原与一键全还原
- 浏览 Addressable 资源：贴图、文本、3D 模型、动画
- 贴图细分类与 PNG/JPG、文本、OBJ、动画数据导出
- 作品集支持多资源打包、裁剪换图、导出 ZIP 和直接安装
- HTML 前端由 C# WebView2 原生窗口承载，Python 仅提供本地接口

### 修复

- 作品集换图和裁剪换图后自动同步安装到游戏
- 从作品集移除项目时正确回退对应资源，不再残留旧 bundle
- 多个 Mod 修改同一 bundle 时，按最后启用顺序正确覆盖与恢复
- 禁止 WebView2 创建浏览器新窗口，并增加应用单实例保护
- ZIP/RAR 分析与安装复用临时目录，完成或退出后自动清理

### 安全说明

- 仅替换本地 bundle 文件，不注入进程、不读内存
- 默认自检只使用系统临时目录，不修改真实游戏与作品集
