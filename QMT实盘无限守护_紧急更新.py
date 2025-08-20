"""实盘无限守护 - QMT和彩虹客户端自动化管理工具
作者： ∞MeowTech @萌新小强 @无限进化 @萌新小王 @大蒜
版本：3.0
"""

# ====================================================================
# USER CONFIG - 用户配置区域（集中管理所有可调参数）
# ====================================================================
class Constants:
    """系统常量配置 - 集中管理可调参数"""
    
    # 进程管理
    GRACEFUL_SHUTDOWN_TIMEOUT = 10  # 优雅关闭超时（秒）
    FORCE_KILL_TIMEOUT = 5         # 强制终止超时（秒）
    PROCESS_START_TIMEOUT = 30     # 进程启动超时（秒）
    
    # 网络测试
    NETWORK_TEST_TIMEOUT = 0.1     # 网络延迟测试超时（秒）
    NETWORK_TEST_SAMPLES = 5       # 延迟测试样本数
    MAX_ACCEPTABLE_LATENCY = 1000  # 最大可接受延迟（毫秒）
    
    # 监控配置
    DEFAULT_MONITOR_INTERVAL = 60      # 监控间隔（秒）
    DEFAULT_NOTIFICATION_INTERVAL = 300 # 通知间隔（秒）
    MEMORY_WARNING_THRESHOLD = 1000    # 内存警告阈值（MB）
    CPU_WARNING_THRESHOLD = 80         # CPU警告阈值（%）
    
    # UI配置
    UI_UPDATE_INTERVAL = 1000      # UI更新间隔（毫秒）
    ASYNC_OPERATION_TIMEOUT = 60   # 异步操作超时（秒）
    STATUS_MESSAGE_MAX_LENGTH = 100 # 状态消息最大长度
    
    # 文件路径
    CONFIG_FILENAME = "guardian_config.json"
    LOG_DIR_NAME = "logs"
    CACHE_DIR_NAME = "cache"
    
    # 进程名称
    QMT_PROCESS_NAME = "XtMiniQmt.exe"
    QMT_CLIENT_PROCESS_NAME = "XtItClient.exe"
    
    # 时间格式
    TIME_FORMAT = "%H:%M:%S"
    DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"
    
    # 飞书通知
    FEISHU_TIMEOUT = 10           # 通知超时（秒）
    FEISHU_RETRY_COUNT = 3        # 重试次数
    FEISHU_RETRY_DELAY = 2        # 重试延迟（秒）

# ====================================================================
# 内存管理和异步操作辅助类
# ====================================================================
class MemoryManager:
    """内存管理器 - 定期清理大对象，防止内存泄漏"""
    
    def __init__(self):
        self._large_objects = weakref.WeakSet()  # 使用弱引用避免循环引用
        self._last_cleanup = time.time()
        self._cleanup_interval = 300  # 5分钟清理一次
        
    def register_large_object(self, obj):
        """注册大对象用于监控"""
        self._large_objects.add(obj)
        
    def cleanup_if_needed(self):
        """根据需要执行内存清理"""
        current_time = time.time()
        if current_time - self._last_cleanup > self._cleanup_interval:
            self.force_cleanup()
            
    def force_cleanup(self):
        """强制执行内存清理"""
        # 清理大对象缓存
        for obj in list(self._large_objects):
            if hasattr(obj, 'clear_cache'):
                obj.clear_cache()
                
        # 执行垃圾回收
        collected = gc.collect()
        self._last_cleanup = time.time()
        
        if collected > 0:
            log(f"内存清理完成，回收了 {collected} 个对象")
            
    def get_memory_usage(self):
        """获取当前内存使用情况"""
        process = psutil.Process()
        memory_info = process.memory_info()
        return {
            'rss_mb': memory_info.rss / 1024 / 1024,  # 物理内存
            'vms_mb': memory_info.vms / 1024 / 1024,  # 虚拟内存
            'percent': process.memory_percent()        # 内存使用百分比
        }

class AsyncOperationManager:
    """异步操作管理器 - 防止长时间操作阻塞UI"""
    
    def __init__(self, max_workers=4):
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self._running_operations = {}
        
    def run_async(self, operation_id, func, *args, **kwargs):
        """异步执行操作
        
        Args:
            operation_id: 操作唯一标识
            func: 要执行的函数
            *args, **kwargs: 函数参数
            
        Returns:
            Future对象
        """
        if operation_id in self._running_operations:
            log(f"操作 {operation_id} 已在运行中，跳过重复执行")
            return self._running_operations[operation_id]
            
        future = self.executor.submit(func, *args, **kwargs)
        self._running_operations[operation_id] = future
        
        # 操作完成后自动清理
        def cleanup_operation(fut):
            self._running_operations.pop(operation_id, None)
            
        future.add_done_callback(cleanup_operation)
        return future
        
    def is_operation_running(self, operation_id):
        """检查操作是否正在运行"""
        future = self._running_operations.get(operation_id)
        return future is not None and not future.done()
        
    def cancel_operation(self, operation_id):
        """取消正在运行的操作"""
        future = self._running_operations.get(operation_id)
        if future and not future.done():
            future.cancel()
            return True
        return False
        
    def shutdown(self):
        """关闭异步操作管理器"""
        self.executor.shutdown(wait=True)

def async_operation(operation_id=None):
    """异步操作装饰器 - 自动异步执行函数"""
    def decorator(func):
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            if hasattr(self, 'async_manager'):
                op_id = operation_id or f"{func.__name__}_{id(self)}"
                return self.async_manager.run_async(op_id, func, self, *args, **kwargs)
            else:
                return func(self, *args, **kwargs)
        return wrapper
    return decorator

# 标准库导入
import os, sys, json, time, threading, subprocess, shutil, socket, gc
import xml.etree.ElementTree as ET
from datetime import datetime
from functools import wraps
import weakref, statistics, winreg

# 第三方库导入
import psutil, requests, schedule
from concurrent.futures import ThreadPoolExecutor

# 设置控制台编码为UTF-8，解决中文乱码问题
try:
    # Windows系统设置控制台编码
    if sys.platform.startswith('win'):
        import io
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
        # 设置控制台代码页为UTF-8
        os.system('chcp 65001 >nul 2>&1')
except Exception as e:
    pass  # 如果设置失败，继续运行
try:
    from PyQt5.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
        QLineEdit, QPushButton, QCheckBox, QLabel, QGroupBox, QTabWidget, QMessageBox
    )
    from PyQt5.QtCore import Qt, QTimer, pyqtSignal as Signal
    from PyQt5.QtGui import QIcon, QFont
except ImportError as e:
    print(f"PyQt5导入失败: {e}")
    print("请安装PyQt5: pip install PyQt5")
    
    # PyQt5模拟类（避免导入错误）
    class MockQt:
        AlignLeft = 0x0001
        AlignCenter = 0x0004
    
    class MockSignal:
        def connect(self, func): pass
        def emit(self, *args): pass
    
    def Signal(*args): return MockSignal()
    
    # 批量创建模拟类
    mock_classes = ['QApplication', 'QMainWindow', 'QWidget', 'QVBoxLayout', 'QHBoxLayout', 
                   'QFormLayout', 'QLineEdit', 'QPushButton', 'QCheckBox', 'QLabel', 
                   'QGroupBox', 'QTabWidget', 'QMessageBox', 'QTimer', 'QIcon', 'QFont']
    
    for cls_name in mock_classes:
        globals()[cls_name] = type(cls_name, (), {
            '__init__': lambda self, *args, **kwargs: None,
            '__getattr__': lambda self, name: lambda *args, **kwargs: None
        })
    
    Qt = MockQt()
    QApplication.exec = lambda self: 0

