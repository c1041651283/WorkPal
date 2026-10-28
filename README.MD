# WorkPal 工作助手

Windows 系统托盘工具，专为需要在 WiFi 和有线网络间频繁切换的办公环境设计，同时提供防止 Teams / 钉钉等应用显示离线的保持在线功能。

## 功能

- **一键网络切换**：点菜单中的网络卡片即可切换，卡片写明当前网络和切换方向，自动处理适配器启用/禁用和连接等待；当前网络无法识别时可直接选择切到 WiFi 或有线。代理守护运行时会先切回脚本代理（同时暂停守护）再切换。WiFi 使用 Windows 已保存的配置，WorkPal 不保存 WiFi 密码
- **保持在线**：通过 Windows API 阻止系统息屏/睡眠，并在检测到用户真实空闲超过 3 分钟时，通过 `SendInput(F15)` 可靠重置系统空闲计时器，防止 Teams 等 IM 软件将状态切换为离线；程序退出后系统自动恢复正常电源策略
- **系统托盘常驻**：左键或右键点击托盘图标弹出菜单面板（圆角、阴影，浅色/深色跟随 Windows）；操作结果以右下角通知卡片显示（淡入淡出），同一件事原地更新；菜单面板打开时通知暂时隐藏，关闭面板后继续显示，不会遮挡面板。托盘图标每 5 秒自动刷新，在 WorkPal 之外拔网线、切网络也会更新；鼠标悬停显示当前网络、保持在线和代理守护状态。Windows 11 上首次运行时图标自动显示在任务栏上，不收进隐藏区（之后自己拖回隐藏区会被保留）
- **开机自启动**：可从托盘启用/禁用 Windows 任务计划自启动
- **运行保护**：同一用户会话只运行一份 WorkPal；网络切换失败时尝试恢复原连接，并报告恢复结果
- **代理守护**：手动开启定时检查或执行单次修复，默认每 60 秒检查；支持公司有线和 FortiClient，在已确认公司网络可用时恢复固定代理

## 代理守护

每次启动 WorkPal 时，自动开启公司脚本代理、关闭手动代理，守护保持未开启。成功时不弹通知，只在失败时提示。

点击 WorkPal 托盘图标打开菜单面板。右上方的卡片显示守护状态和最近检查时间，下面是 `代理守护` 开关和相关操作：

- **切回脚本代理**：开启脚本代理、关闭手动代理，随时切回启动时的状态。如果守护正在运行，会先暂停，避免它马上切回手动代理。此按钮不启动或重启 iNetSec、不检查检疫结果。
- **代理守护开关（打开）**：开启定时守护，立即检查一次，随后默认每 60 秒检查（另加查询耗时）。公司有线网卡已连接且公司代理可达，或 VPN 有有效 IP 且公司代理可达时，恢复固定代理 `proxy.ricoh.co.jp:8080` 并关闭系统 PAC、自动检测。
- **立即检查并修复**：不需要先开启守护。检查后即结束；如果定时守护已经开启，则唤醒现有检查线程，不重复启动。无法确认公司网络时保持原样。
- **检查间隔**：在面板 `设置` 中选择 1、2、5 分钟，保存在用户设置中；从下一次检查完成后采用新间隔。也可用 `PROXY_CHECK_INTERVAL` 配置 30–3600 秒。
- **代理守护开关（关闭）**：暂停守护并保留当前代理，不还原旧脚本。退出 WorkPal 也保持当前代理；重新启动 WorkPal 后仍需手动开启守护。

代理被外部程序改回脚本后，守护会在下一次确认公司网络可用的检查中修复；配置正确时不会重复写入。修改代理的例外列表、PAC 地址仍会保留。需要自己调整代理时请先暂停守护。检查之间仍可能有短暂访问失败，可点击“立即检查并修复”。

在公司：启动 WorkPal 后按原来的方式完成检疫，看到 iNetSec 绿色 OK 后，自行打开 **代理守护** 开关。WorkPal 没有检疫等待、通过确认或自动开启守护的流程；从 WiFi 切到有线也不会开启守护。需要重新使用脚本时，点击“切回脚本代理”即可。

