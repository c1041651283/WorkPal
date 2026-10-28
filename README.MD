# WorkPal 工作助手

Windows 系统托盘工具，专为需要在 WiFi 和有线网络间频繁切换的办公环境设计，同时提供防止 Teams / 钉钉等应用显示离线的保持在线功能。

## 功能

- **一键网络切换**：在 WiFi 和有线（以太网）之间切换，自动处理适配器启用/禁用和连接等待；WiFi 使用 Windows 已保存的配置，WorkPal 不保存 WiFi 密码
- **保持在线**：通过 Windows API 阻止系统息屏/睡眠，并在检测到用户真实空闲超过 3 分钟时，通过 `SendInput(F15)` 可靠重置系统空闲计时器，防止 Teams 等 IM 软件将状态切换为离线；程序退出后系统自动恢复正常电源策略
- **系统托盘常驻**：5 种状态图标实时反映当前网络和功能状态
- **开机自启动**：可从托盘启用/禁用 Windows 任务计划自启动
- **运行保护**：同一用户会话只运行一份 WorkPal；网络切换失败时尝试恢复原连接，并报告恢复结果
- **代理守护**：手动开启定时检查或执行单次修复，默认每 60 秒检查；支持公司有线和 FortiClient，在已确认公司网络可用时恢复固定代理

## 代理守护

每次启动 WorkPal 时，自动开启公司脚本代理、关闭手动代理，守护保持未开启。此操作会先保留原代理备份。

右键 WorkPal 托盘，打开 `代理守护`：

- **开启脚本代理（关闭手动代理）**：随时切回启动时的状态。如果守护正在运行，会先暂停，避免它马上切回手动代理。此按钮不启动或重启 iNetSec、不检查检疫结果。
- **开启定时守护**：立即检查一次，随后默认每 60 秒检查（另加查询耗时）。公司有线网卡已连接且公司代理可达，或 VPN 有有效 IP 且公司代理可达时，恢复固定代理 `proxy.ricoh.co.jp:8080` 并关闭系统 PAC、自动检测。
- **立即检查并修复一次**：不需要先开启守护。检查后即结束；如果定时守护已经开启，则唤醒现有检查线程，不重复启动。无法确认公司网络时保持原样。
- **检查间隔**：可选 1、2、5 分钟，保存在用户设置中；从下一次检查完成后采用新间隔。也可用 `PROXY_CHECK_INTERVAL` 配置 30–3600 秒。
- **暂停守护（保留当前代理）**：停止检查，不还原旧脚本。退出 WorkPal 也保持当前代理；重新启动 WorkPal 后仍需手动开启守护。
- **恢复接管前的代理**：停止检查并显式恢复原代理备份。备份保留最初接管时的值，暂停后再次开启不会覆盖它。

代理被外部程序改回脚本后，守护会在下一次确认公司网络可用的检查中修复；配置正确时不会重复写入。修改代理的例外列表、PAC 地址仍会保留。需要自己调整代理时请先暂停守护。检查之间仍可能有短暂访问失败，可点击“立即检查并修复一次”。

在公司：启动 WorkPal 后按原来的方式完成检疫，看到 iNetSec 绿色 OK 后，自行点击 **开启定时守护**。WorkPal 没有检疫等待、通过确认或自动开启守护的流程；从 WiFi 切到有线也不会开启守护。需要重新使用脚本时，点击新增的脚本代理按钮即可。

启动及按钮使用的脚本地址由 `OFFICE_PAC_URL` 指定，默认 `http://proxy.psh.com.cn/proxy-psh1.pac`。原固定代理地址和例外列表保留，原代理整体设置可通过“恢复接管前的代理”还原。暂停和退出保留当前代理；**下次启动会再次切到脚本代理**。

### 在家使用 FortiClient

1. 连接家庭网络。选择 `代理守护 → 在家连接 / 重新连接公司`。
2. 用户主动点击该入口后，如果公司网络尚不可用，WorkPal 临时关闭系统代理，再打开已安装的 FortiClient；即使网卡状态暂时未知，也允许用户准备重新登录。公司网络已经可用时不关闭代理、不重连。
3. 在 FortiClient 中自行登录、连接和输入验证码；WorkPal 不保存或填写凭据。
4. 连续两次确认 VPN 有有效 IP、公司代理 TCP 端口可达后开启固定代理。可以点击“立即检查并修复一次”主动检查；该操作确认就绪后即可修复，无需等待两个定时间隔。
5. 用 FortiClient 自己的断开按钮断开。连续三次确认断线后关闭系统代理；按默认间隔可能需要约 3 分钟。需要马上重新连接时，直接点击“在家连接 / 重新连接公司”；守护仍在运行也可以使用，不用暂停或恢复旧代理。