# ====================================================================
# 配置管理模块
# ====================================================================
class ConfigManager:
    """配置管理器 - 统一管理配置参数，支持JSON文件持久化"""
    
    DEFAULT_CONFIG = {
        # QMT相关配置
        "qmt_dir": r"D:\DFZQxtqmt_win64",
        "qmt_run_time": "09:28:00",
        "qmt_only_vip": True,
        "enable_qmt_shutdown": False,
        "qmt_shutdown_time": "",
        
        # 彩虹客户端配置
        "rainbow_exe_path": r"D:\quantclass\quantclass.exe",
        "rainbow_restart_time": "09:35:00",
        "enable_rainbow_shutdown": False,
        "rainbow_shutdown_time": "",
        
        # 数据清理配置
        "delete_base_path": r"E:\DATA_Center\real_trading\rocket\data\系统缓存",
        "delete_folders": "早盘数据,早盘择时",
        
        # 系统配置
        "enable_startup": True,
        "enable_system_shutdown": False,
        "system_shutdown_time": "",
        "schedule_running": False,  # 定时任务运行状态
        
        # 实时监控配置
        "monitor_interval": 10,  # 监控间隔（秒）
        "notification_interval": 300,  # 通知间隔（秒，5分钟）
        "notification_start_time": "09:00:00",  # 通知时间段开始
        "notification_end_time": "15:30:00",   # 通知时间段结束
        
        # 飞书通知配置
        "feishu_webhook_url": "",  # 飞书机器人Webhook URL
        "enable_feishu_notification": True,
        "feishu_at_all": True  # 是否@所有人，默认开启
    }
    
    def __init__(self):
        """初始化配置管理器"""
        self.config_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs", "guardian_config.json")
        os.makedirs(os.path.dirname(self.config_file), exist_ok=True)
        self.config = self._load_config()
        log(f"配置管理器已初始化，配置文件: {self.config_file}")
    
    def _load_config(self):
        """加载配置文件，不存在则使用默认配置"""
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    loaded_config = json.load(f)
                config = self.DEFAULT_CONFIG.copy()
                config.update(loaded_config)
                log(f"成功加载配置文件: {self.config_file}")
                return config
            except Exception as e:
                log(f"加载配置文件失败: {e}，使用默认配置")
                return self.DEFAULT_CONFIG.copy()
        else:
            log("配置文件不存在，使用默认配置")
            return self.DEFAULT_CONFIG.copy()
    
    def save_config(self):
        """保存配置到JSON文件"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, ensure_ascii=False, indent=4)
            log(f"配置已保存到: {self.config_file}")
            return True
        except Exception as e:
            log(f"保存配置文件失败: {e}")
            return False
    
    def get(self, key, default=None):
        """获取配置值"""
        return self.config.get(key, default)
    
    def set(self, key, value):
        """设置配置值"""
        self.config[key] = value
        log(f"配置已更新: {key} = {value}")
    
    def update(self, new_config):
        """批量更新配置"""
        self.config.update(new_config)
        log(f"批量更新配置: {len(new_config)} 项")

# ====================================================================
# 工具函数模块
# ====================================================================
def log(message):
    """带时间戳的日志记录"""
    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    try:
        if isinstance(message, bytes):
            message = message.decode('utf-8', errors='ignore')
        print(f"[{timestamp}] {message}", flush=True)
    except Exception:
        try:
            safe_message = str(message).encode('ascii', errors='ignore').decode('ascii')
            print(f"[{timestamp}] {safe_message}", flush=True)
        except:
            print(f"[{timestamp}] [LOG_ERROR]", flush=True)

def is_valid_time(time_str):
    """验证时间格式，支持空值"""
    if not time_str or time_str.strip() == "":
        return True
    try:
        time.strptime(time_str, '%H:%M:%S')
        return True
    except ValueError:
        return False

class Worker(threading.Thread):
    """通用工作线程 - 执行耗时操作"""
    def __init__(self, func, *args, **kwargs):
        super().__init__(daemon=True)
        self.func = func
        self.args = args
        self.kwargs = kwargs

    def run(self):
        try:
            self.func(*self.args, **self.kwargs)
        except Exception as e:
            log(f"工作线程执行失败: {e}")

# ====================================================================
# 网络测试模块
# ====================================================================
class NetworkTester:
    """网络延迟测试工具 - 行情源优选"""
    
    @staticmethod
    def measure_latency(ip, port, timeout=0.1):
        """测量网络延迟（毫秒）"""
        try:
            start = time.time()
            with socket.create_connection((ip, int(port)), timeout=timeout):
                end = time.time()
                return (end - start) * 1000
        except Exception:
            return float('inf')
    
    @staticmethod
    def median_latency(ip, port, count=10):
        """计算中位数延迟"""
        latencies = []
        for _ in range(count):
            delay = NetworkTester.measure_latency(ip, port)
            if delay != float('inf'):
                latencies.append(delay)
            time.sleep(0.05)
        return statistics.median(latencies) if latencies else float('inf')

# ====================================================================
# 飞书通知模块
# ====================================================================
class FeishuNotifier:
    """飞书通知器 - 发送消息到群聊"""
    
    def __init__(self, webhook_url, at_all=False):
        self.webhook_url = webhook_url
        self.at_all = at_all
        self.last_notification_time = {}
        
    def send_message(self, title, content, msg_type="info"):
        """发送消息到飞书"""
        if not self.webhook_url:
            log("飞书Webhook URL未配置，跳过通知")
            return False
            
        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            color_map = {"info": "blue", "warning": "orange", "error": "red", "success": "green"}
            color = color_map.get(msg_type, "blue")
            message = {
                "msg_type": "interactive",
                "card": {
                    "config": {
                        "wide_screen_mode": True
                    },
                    "header": {
                        "title": {
                            "tag": "plain_text",
                            "content": f"🤖 {title}"
                        },
                        "template": color
                    },
                    "elements": [
                        {
                            "tag": "div",
                            "text": {
                                "tag": "plain_text",
                                "content": content
                            }
                        },
                        {
                            "tag": "div",
                            "text": {
                                "tag": "plain_text",
                                "content": f"⏰ 时间: {timestamp}"
                            }
                        }
                    ]
                }
            }
            
            if self.at_all:
                message["card"]["elements"].append({
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": "<at user_id=\"all\">所有人</at>"
                    }
                })
            response = requests.post(
                self.webhook_url,
                json=message,
                timeout=10
            )
            
            if response.status_code == 200:
                result = response.json()
                if result.get("code") == 0:
                    log(f"飞书通知发送成功: {title}")
                    return True
                else:
                    log(f"飞书通知发送失败: {result.get('msg', '未知错误')}")
                    return False
            else:
                log(f"飞书通知发送失败，HTTP状态码: {response.status_code}")
                return False
                
        except Exception as e:
            log(f"发送飞书通知异常: {str(e)}")
            return False
    
    def should_send_notification(self, notification_key, interval_seconds=300):
        """检查是否应该发送通知（防频繁通知）"""
        current_time = time.time()
        last_time = self.last_notification_time.get(notification_key, 0)
        
        if current_time - last_time >= interval_seconds:
            self.last_notification_time[notification_key] = current_time
            return True
        return False
    
    def is_notification_time(self, start_time="09:00:00", end_time="15:30:00"):
        """检查当前是否在通知时间段内"""
        try:
            current_time = datetime.now().time()
            start = datetime.strptime(start_time, "%H:%M:%S").time()
            end = datetime.strptime(end_time, "%H:%M:%S").time()
            return start <= current_time <= end
        except:
            return True  # 如果时间格式错误，默认允许通知

# ====================================================================
# 行情源优选模块（保持原有逻辑不变）
# ====================================================================
class ServerOptimizer:
    """行情源服务器优选器 - 自动选择最佳行情和交易服务器"""
    
    def __init__(self, qmt_dir_path, only_vip=True):
        self.qmt_dir_path = qmt_dir_path
        self.only_vip = only_vip
        self.network_tester = NetworkTester()
    
    def find_best_servers(self):
        """查找最佳行情和交易服务器"""
        log(f"开始查找最佳服务器，QMT路径: {self.qmt_dir_path}")
        
        # 终止QMT进程
        self._terminate_qmt_processes()
        
        # 解析配置文件
        config_path = fr'{self.qmt_dir_path}\userdata_mini\users\xtquoterconfig.xml'
        if not os.path.exists(config_path):
            log(f"错误: 配置文件不存在 {config_path}")
            return None, None, None, None, None
        
        try:
            tree = ET.parse(config_path)
            quoter_server_map = tree.find('QuoterServers')
            quoter_server_list = quoter_server_map.findall('QuoterServer')
            
            # 解析服务器信息
            qs_infos = self._parse_server_info(quoter_server_list)
            
            # 测试服务器延迟
            results = self._test_server_latency(qs_infos)
            
            # 选择最佳服务器
            best_hq, best_jy = self._select_best_servers(results)
            
            return best_hq, best_jy, tree, quoter_server_map, config_path
        
        except Exception as e:
            log(f"解析配置文件出错: {str(e)}")
            return None, None, None, None, None
    
    def _terminate_qmt_processes(self):
        """终止QMT进程"""
        for proc in psutil.process_iter(['pid', 'name', 'exe']):
            try:
                if proc.info['name'] == 'XtMiniQmt.exe':
                    exe_path = (proc.info['exe'] or '').lower()
                    if self.qmt_dir_path.lower() in exe_path:
                        log(f"终止进程: PID={proc.pid}, Path={exe_path}")
                        proc.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    
    def _parse_server_info(self, quoter_server_list):
        """解析服务器信息"""
        qs_infos = {}
        for server in quoter_server_list:
            quoter_type = server.attrib['quotertype']
            if self.only_vip and quoter_type == '0' and 'VIP' not in server.attrib['servername']:
                continue
            info = {
                'ip': server.attrib['address'],
                'port': int(server.attrib['port']),
                'username': server.attrib['username'],
                'pwd': server.attrib['password'],
                'type': quoter_type,
                'servername': server.attrib['servername']
            }
            qs_infos[info['ip']] = info
        return qs_infos
    
    def _test_server_latency(self, qs_infos):
        """测试服务器延迟"""
        results = []
        log(f"开始测试 {len(qs_infos)} 个服务器...")
        
        for info in qs_infos.values():
            median_value = self.network_tester.median_latency(info['ip'], info['port'])
            info['median_value'] = median_value
            results.append(info)
            
            server_type = "行情" if info['type'] == '0' else "交易"
            log(f'{server_type}-{info["servername"]} {info["ip"]} 延迟: {median_value:.2f} ms')
        
        return results
    
    def _select_best_servers(self, results):
        """选择最佳服务器"""
        hq_results = [r for r in results if r['type'] == '0']
        jy_results = [r for r in results if r['type'] == '1']
        
        best_hq = min(hq_results, key=lambda x: x['median_value'], default=None)
        best_jy = min(jy_results, key=lambda x: x['median_value'], default=None)
        
        log("=" * 80)
        
        if best_hq:
            log(f"最佳行情服务器: {best_hq['servername']} IP={best_hq['ip']} 延迟: {best_hq['median_value']:.2f} ms")
        else:
            log("未找到有效的行情服务器")
        
        if best_jy:
            log(f"最佳交易服务器: {best_jy['servername']} IP={best_jy['ip']} 延迟: {best_jy['median_value']:.2f} ms")
        else:
            log("未找到有效的交易服务器")
        
        return best_hq, best_jy
    
    def update_qmt_config(self, best_hq, best_jy, tree, quoter_server_map, config_path):
        """更新QMT配置文件"""
        if not best_hq or not best_jy or tree is None or quoter_server_map is None:
            log("更新配置失败: 缺少必要参数")
            return False
        
        try:
            current_stock = quoter_server_map.get('current_stock')
            current_trade_stock = quoter_server_map.get('current_trade_stock')
            
            if not current_stock or not current_trade_stock:
                log("更新配置失败: 找不到当前服务器配置")
                return False
            
            current_stock_list = current_stock.split('_')
            current_stock_list[-2] = best_hq['ip']
            current_stock_list[-1] = str(best_hq['port'])
            
            current_trade_stock_list = current_trade_stock.split('_')
            current_trade_stock_list[-2] = best_jy['ip']
            current_trade_stock_list[-1] = str(best_jy['port'])
            
            quoter_server_map.set('current_stock', '_'.join(current_stock_list))
            quoter_server_map.set('current_trade_stock', '_'.join(current_trade_stock_list))
            
            tree.write(config_path, encoding='utf-8', xml_declaration=True)
            log(f"配置已更新并保存到 {config_path}")
            return True
        except Exception as e:
            log(f"更新配置文件出错: {str(e)}")
            return False

# ====================================================================
# 进程管理模块
# ====================================================================
class ProcessManager:
    """进程管理器 - 统一管理进程启动和终止"""

    @staticmethod
    def terminate_processes_by_name(process_name, target_path=None, graceful_timeout=10):
        """根据进程名终止进程 - 优雅关闭机制"""
        processes_to_kill = []

        for proc in psutil.process_iter(['pid', 'name', 'exe', 'status']):
            try:
                if proc.info['name'] == process_name:
                    if target_path is None or (proc.info['exe'] and target_path.lower() in proc.info['exe'].lower()):
                        processes_to_kill.append(proc)
                        log(f"发现目标进程: {process_name} (PID={proc.pid}, 状态={proc.info['status']})")
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        if not processes_to_kill:
            log(f"未发现运行中的 {process_name} 进程")
            return 0, 0

        success_count = 0
        failed_count = 0

        for proc in processes_to_kill:
            try:
                if not proc.is_running():
                    log(f"进程 {proc.pid} 已经不存在，跳过")
                    continue

                log(f"开始优雅关闭进程: {process_name} (PID={proc.pid})")
                proc.terminate()

                try:
                    proc.wait(timeout=graceful_timeout)
                    log(f"✓ 进程 {proc.pid} 已优雅退出")
                    success_count += 1
                    continue
                except psutil.TimeoutExpired:
                    log(f"⚠ 进程 {proc.pid} 在 {graceful_timeout}s 内未响应优雅关闭，强制终止")

                if proc.is_running():
                    proc.kill()
                    try:
                        proc.wait(timeout=5)
                        log(f"✓ 进程 {proc.pid} 已强制终止")
                        success_count += 1
                    except psutil.TimeoutExpired:
                        log(f"✗ 进程 {proc.pid} 强制终止失败，可能成为僵尸进程")
                        failed_count += 1

            except psutil.NoSuchProcess:
                log(f"✓ 进程 {proc.pid} 已自然退出")
                success_count += 1
            except psutil.AccessDenied:
                log(f"✗ 权限不足，无法终止进程 {proc.pid}")
                failed_count += 1
            except Exception as e:
                log(f"✗ 终止进程 {proc.pid} 时发生异常: {e}")
                failed_count += 1

        # 第三步：僵尸进程检测和清理
        ProcessManager._cleanup_zombie_processes(process_name)

        log(f"进程终止完成: 成功 {success_count} 个，失败 {failed_count} 个")
        return success_count, failed_count

    @staticmethod
    def _cleanup_zombie_processes(process_name):
        """清理僵尸进程 - 检测并报告僵尸进程状态"""
        zombie_count = 0

        try:
            for proc in psutil.process_iter(['pid', 'name', 'status']):
                try:
                    if (proc.info['name'] == process_name and
                        proc.info['status'] == psutil.STATUS_ZOMBIE):
                        zombie_count += 1
                        log(f"⚠ 检测到僵尸进程: {process_name} (PID={proc.pid})")

                        # 尝试通过父进程清理僵尸进程
                        try:
                            parent = proc.parent()
                            if parent:
                                log(f"僵尸进程的父进程: PID={parent.pid}, 名称={parent.name()}")
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            pass

                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except Exception as e:
            log(f"僵尸进程检测时发生异常: {e}")

        if zombie_count > 0:
            log(f"⚠ 发现 {zombie_count} 个 {process_name} 僵尸进程，建议重启系统清理")
        else:
            log(f"✓ 未发现 {process_name} 僵尸进程")

    @staticmethod
    def get_process_status(process_name, target_path=None):
        """获取进程状态信息"""
        processes = []

        for proc in psutil.process_iter(['pid', 'name', 'exe', 'status', 'create_time', 'memory_info', 'cpu_percent']):
            try:
                if proc.info['name'] == process_name:
                    if target_path is None or (proc.info['exe'] and target_path.lower() in proc.info['exe'].lower()):
                        create_time = proc.info['create_time']
                        running_time = time.time() - create_time

                        process_info = {
                            'pid': proc.info['pid'],
                            'status': proc.info['status'],
                            'exe_path': proc.info['exe'],
                            'running_time_seconds': running_time,
                            'memory_mb': proc.info['memory_info'].rss / 1024 / 1024 if proc.info['memory_info'] else 0,
                            'cpu_percent': proc.info['cpu_percent'] or 0
                        }
                        processes.append(process_info)

            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        return {
            'process_name': process_name,
            'count': len(processes),
            'processes': processes,
            'is_running': len(processes) > 0
        }

    @staticmethod
    def start_process(exe_path, wait_for_start=True, start_timeout=30):
        """启动进程 - 增强版启动机制"""
        if not os.path.exists(exe_path):
            error_msg = f"可执行文件不存在: {exe_path}"
            log(f"✗ {error_msg}")
            return False, error_msg

        try:
            log(f"正在启动进程: {exe_path}")

            process = subprocess.Popen([exe_path])

            if not wait_for_start:
                log(f"✓ 进程已启动 (PID={process.pid})，未等待启动确认")
                return True, process.pid

            process_name = os.path.basename(exe_path)
            start_time = time.time()

            while time.time() - start_time < start_timeout:
                status = ProcessManager.get_process_status(process_name, os.path.dirname(exe_path))
                if status['is_running']:
                    running_process = status['processes'][0]
                    log(f"✓ 进程启动成功: {process_name} (PID={running_process['pid']})")
                    return True, running_process['pid']

                time.sleep(1)  # 每秒检查一次

            # 启动超时
            error_msg = f"进程启动超时 ({start_timeout}s): {process_name}"
            log(f"✗ {error_msg}")
            return False, error_msg

        except Exception as e:
            error_msg = f"启动进程时发生异常: {str(e)}"
            log(f"✗ {error_msg}")
            return False, error_msg

    @staticmethod
    def monitor_process_health(process_name, target_path=None):
        """监控进程健康状态 - 新增健康检查功能

        Args:
            process_name: 进程名称
            target_path: 目标路径过滤（可选）

        Returns:
            dict: 健康状态报告
        """
        status = ProcessManager.get_process_status(process_name, target_path)

        health_report = {
            'process_name': process_name,
            'is_healthy': True,
            'issues': [],
            'recommendations': [],
            'status': status
        }

        if not status['is_running']:
            health_report['is_healthy'] = False
            health_report['issues'].append("进程未运行")
            health_report['recommendations'].append("检查进程是否正常启动")
            return health_report

        # 检查多实例问题
        if status['count'] > 1:
            health_report['is_healthy'] = False
            health_report['issues'].append(f"检测到多个实例运行 ({status['count']} 个)")
            health_report['recommendations'].append("终止多余的进程实例")

        # 检查僵尸进程
        for proc_info in status['processes']:
            if proc_info['status'] == psutil.STATUS_ZOMBIE:
                health_report['is_healthy'] = False
                health_report['issues'].append(f"检测到僵尸进程 (PID={proc_info['pid']})")
                health_report['recommendations'].append("重启系统清理僵尸进程")

        # 检查内存使用
        for proc_info in status['processes']:
            if proc_info['memory_mb'] > 1000:  # 超过1GB内存
                health_report['issues'].append(f"内存使用较高: {proc_info['memory_mb']:.1f}MB (PID={proc_info['pid']})")
                health_report['recommendations'].append("监控内存使用情况，考虑重启进程")

        return health_report

# ====================================================================
# 实时监控模块
# ====================================================================
class MonitoringThread(threading.Thread):
    """实时监控线程 - 监控QMT进程和网络状态"""

    def __init__(self, config_manager, feishu_notifier, status_callback=None, server_update_callback=None):
        super().__init__(daemon=True)
        self.config_manager = config_manager
        self.feishu_notifier = feishu_notifier
        self.status_callback = status_callback
        self.server_update_callback = server_update_callback
        self.running = False
        self.last_status = {}
        self.server_optimizer = None

        self.last_qmt_status = False
        self.last_network_status = False

    def start_monitoring(self):
        """启动监控"""
        self.running = True
        self.start()
        log("实时监控已启动")

    def stop_monitoring(self):
        """停止监控"""
        self.running = False
        log("实时监控已停止")

    def run(self):
        """监控主循环"""
        while self.running:
            try:
                self._check_qmt_status()
                self._check_network_status()

                interval = self.config_manager.get('monitor_interval', 10)
                time.sleep(interval)

            except Exception as e:
                log(f"监控线程异常: {str(e)}")
                time.sleep(10)

    def _check_qmt_status(self):
        """检查QMT进程状态"""
        qmt_dir = self.config_manager.get('qmt_dir')
        if not qmt_dir:
            return

        qmt_running = False
        qmt_processes = []
        all_qmt_processes = []  # 记录所有XtMiniQmt.exe进程

        for proc in psutil.process_iter(['pid', 'name', 'exe']):
            try:
                if proc.info['name'] == 'XtMiniQmt.exe':
                    exe_path = proc.info['exe'] or ''
                    all_qmt_processes.append({
                        'pid': proc.info['pid'],
                        'exe_path': exe_path
                    })

                    # 路径匹配检查 - 支持多种匹配方式
                    exe_path_lower = exe_path.lower()
                    qmt_dir_lower = qmt_dir.lower()

                    # 方式1: 直接包含检查
                    path_match_1 = qmt_dir_lower in exe_path_lower

                    # 方式2: 标准化路径后检查
                    try:
                        exe_path_norm = os.path.normpath(exe_path_lower)
                        qmt_dir_norm = os.path.normpath(qmt_dir_lower)
                        path_match_2 = qmt_dir_norm in exe_path_norm
                    except:
                        path_match_2 = False

                    # 方式3: 检查是否在QMT目录的bin.x64子目录下
                    expected_exe_path = os.path.join(qmt_dir, 'bin.x64', 'XtMiniQmt.exe').lower()
                    path_match_3 = exe_path_lower == expected_exe_path

                    if path_match_1 or path_match_2 or path_match_3:
                        qmt_running = True
                        qmt_processes.append(proc.info)

            except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                continue

        # 调试日志 - 仅在状态变化或没有找到匹配进程时输出
        if not qmt_running and all_qmt_processes:
            log(f"[调试] 发现 {len(all_qmt_processes)} 个XtMiniQmt.exe进程，但路径不匹配:")
            log(f"[调试] 配置的QMT目录: {qmt_dir}")
            for proc_info in all_qmt_processes:
                log(f"[调试] PID {proc_info['pid']}: {proc_info['exe_path']}")

        current_status = {
            'qmt_running': qmt_running,
            'qmt_process_count': len(qmt_processes)
        }

        if self.last_status.get('qmt_running') != qmt_running:
            self._send_qmt_status_notification(qmt_running, qmt_processes)

        self.last_status.update(current_status)
        # 更新QMT状态标志，用于界面显示
        self.last_qmt_status = qmt_running

        if self.status_callback:
            status_msg = f"QMT状态: {'运行中' if qmt_running else '未运行'} ({len(qmt_processes)}个进程)"
            self.status_callback(status_msg)

    def _check_network_status(self):
        """检查网络连接状态"""
        qmt_dir = self.config_manager.get('qmt_dir')
        if not qmt_dir:
            return

        try:
            if not self.server_optimizer:
                only_vip = self.config_manager.get('qmt_only_vip', True)
                self.server_optimizer = ServerOptimizer(qmt_dir, only_vip)

            current_servers = self._get_current_server_config()
            if not current_servers:
                return

            hq_server = current_servers.get('hq_server')
            jy_server = current_servers.get('jy_server')

            network_status = {
                'hq_server': hq_server,
                'jy_server': jy_server,
                'hq_latency': float('inf'),
                'jy_latency': float('inf'),
                'last_test_time': datetime.now().strftime('%H:%M:%S')
            }

            if hq_server:
                network_status['hq_latency'] = NetworkTester.measure_latency(
                    hq_server['ip'], hq_server['port']
                )

            if jy_server:
                network_status['jy_latency'] = NetworkTester.measure_latency(
                    jy_server['ip'], jy_server['port']
                )

            # 判断网络连接状态
            hq_connected = network_status['hq_latency'] != float('inf') if hq_server else True
            jy_connected = network_status['jy_latency'] != float('inf') if jy_server else True
            network_status['connected'] = hq_connected and jy_connected

            # 更新网络状态标志，用于界面显示
            self.last_network_status = network_status['connected']

            self._check_network_status_change(network_status)

            if self.status_callback:
                status_msg = f"网络状态: {'正常' if network_status.get('connected', False) else '异常'}"
                self.status_callback(status_msg)

        except Exception as e:
            log(f"网络状态检查异常: {str(e)}")

    def _get_current_server_config(self):
        """获取当前服务器配置"""
        try:
            qmt_dir = self.config_manager.get('qmt_dir')
            config_path = os.path.join(qmt_dir, 'userdata_mini', 'users', 'xtquoterconfig.xml')

            if not os.path.exists(config_path):
                return None

            tree = ET.parse(config_path)
            quoter_server_map = tree.find('QuoterServers')
            quoter_server_list = quoter_server_map.findall('QuoterServer')

            hq_server = None
            jy_server = None

            for server in quoter_server_list:
                server_info = {
                    'ip': server.attrib['address'],
                    'port': int(server.attrib['port']),
                    'servername': server.attrib['servername'],
                    'type': server.attrib['quotertype']
                }

                if server.attrib['quotertype'] == '0':  # 行情服务器
                    hq_server = server_info
                elif server.attrib['quotertype'] == '1':  # 交易服务器
                    jy_server = server_info

            return {
                'hq_server': hq_server,
                'jy_server': jy_server
            }

        except Exception as e:
            log(f"获取服务器配置异常: {str(e)}")
            return None

    def _check_network_status_change(self, network_status):
        """检查网络状态变化并发送通知"""
        hq_latency = network_status.get('hq_latency', float('inf'))
        jy_latency = network_status.get('jy_latency', float('inf'))

        high_latency_threshold = 200

        if hq_latency > high_latency_threshold:
            self._send_network_notification(
                "行情服务器延迟过高",
                f"当前延迟: {hq_latency:.2f}ms，建议切换服务器",
                "warning"
            )

        if jy_latency > high_latency_threshold:
            self._send_network_notification(
                "交易服务器延迟过高",
                f"当前延迟: {jy_latency:.2f}ms，建议切换服务器",
                "warning"
            )

    def _send_qmt_status_notification(self, is_running, processes):
        """发送QMT状态通知"""
        if not self._should_send_notification('qmt_status'):
            return

        if is_running:
            title = "QMT启动通知"
            content = f"QMT已启动，当前运行 {len(processes)} 个进程"
            msg_type = "success"
        else:
            title = "QMT关闭通知"
            content = "QMT已关闭或异常退出"
            msg_type = "warning"

        self.feishu_notifier.send_message(title, content, msg_type)

    def _send_network_notification(self, title, content, msg_type="info"):
        """发送网络状态通知"""
        if not self._should_send_notification('network_status'):
            return

        self.feishu_notifier.send_message(title, content, msg_type)

    def _should_send_notification(self, notification_type):
        """检查是否应该发送通知"""
        if not self.config_manager.get('enable_feishu_notification', True):
            return False

        start_time = self.config_manager.get('notification_start_time', '09:00:00')
        end_time = self.config_manager.get('notification_end_time', '15:30:00')

        if not self.feishu_notifier.is_notification_time(start_time, end_time):
            return False

        interval = self.config_manager.get('notification_interval', 300)
        return self.feishu_notifier.should_send_notification(notification_type, interval)

# ====================================================================
# 核心业务逻辑模块
# ====================================================================
class CoreLogic:
    """核心业务逻辑控制器"""

    def __init__(self, config_manager, status_callback, server_update_callback=None):
        self.config = config_manager
        self.status_callback = status_callback
        self.server_update_callback = server_update_callback
        
        self.process_manager = ProcessManager()
        self.startup_manager = StartupManager()
        self.schedule_manager = ScheduleManager(config_manager, status_callback, server_update_callback)
        
        self.feishu_notifier = FeishuNotifier(
            webhook_url=config_manager.get('feishu_webhook_url', ''),
            at_all=config_manager.get('feishu_at_all', False)
        )
        self.monitoring_thread = None
        self.start_monitoring()
    
    def restart_qmt(self):
        """立即重启QMT"""
        self.schedule_manager.restart_qmt_service()
    
    def shutdown_qmt_now(self):
        """立即关闭QMT"""
        self.schedule_manager.shutdown_qmt_service()
    
    def restart_rainbow_client(self):
        """立即重启彩虹客户端"""
        self.schedule_manager.restart_rainbow_service()
    
    def shutdown_rainbow_now(self):
        """立即关闭彩虹客户端"""
        self.schedule_manager.shutdown_rainbow_service()
    
    def delete_data_files_only(self):
        """仅删除数据文件，不重启彩虹客户端"""
        self.schedule_manager.delete_data_files_service()
    
    def restart_rainbow_client_only(self):
        """仅重启彩虹客户端（不删除数据）"""
        self.schedule_manager.restart_rainbow_service_only()
    
    def shutdown_system_now(self):
        """立即关机"""
        # 创建确认对话框
        msg_box = QMessageBox()
        msg_box.setWindowTitle("关机确认")
        msg_box.setText("确认要关闭计算机吗？")
        msg_box.setInformativeText("系统将在确认后1分钟内关机。")
        msg_box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        msg_box.button(QMessageBox.Yes).setText("确认")
        msg_box.button(QMessageBox.No).setText("取消")
        msg_box.setDefaultButton(QMessageBox.No)  # 默认选中取消按钮，避免误操作
        msg_box.setIcon(QMessageBox.Warning)

        # 显示对话框并获取用户选择
        result = msg_box.exec_()

        # 只有用户点击确认按钮才执行关机
        if result == QMessageBox.Yes:
            self.schedule_manager.shutdown_system_service()

    def toggle_startup(self, enable):
        """切换开机启动状态"""
        if self.startup_manager.set_startup(enable):
            self.status_callback("已设置开机启动" if enable else "已取消开机启动")
            return True
        else:
            self.status_callback("设置开机启动失败")
            return False
    
    def check_startup_status(self):
        """检查开机启动状态"""
        return self.startup_manager.check_startup_status()
    
    def start_schedule(self):
        """启动定时任务"""
        self.schedule_manager.start_schedule()
    
    def stop_schedule(self):
        """停止定时任务"""
        self.schedule_manager.stop_schedule()
    
    @property
    def is_schedule_running(self):
        """定时任务是否正在运行"""
        return self.schedule_manager.is_running
    
    def start_monitoring(self):
        """启动实时监控"""
        if self.monitoring_thread and self.monitoring_thread.is_alive():
            log("监控线程已在运行")
            return
        
        self.monitoring_thread = MonitoringThread(
            config_manager=self.config,
            feishu_notifier=self.feishu_notifier,
            status_callback=self.status_callback,
            server_update_callback=self.server_update_callback
        )
        self.monitoring_thread.start_monitoring()
        log("实时监控已启动")
        self.status_callback("实时监控已启动")
    
    def stop_monitoring(self):
        """停止实时监控"""
        if self.monitoring_thread:
            self.monitoring_thread.stop_monitoring()
            self.monitoring_thread = None
            log("实时监控已停止")
            self.status_callback("实时监控已停止")
    
    @property
    def is_monitoring_running(self):
        """监控是否正在运行"""
        return self.monitoring_thread and self.monitoring_thread.is_alive()
    
    def update_monitoring_config(self):
        """更新监控配置"""
        if self.monitoring_thread:
            # 更新飞书通知器配置
            self.feishu_notifier.webhook_url = self.config.get('feishu_webhook_url', '')
            self.feishu_notifier.at_all = self.config.get('feishu_at_all', False)
            
            # 如果监控正在运行，重启以应用新配置
            if self.is_monitoring_running:
                self.stop_monitoring()
                self.start_monitoring()

# ====================================================================
# UI样式表
# ====================================================================
STYLESHEET = """
QWidget {
    background-color: #1e1e1e;
    color: #d4d4d4;
    font-family: 'Microsoft YaHei';
    font-size: 22px;
}
QMainWindow {
    background-color: #252526;
}
QTabWidget::pane {
    border: 1px solid #3c3c3c;
    border-radius: 4px;
}
QTabBar::tab {
    background: #2d2d2d;
    color: #d4d4d4;
    padding: 10px 20px;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
    border: 1px solid #3c3c3c;
    border-bottom: none;
    margin-right: 2px;
}
QTabBar::tab:selected {
    background: #1e1e1e;
    color: #ffffff;
    border-bottom: 1px solid #1e1e1e;
}
QGroupBox {
    border: 1px solid #3c3c3c;
    border-radius: 5px;
    margin-top: 15px;
    padding-top: 20px;
    font-weight: bold;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 5px;
    background-color: #1e1e1e;
}
QLineEdit {
    background-color: #3c3c3c;
    border: 1px solid #555;
    border-radius: 4px;
    padding: 5px;
    color: #d4d4d4;
}
QLineEdit:read-only {
    background-color: #2d2d2d;
}
QPushButton {
    background-color: #0e639c;
    color: white;
    border: none;
    padding: 12px 15px;
    border-radius: 4px;
    min-height: 30px;
}
QPushButton:hover {
    background-color: #1177bb;
}
QPushButton:pressed {
    background-color: #0c568a;
}
QCheckBox {
    spacing: 5px;
}
QCheckBox::indicator {
    width: 18px;
    height: 18px;
}
QLabel#statusLabel {
    font-size: 22px;
    font-weight: bold;
    color: #4ec9b0;
}
"""

# ====================================================================
# 主窗口UI模块
# ====================================================================
class MainWindow(QMainWindow):
    """主窗口界面"""
    status_update_signal = Signal(str)
    server_update_signal = Signal(str, str)

    def __init__(self):
        super().__init__()
        
        self.config_manager = ConfigManager()
        self.memory_manager = MemoryManager()
        self.async_manager = AsyncOperationManager(max_workers=4)
        # 先初始化 core_logic，避免 UI 构建过程中引用属性不存在
        self.core_logic = CoreLogic(
            self.config_manager,
            self.update_status_bar,
            self.update_server_info
        )
        self.core_logic.memory_manager = self.memory_manager
        self.core_logic.async_manager = self.async_manager
        
        # 再初始化 UI 与其它组件
        self.init_ui()
        self.connect_signals()
        self.init_timers()

        self.load_initial_state()

    def init_ui(self):
        """初始化用户界面"""
        self.setWindowTitle("∞MeowTech.实盘无限守护")
        self.setGeometry(300, 300, 600, 500)
        self.setStyleSheet(STYLESHEET)

        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

        self.create_operation_page()
        self.create_config_page()
        
        self.status_label = QLabel("就绪")
        self.status_label.setObjectName("statusLabel")
        self.statusBar().addWidget(self.status_label)

    def connect_signals(self):
        self.status_update_signal.connect(self.update_status_bar)
        self.server_update_signal.connect(self.update_server_info)
    
    def init_timers(self):
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_next_run_time)
        self.timer.start(1000)
    
    def load_initial_state(self):
        """加载初始状态"""
        if not StartupManager.diagnose_startup():
            log(f"✗ 开机启动诊断失败，可能存在权限或环境问题")
        
        config_startup = self.config_manager.get('enable_startup', False)
        registry_startup = self.core_logic.check_startup_status()
        
        final_status = config_startup
        
        if config_startup != registry_startup:
            log(f"检测到状态不一致，开始同步")
            
            if self.core_logic.toggle_startup(config_startup):
                new_registry_status = self.core_logic.check_startup_status()
                if new_registry_status == config_startup:
                    log(f"✓ 同步成功")
                    final_status = config_startup
                else:
                    final_status = registry_startup
                    self.config_manager.set('enable_startup', registry_startup)
                    log(f"同步失败，已更新配置文件")
            else:
                # 同步失败，以注册表实际状态为准
                final_status = registry_startup
                self.config_manager.set('enable_startup', registry_startup)
                log(f"同步操作失败，已更新配置文件")
        
        # 4. 更新UI状态
        self.update_button_states()
        
        # 5. 恢复定时任务状态
        self.restore_schedule_state()
        
        # 6. 启动时自动重启QMT和彩虹客户端
        self.perform_startup_restart()
    
    def restore_schedule_state(self):
        """恢复定时任务状态"""
        try:
            # 从配置文件读取上次的定时任务状态
            was_schedule_running = self.config_manager.get('schedule_running', False)
            
            if was_schedule_running:
                log("检测到上次定时任务处于运行状态，正在恢复...")
                
                # 验证配置有效性
                qmt_dir = self.config_manager.get('qmt_dir')
                qmt_time = self.config_manager.get('qmt_run_time')
                
                if os.path.exists(qmt_dir) and is_valid_time(qmt_time):
                    self.core_logic.start_schedule()
                    log("✓ 定时任务状态已恢复")
                    # 更新UI按钮状态
                    self.update_button_states()
                else:
                    log("✗ 配置验证失败，无法恢复定时任务状态")
                    # 更新配置状态为未运行
                    self.config_manager.set('schedule_running', False)
                    self.config_manager.save_config()
                    # 更新UI按钮状态
                    self.update_button_states()
            else:
                log("上次定时任务未运行，保持停止状态")
                
        except Exception as e:
            log(f"恢复定时任务状态失败: {e}")
            # 发生异常时确保状态为停止
            self.config_manager.set('schedule_running', False)
            self.config_manager.save_config()
            # 更新UI按钮状态
            self.update_button_states()
    
    def perform_startup_restart(self):
        """程序启动时自动重启QMT和彩虹客户端"""
        log("程序启动检测：开始自动重启QMT和彩虹客户端...")
        
        def restart_worker():
            try:
                log("正在重启QMT...")
                self.core_logic.restart_qmt()
                
                time.sleep(2)
                
                log("正在重启彩虹客户端...")
                self.core_logic.restart_rainbow_client()
                
                log("✓ 启动时自动重启完成")
                
            except Exception as e:
                log(f"✗ 启动时自动重启失败: {e}")
        
        restart_thread = threading.Thread(target=restart_worker, daemon=True)
        restart_thread.start()

    def create_operation_page(self):
        """创建操作页面"""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(20)

        schedule_group = self._create_schedule_control_group()
        qmt_group = self._create_qmt_control_group()
        rainbow_group = self._create_rainbow_control_group()
        system_group = self._create_system_control_group()
        
        layout.addWidget(qmt_group)
        layout.addWidget(rainbow_group)
        layout.addWidget(system_group)
        layout.addWidget(schedule_group)
        layout.addStretch()
        
        self.tabs.addTab(page, "操作")
    
    def _create_qmt_control_group(self):
        """创建QMT控制组"""
        qmt_group = QGroupBox("QMT 控制")
        qmt_layout = QVBoxLayout()
        qmt_layout.setSpacing(15)
        
        manual_qmt_layout = QHBoxLayout()
        manual_qmt_layout.setSpacing(10)
        restart_qmt_btn = QPushButton("立即重启QMT")
        restart_qmt_btn.setStyleSheet("background-color: #4caf50; color: white; font-weight: bold;")
        restart_qmt_btn.clicked.connect(lambda: Worker(self.core_logic.restart_qmt).start())
        
        shutdown_qmt_btn = QPushButton("立即关闭QMT")
        shutdown_qmt_btn.clicked.connect(lambda: Worker(self.core_logic.shutdown_qmt_now).start())
        
        manual_qmt_layout.addWidget(restart_qmt_btn)
        manual_qmt_layout.addWidget(shutdown_qmt_btn)
        qmt_layout.addLayout(manual_qmt_layout)
        
        server_info_layout = QFormLayout()
        self.best_hq_label = QLabel("待检测")
        self.best_jy_label = QLabel("待检测")
        server_info_layout.addRow("最佳行情服务器:", self.best_hq_label)
        server_info_layout.addRow("最佳交易服务器:", self.best_jy_label)
        
        status_layout = QHBoxLayout()
        self.network_status_label = QLabel("待检测")
        self.network_status_label.setAlignment(Qt.AlignLeft)
        self.qmt_process_label = QLabel("待检测")
        self.qmt_process_label.setAlignment(Qt.AlignLeft)
        
        network_label = QLabel("网络状态:")
        network_label.setAlignment(Qt.AlignLeft)
        qmt_label = QLabel("  QMT进程:")
        qmt_label.setAlignment(Qt.AlignLeft)
        
        status_layout.addWidget(network_label)
        status_layout.addWidget(self.network_status_label)
        status_layout.addWidget(qmt_label)
        status_layout.addWidget(self.qmt_process_label)
        status_layout.addStretch()
        status_widget = QWidget()
        status_widget.setLayout(status_layout)
        server_info_layout.addRow("", status_widget)
        
        qmt_layout.addLayout(server_info_layout)

        qmt_group.setLayout(qmt_layout)
        return qmt_group
    
    def _create_rainbow_control_group(self):
        """创建彩虹客户端控制组"""
        rainbow_group = QGroupBox("彩虹客户端控制")
        rainbow_layout = QVBoxLayout()
        rainbow_layout.setSpacing(10)
        
        # 手动操作按钮
        restart_rainbow_btn = QPushButton("立即重启彩虹客户端")
        restart_rainbow_btn.setStyleSheet("background-color: #4caf50; color: white; font-weight: bold;")
        restart_rainbow_btn.clicked.connect(lambda: Worker(self.core_logic.restart_rainbow_client_only).start())
        rainbow_layout.addWidget(restart_rainbow_btn)
        
        shutdown_rainbow_btn = QPushButton("立即关闭彩虹客户端")
        shutdown_rainbow_btn.clicked.connect(lambda: Worker(self.core_logic.shutdown_rainbow_now).start())
        rainbow_layout.addWidget(shutdown_rainbow_btn)
        
        # 新增：独立的删除数据文件按钮
        delete_data_btn = QPushButton("删除数据文件")
        delete_data_btn.clicked.connect(lambda: Worker(self.core_logic.delete_data_files_only).start())
        rainbow_layout.addWidget(delete_data_btn)
        
        rainbow_group.setLayout(rainbow_layout)
        return rainbow_group
    
    def _create_schedule_control_group(self):
        """创建定时任务总控"""
        group = QGroupBox("定时任务总控")
        layout = QVBoxLayout()
        layout.setSpacing(15)

        self.schedule_btn = QPushButton("启动总定时器")
        self.schedule_btn.setCheckable(True)
        self.schedule_btn.clicked.connect(self.toggle_schedule)

        self.next_run_label = QLabel("下次运行时间:\n定时任务未启动")
        self.next_run_label.setAlignment(Qt.AlignLeft)
        self.next_run_label.setStyleSheet("font-size: 24px; color: #4ec9b0; font-weight: bold;")

        layout.addWidget(self.schedule_btn)
        layout.addWidget(self.next_run_label)

        group.setLayout(layout)
        return group

    def _create_system_control_group(self):
        """创建系统控制组"""
        system_group = QGroupBox("系统控制")
        system_layout = QVBoxLayout()
        system_layout.setSpacing(10)
        
        self.startup_btn = QPushButton("设置开机启动")
        self.startup_btn.clicked.connect(self.toggle_startup)
        system_layout.addWidget(self.startup_btn)

        shutdown_system_btn = QPushButton("立即关机")
        # 修复: 不能在后台线程中创建/执行 QMessageBox，否则会导致窗口卡死“未响应”
        # 原实现: shutdown_system_btn.clicked.connect(lambda: Worker(self.core_logic.shutdown_system_now).start())
        shutdown_system_btn.clicked.connect(self.core_logic.shutdown_system_now)
        system_layout.addWidget(shutdown_system_btn)

        system_group.setLayout(system_layout)
        return system_group
    


    def create_config_page(self):
        """创建配置页面"""
        page = QWidget()
        layout = QVBoxLayout(page)

        qmt_group = self._create_qmt_config_group()
        rainbow_group = self._create_rainbow_config_group()
        delete_group = self._create_delete_config_group()
        system_monitoring_group = self._create_system_monitoring_config_group()
        
        button_layout = QHBoxLayout()
        
        button_layout.addStretch()
        
        save_btn = QPushButton("保存配置")
        save_btn.clicked.connect(self.save_config)
        button_layout.addWidget(save_btn)

        layout.addWidget(qmt_group)
        layout.addWidget(rainbow_group)
        layout.addWidget(delete_group)
        layout.addWidget(system_monitoring_group)
        layout.addLayout(button_layout)
        layout.addStretch()
        
        self.tabs.addTab(page, "配置")
    
    def _create_qmt_config_group(self):
        """创建QMT配置组"""
        qmt_group = QGroupBox("QMT 配置")
        qmt_form = QFormLayout()
        
        self.qmt_dir_input = QLineEdit(self.config_manager.get('qmt_dir'))
        self.qmt_run_time_input = QLineEdit(self.config_manager.get('qmt_run_time'))
        self.qmt_run_time_input.setPlaceholderText("留空则不执行")
        self.qmt_shutdown_time_edit = QLineEdit(self.config_manager.get('qmt_shutdown_time', '15:05:00'))
        self.qmt_shutdown_time_edit.setPlaceholderText("留空则不执行")
        self.qmt_only_vip_checkbox = QCheckBox("仅使用VIP服务器")
        self.qmt_only_vip_checkbox.setChecked(self.config_manager.get("qmt_only_vip", True))
        
        # 创建定时时间范围的水平布局
        qmt_time_widget = QWidget()
        qmt_time_layout = QHBoxLayout(qmt_time_widget)
        qmt_time_layout.setContentsMargins(0, 0, 0, 0)
        qmt_time_layout.addWidget(self.qmt_run_time_input)
        qmt_time_layout.addWidget(QLabel(" / "))
        qmt_time_layout.addWidget(self.qmt_shutdown_time_edit)
        
        qmt_form.addRow("QMT 路径:", self.qmt_dir_input)
        qmt_form.addRow("定时 重启/关闭:", qmt_time_widget)
        qmt_form.addRow("", self.qmt_only_vip_checkbox)
        
        qmt_group.setLayout(qmt_form)
        return qmt_group
    
    def _create_rainbow_config_group(self):
        """创建彩虹客户端配置组"""
        rainbow_group = QGroupBox("彩虹客户端配置")
        rainbow_form = QFormLayout()
        
        self.rainbow_exe_path_input = QLineEdit(self.config_manager.get('rainbow_exe_path'))
        self.rainbow_restart_time_input = QLineEdit(self.config_manager.get('rainbow_restart_time'))
        self.rainbow_restart_time_input.setPlaceholderText("留空则不执行")
        self.rainbow_shutdown_time_edit = QLineEdit(self.config_manager.get('rainbow_shutdown_time', '15:10:00'))
        self.rainbow_shutdown_time_edit.setPlaceholderText("留空则不执行")
        
        rainbow_time_widget = QWidget()
        rainbow_time_layout = QHBoxLayout(rainbow_time_widget)
        rainbow_time_layout.setContentsMargins(0, 0, 0, 0)
        rainbow_time_layout.addWidget(self.rainbow_restart_time_input)
        rainbow_time_layout.addWidget(QLabel(" / "))
        rainbow_time_layout.addWidget(self.rainbow_shutdown_time_edit)
        
        rainbow_form.addRow("彩虹客户端路径:", self.rainbow_exe_path_input)
        rainbow_form.addRow("定时 重启/关闭:", rainbow_time_widget)
        
        rainbow_group.setLayout(rainbow_form)
        return rainbow_group
    
    def _create_delete_config_group(self):
        """创建数据删除配置组"""
        delete_group = QGroupBox("数据删除配置")
        delete_form = QFormLayout()
        
        self.delete_base_path_input = QLineEdit(self.config_manager.get('delete_base_path'))
        self.delete_folders_input = QLineEdit(self.config_manager.get('delete_folders'))
        
        delete_form.addRow("基础路径:", self.delete_base_path_input)
        delete_form.addRow("文件夹名称 (逗号分隔):", self.delete_folders_input)
        
        delete_group.setLayout(delete_form)
        return delete_group
    
    def _create_system_monitoring_config_group(self):
        """创建系统监控配置组"""
        system_monitoring_group = QGroupBox("系统监控配置")
        system_monitoring_form = QFormLayout()
        
        # 定时关机配置
        self.system_shutdown_time_edit = QLineEdit(self.config_manager.get('system_shutdown_time', '15:30:00'))
        self.system_shutdown_time_edit.setPlaceholderText("留空则不执行")
        system_monitoring_form.addRow("定时关机:", self.system_shutdown_time_edit)
        
        # 监控间隔配置
        self.monitor_interval_input = QLineEdit(str(self.config_manager.get('monitor_interval', 10)))
        self.monitor_interval_input.setPlaceholderText("监控间隔（秒）")
        self.notification_interval_input = QLineEdit(str(self.config_manager.get('notification_interval', 300)))
        self.notification_interval_input.setPlaceholderText("通知间隔（秒）")
        
        interval_widget = QWidget()
        interval_layout = QHBoxLayout(interval_widget)
        interval_layout.setContentsMargins(0, 0, 0, 0)
        interval_layout.addWidget(self.monitor_interval_input)
        interval_layout.addWidget(QLabel(" / "))
        interval_layout.addWidget(self.notification_interval_input)
        
        system_monitoring_form.addRow("监控/通知 间隔(秒):", interval_widget)
        
        # 通知时间范围配置
        self.notification_start_time_input = QLineEdit(self.config_manager.get('notification_start_time', '09:00:00'))
        self.notification_start_time_input.setPlaceholderText("HH:MM:SS")
        self.notification_end_time_input = QLineEdit(self.config_manager.get('notification_end_time', '15:30:00'))
        self.notification_end_time_input.setPlaceholderText("HH:MM:SS")
        
        time_range_widget = QWidget()
        time_range_layout = QHBoxLayout(time_range_widget)
        time_range_layout.setContentsMargins(0, 0, 0, 0)
        time_range_layout.addWidget(self.notification_start_time_input)
        time_range_layout.addWidget(QLabel(" - "))
        time_range_layout.addWidget(self.notification_end_time_input)
        
        system_monitoring_form.addRow("通知时间范围:", time_range_widget)
        
        # 飞书通知配置
        self.feishu_webhook_input = QLineEdit(self.config_manager.get('feishu_webhook_url', ''))
        self.feishu_webhook_input.setPlaceholderText("飞书机器人Webhook URL（配置即开启通知，默认@所有人）")
        # 设置更长的输入框最小宽度
        self.feishu_webhook_input.setMinimumWidth(400)
        
        system_monitoring_form.addRow("飞书Webhook:", self.feishu_webhook_input)
        
        system_monitoring_group.setLayout(system_monitoring_form)
        return system_monitoring_group
    def toggle_schedule(self):
        """切换定时任务状态"""
        if self.core_logic.is_schedule_running:
            self.core_logic.stop_schedule()
            # 保存定时任务停止状态
            self.config_manager.set('schedule_running', False)
            self.config_manager.save_config()
        else:
            qmt_dir = self.config_manager.get('qmt_dir')
            qmt_time = self.config_manager.get('qmt_run_time')
            
            if not os.path.exists(qmt_dir):
                QMessageBox.warning(self, "错误", "QMT 路径不存在，请检查配置")
                return
            
            if not is_valid_time(qmt_time):
                QMessageBox.warning(self, "错误", "QMT 定时重启时间格式不正确")
                return
            
            self.core_logic.start_schedule()
            # 保存定时任务启动状态
            self.config_manager.set('schedule_running', True)
            self.config_manager.save_config()
        
        self.update_button_states()
    
    def toggle_monitoring(self):
        """切换监控状态"""
        if self.core_logic.is_monitoring_running:
            self.core_logic.stop_monitoring()
        else:
            self.core_logic.start_monitoring()
    

    
    def toggle_startup(self):
        """切换开机启动状态"""
        current_status = self.config_manager.get('enable_startup', False)
        target_status = not current_status
        
        if not StartupManager.diagnose_startup():
            QMessageBox.warning(self, "警告", 
                              "开机启动环境检查失败，可能存在权限问题。\n"
                              "请尝试以管理员身份运行程序。")
            return
        
        if self.core_logic.toggle_startup(target_status):
            actual_status = self.core_logic.check_startup_status()
            
            if actual_status == target_status:
                self.config_manager.set('enable_startup', target_status)
                self.update_button_states()
                
                success_msg = "✓ 开机启动已启用" if target_status else "✓ 开机启动已禁用"
                log(f"{success_msg}")
                QMessageBox.information(self, "成功", success_msg)
            else:
                error_msg = f"设置操作完成，但验证失败\n期望状态: {target_status}\n实际状态: {actual_status}"
                log(f"✗ {error_msg}")
                QMessageBox.warning(self, "警告", error_msg)
                
                # 以实际状态为准更新配置
                self.config_manager.set('enable_startup', actual_status)
                self.update_button_states()
        else:
            # 操作失败
            error_msg = f"{'启用' if target_status else '禁用'}开机启动失败\n请检查系统权限或重试"
            log(f"✗ {error_msg}")
            QMessageBox.critical(self, "错误", error_msg)

    # ----------------------------------------------------------------
    # 配置管理
    def save_config(self):
        """保存配置"""
        qmt_time = self.qmt_run_time_input.text().strip()
        qmt_shutdown_time = self.qmt_shutdown_time_edit.text().strip()
        rainbow_time = self.rainbow_restart_time_input.text().strip()
        rainbow_shutdown_time = self.rainbow_shutdown_time_edit.text().strip()
        system_shutdown_time = self.system_shutdown_time_edit.text().strip()
        
        if not is_valid_time(qmt_time):
            QMessageBox.warning(self, "错误", "QMT定时重启时间格式不正确，请使用 HH:MM:SS 格式或留空不启用")
            return
        
        if not is_valid_time(qmt_shutdown_time):
            QMessageBox.warning(self, "错误", "QMT定时关闭时间格式不正确，请使用 HH:MM:SS 格式或留空不执行")
            return
        
        if not is_valid_time(rainbow_time):
            QMessageBox.warning(self, "错误", "彩虹客户端定时重启时间格式不正确，请使用 HH:MM:SS 格式或留空不启用")
            return
        
        if not is_valid_time(rainbow_shutdown_time):
            QMessageBox.warning(self, "错误", "彩虹客户端定时关闭时间格式不正确，请使用 HH:MM:SS 格式或留空不执行")
            return
        
        if not is_valid_time(system_shutdown_time):
            QMessageBox.warning(self, "错误", "系统定时关机时间格式不正确，请使用 HH:MM:SS 格式或留空不执行")
            return
        
        monitor_interval = self.monitor_interval_input.text().strip()
        notification_interval = self.notification_interval_input.text().strip()
        notification_start_time = self.notification_start_time_input.text().strip()
        notification_end_time = self.notification_end_time_input.text().strip()
        
        try:
            if monitor_interval:
                int(monitor_interval)
            if notification_interval:
                int(notification_interval)
        except ValueError:
            QMessageBox.warning(self, "错误", "监控间隔和通知间隔必须是数字")
            return
        
        if not is_valid_time(notification_start_time):
            QMessageBox.warning(self, "错误", "通知开始时间格式不正确，请使用 HH:MM:SS 格式")
            return
        
        if not is_valid_time(notification_end_time):
            QMessageBox.warning(self, "错误", "通知结束时间格式不正确，请使用 HH:MM:SS 格式")
            return
        
        config_updates = {
            'qmt_dir': self.qmt_dir_input.text().strip(),
            'qmt_run_time': qmt_time,
            'qmt_shutdown_time': qmt_shutdown_time,
            'qmt_only_vip': self.qmt_only_vip_checkbox.isChecked(),
            'rainbow_exe_path': self.rainbow_exe_path_input.text().strip(),
            'rainbow_restart_time': rainbow_time,
            'rainbow_shutdown_time': rainbow_shutdown_time,
            'delete_base_path': self.delete_base_path_input.text().strip(),
            'delete_folders': self.delete_folders_input.text().strip(),
            'system_shutdown_time': system_shutdown_time,
            'monitor_interval': int(monitor_interval) if monitor_interval else 10,
            'notification_interval': int(notification_interval) if notification_interval else 300,
            'notification_start_time': notification_start_time,
            'notification_end_time': notification_end_time,
            'enable_feishu_notification': bool(self.feishu_webhook_input.text().strip()),
            'feishu_webhook_url': self.feishu_webhook_input.text().strip(),
            'feishu_at_all': True
        }
        
        self.config_manager.update(config_updates)
        
        if self.config_manager.save_config():
            self.update_status_bar("配置已保存！")
            
            # 自动测试飞书通知
            feishu_url = self.feishu_webhook_input.text().strip()
            if feishu_url:
                try:
                    test_notifier = FeishuNotifier(
                        webhook_url=feishu_url,
                        at_all=self.config_manager.get('feishu_at_all', False)
                    )
                    
                    success = test_notifier.send_message(
                        title="🧪 配置保存测试通知",
                        content="配置已成功保存，这是一条来自∞MeowTech.实盘无限守护的测试通知",
                        msg_type="info"
                    )
                    
                    if success:
                        QMessageBox.information(self, "成功", "配置已成功保存！\n飞书通知测试成功！")
                        self.update_status_bar("配置已保存，飞书通知测试成功")
                    else:
                        QMessageBox.warning(self, "部分成功", "配置已成功保存！\n但飞书通知测试失败，请检查Webhook URL")
                        self.update_status_bar("配置已保存，飞书通知测试失败")
                        
                except Exception as e:
                    QMessageBox.warning(self, "部分成功", f"配置已成功保存！\n但飞书通知测试时发生错误: {str(e)}")
                    self.update_status_bar(f"配置已保存，飞书通知测试错误: {str(e)}")
            else:
                QMessageBox.information(self, "成功", "配置已成功保存！")
        else:
            QMessageBox.warning(self, "错误", "配置保存失败！")
        
        if self.core_logic.is_schedule_running:
            self.core_logic.stop_schedule()
            self.core_logic.start_schedule()
        
        self.core_logic.update_monitoring_config()
        
        self.update_button_states()
    
    def closeEvent(self, event):
        """关闭窗口前保存配置并清理资源"""
        try:
            self.config_manager.save_config()
            
            if hasattr(self, 'async_manager'):
                self.async_manager.shutdown()
                
            # 强制清理内存
            if hasattr(self, 'memory_manager'):
                self.memory_manager.force_cleanup()
                
            log("程序资源清理完成")
        except Exception as e:
            log(f"资源清理时发生错误: {e}")
        finally:
            super().closeEvent(event)

    def update_button_states(self):
        """更新按钮状态和文本"""
        if self.core_logic.is_schedule_running:
            self.schedule_btn.setText("停止定时任务")
            self.schedule_btn.setStyleSheet("background-color: #f44336; color: white;")
        else:
            self.schedule_btn.setText("启动定时任务")
            self.schedule_btn.setStyleSheet("background-color: #4caf50; color: white;")
        
        if self.config_manager.get('enable_startup', False):
            self.startup_btn.setText("取消开机启动")
            self.startup_btn.setStyleSheet("background-color: #ff9800; color: white;")
        else:
            self.startup_btn.setText("设置开机启动")
            self.startup_btn.setStyleSheet("background-color: #2196f3; color: white;")


    
    def update_next_run_time(self):
        """更新下次运行时间显示并监控内存使用情况"""
        if hasattr(self, 'memory_manager'):
            self.memory_manager.cleanup_if_needed()
            
        if self.core_logic.is_schedule_running:
            next_run = schedule.next_run()
            if next_run:
                restart_tasks = []
                shutdown_tasks = []
                system_tasks = []
                
                qmt_time = self.config_manager.get('qmt_run_time')
                if qmt_time:
                    restart_tasks.append(f"QMT重启: {qmt_time}")
                
                rainbow_time = self.config_manager.get('rainbow_restart_time')
                if rainbow_time:
                    restart_tasks.append(f"彩虹重启: {rainbow_time}")
                
                qmt_shutdown_time = self.config_manager.get('qmt_shutdown_time')
                if qmt_shutdown_time:
                    shutdown_tasks.append(f"QMT关闭: {qmt_shutdown_time}")
                
                rainbow_shutdown_time = self.config_manager.get('rainbow_shutdown_time')
                if rainbow_shutdown_time:
                    shutdown_tasks.append(f"彩虹关闭: {rainbow_shutdown_time}")
                
                system_shutdown_time = self.config_manager.get('system_shutdown_time')
                if system_shutdown_time:
                    system_tasks.append(f"系统关机: {system_shutdown_time}")
                
                status_lines = ["下次运行时间:"]
                if restart_tasks:
                    status_lines.append("重启任务: " + " / ".join(restart_tasks))
                if shutdown_tasks:
                    status_lines.append("关闭任务: " + " / ".join(shutdown_tasks))
                if system_tasks:
                    status_lines.append("系统任务: " + " / ".join(system_tasks))
                
                if len(status_lines) > 1:
                    status = "\n".join(status_lines)
                else:
                    status = "下次运行时间:\n无有效任务配置"
            else:
                status = "下次运行时间: 计算中..."
        else:
            status = "下次运行时间: 定时任务未启动"
        
        self.next_run_label.setText(status)
        
        self.update_monitoring_status()
    
    def update_status_bar(self, message):
        """线程安全地更新状态栏文本"""
        if threading.current_thread() is not threading.main_thread():
            self.status_update_signal.emit(message)
        else:
            log(message)
            self.status_label.setText(message)
    
    def update_server_info(self, hq_info, jy_info):
        """更新服务器信息显示"""
        if threading.current_thread() is not threading.main_thread():
            self.server_update_signal.emit(hq_info, jy_info)
        else:
            self.best_hq_label.setText(hq_info)
            self.best_jy_label.setText(jy_info)
    
    def update_monitoring_status(self):
        """更新监控状态显示并检查内存使用情况"""
        try:
            if hasattr(self, 'memory_manager'):
                self.memory_manager.cleanup_if_needed()
                
            if hasattr(self, 'network_status_label') and hasattr(self, 'qmt_process_label'):
                is_running = self.core_logic.is_monitoring_running
                if is_running and hasattr(self.core_logic, 'monitoring_thread') and self.core_logic.monitoring_thread:
                    network_status = "正常" if self.core_logic.monitoring_thread.last_network_status else "异常"
                    qmt_status = "运行中" if self.core_logic.monitoring_thread.last_qmt_status else "未运行"
                    
                    # 内存显示已移除
                    
                    self.network_status_label.setText(network_status)
                    self.qmt_process_label.setText(qmt_status)
                    
                    network_color = "#51cf66" if self.core_logic.monitoring_thread.last_network_status else "#ff6b6b"
                    qmt_color = "#51cf66" if self.core_logic.monitoring_thread.last_qmt_status else "#ff6b6b"
                    
                    self.network_status_label.setStyleSheet(f"color: {network_color}; font-weight: bold; font-size: 14px;")
                    self.qmt_process_label.setStyleSheet(f"color: {qmt_color}; font-weight: bold; font-size: 14px;")
                else:
                    self.network_status_label.setText("待检测")
                    self.qmt_process_label.setText("待检测")
                    self.network_status_label.setStyleSheet("color: #868e96; font-size: 14px;")
                    self.qmt_process_label.setStyleSheet("color: #868e96; font-size: 14px;")
        except Exception as e:
            log(f"更新监控状态显示时发生错误: {e}")

