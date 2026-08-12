# ArkPaint · 拼豆自动绘图工具

把任意图片转为 **24×24** 像素稿，通过 **ADB** 控制 MuMu 模拟器，在游戏拼豆玩法中自动填色。

## 源码与发布包（分离）

| 内容 | 路径 | 是否进 GitHub |
|------|------|----------------|
| 源码与配置 | `arkpaint/`、`main.py`、`*.spec`、`requirements.txt` 等 | ✅ 提交 |
| 构建中间文件 | `build/` | ❌ 忽略 |
| 可分发程序 | `dist/arkpaint/`（含 `ArkPaint.exe`） | ❌ 忽略 |
| 虚拟环境 | `.venv313/` | ❌ 忽略 |
| 运行时数据 | `data/`（校准、设置） | ❌ 忽略 |

本地打包后，把 **`dist\arkpaint\` 整个文件夹** 发给用户即可；GitHub 只托管源码。

## 功能概览

1. 导入 / 拖入 / 框选截图 → 量化为 24×24，左侧对照原图与像素预览  
2. 中央画布：涂色、撤回、编号开关、滚轮缩放、边缘平移、导出 PNG  
3. ADB 连接 MuMu（可填端口 / 选 adb 路径 / 自动检测多开端口）  
4. 「校准并识别」→「开始绘图」，进度条显示当前色与填涂进度  

## 给最终用户

运行 `build_exe.bat` 后分发：

```
dist/arkpaint/
  ArkPaint.exe
  tools/
    adb.exe
    AdbWinApi.dll
    AdbWinUsbApi.dll
```

双击 `ArkPaint.exe`。MuMu 12 常见 ADB：`127.0.0.1:16384`（多开端口按 +32 递增）。

## 开发运行

需要 **Python 3.10+**（推荐 3.13）：

```bash
cd D:\Q\project\arkpaint
python -m venv .venv313
.venv313\Scripts\activate
pip install -r requirements.txt
.venv313\Scripts\python.exe main.py
```

## 打包 EXE

```bat
build_exe.bat
```

产物仅在本地：`dist\arkpaint\`（不进入 Git 仓库）。

## 源码目录

```
arkpaint/          # Python 源码
assets/            # 可选识别参考图
main.py            # 入口
ArkPaint.spec      # PyInstaller 配置
build_exe.bat      # 一键打包
requirements.txt
```

## 说明

- 默认色盘约 **40** 色；校准保存时会采样可见色。  
- 白色格默认可跳过。  
- 分辨率变化后请重新「校准并识别」。