公司网络可用时不重连，也不会临时关闭代理。在公司有线网络可用时，不要求 VPN 连接。自动检查遇到网卡读取失败会保持当前代理，不把未知状态当作断线。在家模式下，如果网卡仍显示连接、但公司代理连续三次不可达，会临时关闭系统代理，并明确显示“公司代理不可达”；这不等同于确认 VPN 断开。恢复可达后继续自动启用固定代理。

### 锁屏、休眠和唤醒

守护开启时，Windows 解锁或唤醒事件会立即触发复查，并最多追加两次间隔 5 秒的检查，之后恢复用户选择的 1/2/5 分钟间隔。未开启守护时不会因为唤醒而自动开启。相近的重复唤醒事件会合并。

菜单显示最近检查时间，以及“VPN 已断开”“公司代理不可达”或“无法确认 VPN 状态”。网卡读取使用 Windows IP Helper；菜单刷新也不再调用 WMI/netsh，避免旧查询阻塞状态更新。

若 FortiClient 要求重新认证，点击“在家连接 / 重新连接公司”，再手动登录或输入验证码即可。WorkPal 不替用户登录、不改变 VPN 超时策略，也不阻止 Windows 正常锁屏或休眠。

助手只操作**当前用户 Windows LAN 代理**，不修改 WinHTTP、VPN 专用代理、FortiClient 配置/服务、网卡、DNS 或路由。守护运行期间阻止 WorkPal 切换网卡；暂停后可使用网络切换功能。保存备份期间收到暂停请求会取消本次代理写入；临时关闭代理后、尚未启动 FortiClient 时收到暂停请求，或 GUI 启动失败时，会撤销本次临时关闭。撤销失败会报告错误并保留恢复备份。

备份位于 `%LOCALAPPDATA%\WorkPal\vpn_proxy_session.json`；变更及错误记录在同目录 `app.log` 中。写入备份失败时不修改系统代理。现有 v1.1.0 备份可以继续使用；启动时设置脚本代理，但不自动开启守护。操作失败会通知，不阻止托盘启动。

`FORTICLIENT_PATH` 可指定已有的 FortiClient.exe，留空时查找默认安装目录；`VPN_PROXY_SERVER` 指定公司固定代理。这些配置不涉及 VPN 服务器、密码或证书。

### Edge 公司网页快捷方式

桌面创建快捷方式，目标填写：

```text
"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" --user-data-dir="%LOCALAPPDATA%\Microsoft\Edge-Company-PAC" --proxy-pac-url="http://proxy.psh.com.cn/proxy-psh1.pac"
```

命名为 `Edge－公司网页`。此窗口使用独立登录数据和公司 PAC，原有 Edge 继续使用系统代理。首次使用需要重新登录公司网页。公司强制的 Edge 代理策略或 UserDataDir 策略可能覆盖启动参数，应通过 `edge://policy` 检查，不能靠这个快捷方式绕过公司策略。

