# WorkPal 工作助手

Windows 系统托盘工具，专为需要在 WiFi 和有线网络间频繁切换的办公环境设计，同时提供防止 Teams / 钉钉等应用显示离线的保持在线功能。

## 功能

- **一键网络切换**：在 WiFi 和有线（以太网）之间切换，自动处理适配器启用/禁用和连接等待
- **保持在线**：每 60 秒模拟鼠标微移，防止 IM 软件显示离线状态
- **系统托盘常驻**：5 种状态图标实时反映当前网络和功能状态

## 系统要求

- Windows 10/11
- Python 3.11+
- 管理员权限（网络适配器操作必需）

## 快速开始

### 1. 安装依赖

```bash
python -m pip install -r requirements.txt
```

### 2. 配置

复制 `network_config.ini.example` 并重命名为 `network_config.ini`，按注释填写：

```ini
WIFI_ADAPTER_NAME=WLAN
ETHERNET_ADAPTER_NAME=以太网
WIFI_SSID=your_wifi_ssid
WIFI_PASSWORD=your_wifi_password
ETHERNET_PROGRAM_PATH=
```

### 3. 运行（需管理员权限）

```bash
python main.py
```

### 4. 打包为 exe

```bash
# 文件夹模式（推荐，启动快）
scripts\build_exe.bat

# 单文件模式（便于分发）
scripts\build_onefile.bat
```

### 5. 开机自启动

```powershell
# 启用（需管理员权限）
.\scripts\enable_autostart.ps1

# 禁用
.\scripts\disable_autostart.ps1
```

## 项目结构

```
WorkPal/
├── main.py                      # 入口文件
├── requirements.txt             # 依赖清单
├── network_config.ini.example   # 配置模板
├── WorkPal.spec                 # PyInstaller 文件夹模式打包配置
├── WorkPal_onefile.spec         # PyInstaller 单文件模式打包配置
├── workpal/                     # 核心包
│   ├── config.py                # 配置加载
│   ├── system.py                # 系统工具函数
│   ├── tray.py                  # 系统托盘 UI
│   └── features/
│       ├── network.py           # 网络切换逻辑（wmi + psutil）
│       └── keep_alive.py        # 保持在线功能
├── scripts/                     # 工具脚本
│   ├── gen_icons.py             # 图标生成（Pillow 绘制，无版权风险）
│   ├── build_exe.bat/.ps1       # 文件夹模式打包
│   ├── build_onefile.bat/.ps1   # 单文件模式打包
│   ├── enable_autostart.ps1     # 启用开机自启
│   └── disable_autostart.ps1    # 禁用开机自启
├── assets/                      # 生成的图标（不提交 git）
└── tests/                       # 单元测试
    ├── test_network.py
    └── test_keep_alive.py
```

## 图标说明

图标在首次运行构建脚本时自动生成（`scripts/gen_icons.py`），无需手动准备：

| 颜色/图案 | 含义 |
|-----------|------|
| 深灰 WiFi 图标 | 默认/空闲 |
| 蓝色 WiFi 图标 | 当前使用 WiFi |
| 绿色 网口图标 | 当前使用有线网络 |
| 橙色 旋转箭头 | 正在切换网络 |
| 紫色 心跳线 | 保持在线激活中 |

## 运行测试

```bash
python -m pytest tests/ -v
```

## 注意事项

- 切换网络适配器需要 **管理员权限**，请以管理员身份运行
- WiFi 连接依赖 Windows `netsh wlan` 命令，需要 WLAN AutoConfig 服务运行
- 单文件打包模式（onefile）首次启动较慢，因需解压临时文件

## License

MIT