启动及按钮使用的脚本地址由 `OFFICE_PAC_URL` 指定，默认 `http://proxy.psh.com.cn/proxy-psh1.pac`。原固定代理地址和例外列表保留。暂停和退出保留当前代理；**下次启动会再次切到脚本代理**。

### 在家使用 FortiClient

1. 连接家庭网络。在菜单面板中点击 `在家连接公司`。
2. 用户主动点击该入口后，如果公司网络尚不可用，WorkPal 临时关闭系统代理，再打开已安装的 FortiClient；即使网卡状态暂时未知，也允许用户准备重新登录。公司网络已经可用时不关闭代理、不重连。
3. 在 FortiClient 中自行登录、连接和输入验证码；WorkPal 不保存或填写凭据。
4. 连续两次确认 VPN 有有效 IP、公司代理 TCP 端口可达后开启固定代理。可以点击“立即检查并修复”主动检查；该操作确认就绪后即可修复，无需等待两个定时间隔。
5. 用 FortiClient 自己的断开按钮断开。连续三次确认断线后关闭系统代理；按默认间隔可能需要约 3 分钟。需要马上重新连接时，直接点击“在家连接公司”；守护仍在运行也可以使用，不用暂停或恢复旧代理。

公司网络可用时不重连，也不会临时关闭代理。在公司有线网络可用时，不要求 VPN 连接。自动检查遇到网卡读取失败会保持当前代理，不把未知状态当作断线。在家模式下，如果网卡仍显示连接、但公司代理连续三次不可达，会临时关闭系统代理，并明确显示“公司代理不可达”；这不等同于确认 VPN 断开。恢复可达后继续自动启用固定代理。

### 锁屏、休眠和唤醒

守护开启时，Windows 解锁或唤醒事件会立即触发复查，并最多追加两次间隔 5 秒的检查，之后恢复用户选择的 1/2/5 分钟间隔。未开启守护时不会因为唤醒而自动开启。相近的重复唤醒事件会合并。

菜单显示最近检查时间，以及“VPN 已断开”“公司代理不可达”或“无法确认 VPN 状态”。网卡读取使用 Windows IP Helper；菜单刷新也不再调用 WMI/netsh，避免旧查询阻塞状态更新。

若 FortiClient 要求重新认证，点击“在家连接公司”，再手动登录或输入验证码即可。WorkPal 不替用户登录、不改变 VPN 超时策略，也不阻止 Windows 正常锁屏或休眠。

代理守护只操作**当前用户 Windows LAN 代理**，不修改 WinHTTP、VPN 专用代理、FortiClient 配置/服务、网卡、DNS 或路由。守护运行期间点击网络切换，会先切回脚本代理并暂停守护，再切换网卡。保存备份期间收到暂停请求会取消本次代理写入；临时关闭代理后、尚未启动 FortiClient 时收到暂停请求，或 GUI 启动失败时，会撤销本次临时关闭。撤销失败会报告错误并保留恢复备份。

备份位于 `%LOCALAPPDATA%\WorkPal\vpn_proxy_session.json`；变更及错误记录在同目录 `app.log` 中，可从菜单面板底部的 `日志` 打开。写入备份失败时不修改系统代理。现有 v1.1.0 备份可以继续使用；启动时设置脚本代理，但不自动开启守护。操作失败会通知，不阻止托盘启动。

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

配置文件固定放在 `%LOCALAPPDATA%\WorkPal\network_config.ini`，源码运行和每次打包后的 EXE 都读取这一份，重新打包后无需重填。

- **首次填写**：启动 WorkPal 后，在菜单面板中打开 `设置 → 编辑配置文件`。如果还没有配置，会按模板生成一份并用记事本打开；每次在记事本中保存都会自动重新加载，无需关闭记事本或重启。代理守护正在运行时，下一次检查即使用新的代理地址。
- **从旧版本升级**：首次启动时，如果用户目录中还没有配置，会自动把 EXE 旁边（源码运行时为项目根目录）原有的 `network_config.ini` 复制过来，原文件保留。之后程序只读用户目录中的配置；旧位置的文件与之不一致时会在日志中提示，可以删除。
- 用户目录不在项目中，不会被提交到 Git；项目根目录下的 `network_config.ini` 仍被 Git 忽略。

配置内容示例：

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