实现依据：[Edge 代理启动参数](https://learn.microsoft.com/en-us/deployedge/edge-learnmore-cmdline-options-proxy-settings)、[WinINet 代理选项](https://learn.microsoft.com/en-us/windows/win32/api/wininet/ns-wininet-internet_per_conn_optionw)。本功能不执行 FortiClient CLI 命令，兼容本机现有的 7.2.1 客户端，不要求升级。

## 系统要求

- Windows 10/11
- Python 3.11+
- 管理员权限（网络适配器操作必需）

## 快速开始

### 1. 安装依赖

```bash
python -m pip install -r requirements.txt
```

开发、运行测试或打包时改为安装 `requirements-dev.txt`（含 pytest、PyInstaller 和图标生成依赖）：

```bash
python -m pip install -r requirements-dev.txt
```

### 2. 配置

复制 `network_config.ini.example` 并重命名为 `network_config.ini`，按注释填写：

源码运行时读取项目根目录中的配置；打包后读取 EXE 同目录中的配置，不受快捷方式工作目录影响。配置副本也会被 Git 忽略，模板仍可提交。

```ini
WIFI_ADAPTER_NAME=WLAN
ETHERNET_ADAPTER_NAME=以太网
WIFI_SSID=your_wifi_ssid
ETHERNET_PROGRAM_PATH=
```

切换到 WiFi 时使用 Windows 中已保存的 `WIFI_SSID` 配置，因此请先在 Windows 中手动连接一次该 WiFi 并保存密码。支持 WPA2、WPA3 和企业认证等 Windows 能保存的网络类型。旧配置中的 `WIFI_PASSWORD` 已不再使用，启动时会提示删除这行明文密码。

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

每次构建输出到独立的 `dist/folder-时间-标识/` 或 `dist/onefile-时间-标识/` 目录。脚本不会关闭运行中的 WorkPal，也不会删除旧包或用户配置；构建失败后旧包仍可使用。新包仅附带 `network_config.ini.example`，私人配置需自行放到新 EXE 旁边。EXE 的文件版本取自 `workpal/__init__.py` 中的 `__version__`；不使用 UPX 压缩，以减少杀毒软件误报。

首次使用新版前请从托盘退出旧版，再运行新包。请在新包的托盘中重新启用自启动，以更新程序路径和取消旧任务的三天运行时限。

### 5. 开机自启动

可直接从托盘点击 `开机自动启动：已开启/已关闭` 切换状态。也可以手动执行脚本：

```powershell
# 启用（需管理员权限）
.\scripts\enable_autostart.ps1 -ExePath '本次构建目录\WorkPal.exe'

# 禁用
.\scripts\disable_autostart.ps1
```

托盘通过任务计划 COM 接口直接读写任务，不再启动 PowerShell。自启动任务不限制持续运行时间；设置成功后会重新检查任务状态、程序路径、参数和工作目录，失败时不会显示“已开启”。已启用的任务指向旧版本或文件不存在时，菜单显示“需更新（点击修复）”；点击即可将任务更新为当前程序。

## 项目结构

```
WorkPal/
├── main.py                      # 入口文件
├── requirements.txt             # 运行依赖
├── requirements-dev.txt         # 测试、打包与图标生成依赖
├── network_config.ini.example   # 配置模板
├── WorkPal.spec                 # PyInstaller 文件夹模式打包配置
├── WorkPal_onefile.spec         # PyInstaller 单文件模式打包配置
├── workpal/                     # 核心包（__init__.py 中的 __version__ 为唯一版本号）
│   ├── config.py                # 配置加载
│   ├── system.py                # 系统工具函数
│   ├── tray.py                  # 系统托盘 UI
│   ├── features/
│   │   ├── autostart.py         # Windows 任务计划自启动（COM 接口）
│   │   ├── network.py           # 网络切换逻辑（wmi + psutil）
│   │   ├── wlan.py              # Native WiFi API 只读查询 WLAN 状态和已保存配置
│   │   ├── keep_alive.py        # 保持在线功能
│   │   ├── vpn_proxy.py         # 代理守护及 FortiClient 状态检查
│   │   ├── adapter_status.py    # 不依赖 WMI 的只读网卡检测
│   │   ├── session_events.py    # Windows 唤醒/解锁事件
│   │   ├── proxy_settings.py    # LAN 代理和持久化恢复备份
│   │   ├── single_instance.py   # 同一用户会话单实例
│   │   └── network_guard.py     # 网络变更互斥锁
├── scripts/                     # 工具脚本
│   ├── gen_icons.py             # 图标生成（Fluent UI Icons，MIT，需联网下载）
│   ├── build_package.ps1        # 两种打包模式共用的构建实现
│   ├── build_exe.bat/.ps1       # 文件夹模式打包
│   ├── build_onefile.bat/.ps1   # 单文件模式打包
│   ├── version_resource.py      # 生成 EXE 版本信息
│   ├── enable_autostart.ps1     # 启用开机自启
│   └── disable_autostart.ps1    # 禁用开机自启
├── assets/                      # 生成的图标（不提交 git）
└── tests/                       # 单元测试（系统调用全部使用替身）
```

## 图标说明

图标在首次运行构建脚本时自动生成（`scripts/gen_icons.py`），无需手动准备。直接运行源码时，图标缺失或损坏会自动使用内置备用图标，无需先打包或联网下载。
图标来源：[Fluent UI System Icons](https://github.com/microsoft/fluentui-system-icons)（Microsoft，MIT 协议），每次打包时自动从网络下载最新版本。

| 颜色/图案 | 含义 |
|-----------|------|
| 深灰 WiFi-off 图标 | 默认/空闲 |
| 蓝色 WiFi 图标 | 当前使用 WiFi |
| 绿色 插头图标 | 当前使用有线网络 |
| 橙色 同步箭头 | 正在切换网络 |
| 紫色 心跳波形 | 保持在线激活中 |

## 运行测试

需要先安装 `requirements-dev.txt`：

```bash
python -m pytest tests/ -v
```

## 注意事项

- 切换网络适配器需要 **管理员权限**，请以管理员身份运行
- WiFi 状态通过 Native WiFi API 读取，连接使用 `netsh wlan connect`，均需要 WLAN AutoConfig 服务运行
- 切到 WiFi 时先启用 WiFi 网卡并确认存在已保存配置，再禁用有线网卡；失败后恢复原网卡状态与原 WiFi 连接，无法完成恢复时会明确提示。切换或恢复期间不能退出程序。
- WorkPal 不新增、修改或删除任何 WiFi 配置，也不读取已保存的密码。
- 单文件打包模式（onefile）首次启动较慢，因需解压临时文件

## License

Apache 2.0
