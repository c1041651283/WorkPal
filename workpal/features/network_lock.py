"""串行化会影响当前网络的操作；代理守护持有期间不切换物理网卡。"""

import threading

network_change_lock = threading.Lock()