每次构建输出到独立的 `dist/folder-时间-标识/` 或 `dist/onefile-时间-标识/` 目录。脚本不会关闭运行中的 WorkPal，也不会删除旧包或用户配置；构建失败后旧包仍可使用。新包仅附带 `network_config.ini.example`；配置保存在用户目录，新 EXE 直接沿用，不需要复制。EXE 的文件版本取自 `workpal/__init__.py` 中的 `__version__`；不使用 UPX 压缩，以减少杀毒软件误报。

首次使用新版前请从托盘退出旧版，再运行新包。请在新包的托盘中重新启用自启动，以更新程序路径和取消旧任务的三天运行时限。

### 5. 开机自启动

在菜单面板 `设置` 中用 `开机自动启动` 开关切换。

托盘通过任务计划 COM 接口直接读写任务，不再启动 PowerShell。自启动任务不限制持续运行时间；设置成功后会重新检查任务状态、程序路径、参数和工作目录，失败时不会显示“已开启”。已启用的任务指向旧版本或文件不存在时，设置页显示“需更新”和“更新”按钮；点击即可将任务更新为当前程序。

## 项目结构

```
WorkPal/
├── main.py                      # 入口文件
├── requirements.txt             # 运行依赖
├── requirements-dev.txt         # 测试与打包依赖
├── network_config.ini.example   # 配置模板（实际配置在 %LOCALAPPDATA%\WorkPal\）
├── WorkPal.spec                 # PyInstaller 文件夹模式打包配置
├── WorkPal_onefile.spec         # PyInstaller 单文件模式打包配置
├── workpal/                     # 核心包（__init__.py 中的 __version__ 为唯一版本号）
│   ├── config.py                # 配置加载
│   ├── system.py                # 系统工具函数
│   ├── tray.py                  # 托盘业务动作与状态（与界面无关）
│   ├── ui/                      # Qt 界面（PySide6）
│   │   ├── app.py               # 托盘图标、事件循环、跨线程信号
│   │   ├── panel.py             # 菜单面板与设置页
│   │   ├── toast.py             # 右下角通知卡片
│   │   ├── widgets.py           # 拨动开关、卡片等控件
│   │   ├── icons.py             # 图标着色与托盘图标合成
│   │   ├── theme.py             # 浅色/深色配色
│   │   └── glyphs.py            # 内嵌的 Fluent 矢量图标（生成文件）
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
│   │   ├── tray_promotion.py    # Windows 11 托盘图标直接显示
│   │   └── network_lock.py      # 网络变更互斥锁
├── scripts/                     # 工具脚本
│   ├── gen_icons.py             # 生成 EXE 文件图标（与托盘图标相同，打包时自动运行）
│   ├── gen_glyphs.py            # 重新生成 workpal/ui/glyphs.py（仅更换图标时运行）
│   ├── build_package.ps1        # 两种打包模式共用的构建实现
│   ├── build_exe.bat/.ps1       # 文件夹模式打包
│   ├── build_onefile.bat/.ps1   # 单文件模式打包
│   ├── qt_trim.py               # 打包时去掉用不到的 Qt 文件
│   └── version_resource.py      # 生成 EXE 版本信息
├── assets/                      # 生成的 EXE 文件图标（不提交 git）
└── tests/                       # 单元测试（系统调用全部使用替身）
```

## 图标说明

界面和托盘用到的图标来自 [Fluent UI System Icons](https://github.com/microsoft/fluentui-system-icons)（Microsoft，MIT 协议），已内嵌在 `workpal/ui/glyphs.py` 中，运行时直接绘制，源码运行和打包都无需联网。需要更换图标时运行 `python scripts/gen_glyphs.py` 重新生成。EXE 文件本身的图标由构建脚本调用 `scripts/gen_icons.py` 用同样的托盘图标绘制，也不需联网。

托盘图标是圆角色块加白色图标：

| 颜色/图案 | 含义 |
|-----------|------|
| 灰色 WiFi-off | 当前网络无法识别 |
| 蓝色 WiFi | 当前使用 WiFi |
| 绿色 插头 | 当前使用有线网络 |
| 橙色 同步箭头 | 正在切换网络 |
| 右下角紫色圆点 | 保持在线已开启（叠加在网络图标上） |

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
