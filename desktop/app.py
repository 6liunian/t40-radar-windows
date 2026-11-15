"""Standalone launcher. No hardware is opened until preflight succeeds."""
from __future__ import annotations
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
import traceback

VERSION = '0.5.2'
FROZEN = getattr(sys, 'frozen', False)
BASE = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
ASSETS = BASE / 'assets' if FROZEN else Path(__file__).parent / 'assets'
PROJECT = Path(__file__).resolve().parents[1]
if not FROZEN:
    sys.path[:0] = [str(PROJECT / 'native_windows'), str(PROJECT / 'radar_client')]
DATA = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'T40Radar'
RUNTIME = DATA / 'runtime'
LOGS = DATA / 'logs'
for folder in (RUNTIME, LOGS):
    folder.mkdir(parents=True, exist_ok=True)
os.environ['RADAR_RUNTIME_DIR'] = str(RUNTIME)
os.environ['RADAR_FIRMWARE_DIR'] = str(ASSETS / 'firmware' if FROZEN else PROJECT / 'native_windows' / 'firmware')
os.environ['RADAR_CAPTURE_DIR'] = str(DATA / 'captures')
os.environ['RADAR_TELEMETRY_PATH'] = str(RUNTIME / 'panel.json')
os.environ['RADAR_LOCAL_IP'] = '192.168.8.1'
os.environ['RADAR_REMOTE_IP'] = '192.168.8.2'
if FROZEN:
    os.environ['PATH'] = str(BASE) + os.pathsep + os.environ.get('PATH', '')
    DLL_COOKIE = os.add_dll_directory(str(BASE))


def command(*args):
    return [sys.executable, *([] if FROZEN else [str(Path(__file__).resolve())]), *args]


def redirect_log(name):
    stream = (LOGS / (time.strftime('%Y%m%d-%H%M%S') + '-' + name + '.log')).open('a', encoding='utf-8', buffering=1)
    sys.stdout = sys.stderr = stream
    return stream


def self_test(destination):
    """Exercise bundled dependencies and an actual TkAgg panel without USB/CAN I/O."""
    os.environ.pop('RADAR_TELEMETRY_PATH',None)
    import tkinter as tk
    import usb1
    import can.interfaces.pcan.pcan
    import radar_control_panel as panel
    from ath6kl_win.firmware import load_verified
    load_verified(Path(os.environ['RADAR_FIRMWARE_DIR']))
    # Loading the libraries checks packaging; it neither claims USB nor opens a CAN channel.
    with usb1.USBContext():
        pass
    ctypes.WinDLL(str(BASE / 'PCANBasic.dll') if FROZEN else str(PROJECT / 'windows/pcan-basic-x64/x64/PCANBasic.dll'))
    root = tk.Tk()
    root.withdraw()
    os.environ['RADAR_TEST_WINDOW'] = '1'
    panel.RadarControlPanel._start_worker = lambda self: None
    view = panel.RadarControlPanel(root)
    # Exercise nonempty contour artists in the frozen build, without device I/O.
    now = time.monotonic()
    view.telemetry.pcla = [(3+x*.15, 2+y*.15, z*.15, 0, 0)
                          for x in range(3) for y in range(3) for z in range(3)]
    view.telemetry.last_udp_at = now
    view.telemetry.layer_updated['pcla'] = now
    view.telemetry.frame_total = 1
    view.cloud.update(view.telemetry.snapshot(), force=True)
    for mode in ('3D', '俯视', '侧视'):
        view._change_view(mode)
        view.canvas.draw()
    import paramiko
    from sector_cloud import decode_sectors, SIZE, STRIDE
    import struct
    assert hasattr(paramiko,'DSSKey'), 'Radar requires ssh-dss support'
    raw=bytearray(SIZE)
    for index in range(360):
        raw[index*STRIDE]=1;raw[index*STRIDE+1]=1
        struct.pack_into('<f',raw,index*STRIDE+15,3)
    points,stats,_=decode_sectors(raw)
    view.telemetry.sector_history.append('pcla',points,time.monotonic())
    view.telemetry.sector_at=time.monotonic();view.telemetry.actual_rpm=650;view.telemetry.last_can_at=time.monotonic()
    view.telemetry.sector_stats=stats;view.source_box.set('360° 扇区');view._source_changed();view.canvas.draw()
    assert view.cloud.last_stats['plotted']==360
    view._change_view('3D');assert view.cloud.mode=='俯视'
    view.source_box.set('避障候选');view._source_changed();view.canvas.draw()
    root.update()
    view.close()
    result = {'ok': True, 'version': VERSION, 'frozen': FROZEN, 'python': sys.version,
              'checks': ['firmware hashes', 'libusb DLL', 'PCANBasic DLL', 'python-can PCAN backend', 'TkAgg 3D/top/side nonempty outline views','SSH DSS compatibility','360-sector decode and source switching'],
              'hardware_opened': False}
    Path(destination).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')


def watch_parent(pid):
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x00100000, False, pid)
    if handle:
        kernel.WaitForSingleObject(handle, 0xffffffff)
        (RUNTIME / 'stop').touch()
        kernel.CloseHandle(handle)


class Launcher:
    def __init__(self):
        import tkinter as tk
        from tkinter import ttk
        self.root = tk.Tk()
        self.root.title('T40 雷达控制台 · ' + VERSION)
        self.root.iconbitmap(str(ASSETS / 'T40Radar.ico'))
        self.root.geometry('600x320')
        self.root.configure(bg='#12171c')
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        self.cancelled = threading.Event()
        self.messages = queue.Queue()
        self.child = None
        self.recovery_thread = None
        self.recovery_attempts = 0
        self.backend_started = time.monotonic()
        self.last_backend_rx = None
        self.last_backend_progress = time.monotonic()
        self.preparing = False
        self.panel = None
        tk.Label(self.root, text='T40 雷达控制台', bg='#12171c', fg='#e8eef0', font=('Microsoft YaHei UI', 22, 'bold')).pack(pady=(26, 12))
        self.label = tk.Label(self.root, text='检查设备和运行环境…', bg='#12171c', fg='#8d9aa4', wraplength=550, justify='left', font=('Microsoft YaHei UI', 11))
        self.label.pack(padx=25, pady=10)
        self.progress = ttk.Progressbar(self.root, mode='indeterminate')
        self.progress.pack(fill='x', padx=30, pady=12)
        buttons = tk.Frame(self.root, bg='#12171c')
        buttons.pack(pady=12)
        self.retry = ttk.Button(buttons, text='重新检查', command=self.start)
        self.retry.pack(side='left', padx=6)
        ttk.Button(buttons, text='修复设备配置', command=self.repair).pack(side='left', padx=6)
        ttk.Button(buttons, text='打开日志', command=lambda: os.startfile(str(LOGS))).pack(side='left', padx=6)
        self.root.after(100, self.poll)
        self.start()

    def check(self):
        output = RUNTIME / 'devices.json'
        output.unlink(missing_ok=True)
        script = ASSETS / 'device_setup.ps1'
        subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', str(script), '-Mode', 'Check', '-ResultPath', str(output)], creationflags=subprocess.CREATE_NO_WINDOW, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT, timeout=50)
        if not output.exists():
            raise RuntimeError('设备检查没有完成，请查看日志或点击“修复设备配置”。')
        return json.loads(output.read_text(encoding='utf-8-sig'))

    def start(self):
        if self.preparing or self.cancelled.is_set():
            return
        self.preparing = True
        self.retry.configure(state='disabled')
        self.progress.start()
        self.label.configure(text='正在检查 USBWLAN、USB-CAN 和专用网卡…')
        threading.Thread(target=self.prepare, daemon=True).start()

    def prepare(self):
        try:
            self.stop_child()
            status = self.check()
            if not status.get('network_ok'):
                raise RuntimeError('专用雷达网卡尚未配置。请点击“修复设备配置”，并允许 Windows 管理员确认。' + ('\n' + status['message'] if status.get('message') else ''))
            if status.get('usb_count') != 1:
                raise RuntimeError('请连接一只 USBWLAN（0CF3:1022），保持归 Windows 使用，随后点“重新检查”。')
            if not status.get('usb_ok'):
                raise RuntimeError('USBWLAN 驱动未就绪。请点击“修复设备配置”；若 Windows 报设备描述符失败，请重新插入设备。')
            if not status.get('can_ok'):
                raise RuntimeError('请连接一只 PCAN 兼容 USB-CAN（0C72:000C）。连接后点“重新检查”。')
            if self.cancelled.is_set():
                return
            self.messages.put(('progress', '设备已就绪，正在初始化无线链路…\n电机保持停止，打开面板后可手动启动。'))
            # A previous run can leave RAM firmware active. Reset only after taking the app mutex.
            subprocess.run(command('--reset'), creationflags=subprocess.CREATE_NO_WINDOW, timeout=12, check=True)
            if self.cancelled.wait(2):
                return
            (RUNTIME / 'stop').unlink(missing_ok=True)
            (RUNTIME / 'status.json').unlink(missing_ok=True)
            self.child = subprocess.Popen(command('--transport', status['guid'], str(os.getpid())), creationflags=subprocess.CREATE_NO_WINDOW)
            deadline = time.monotonic() + 40
            while time.monotonic() < deadline and not self.cancelled.wait(0.25):
                if self.child.poll() is not None:
                    raise RuntimeError('无线链路启动失败。请检查 USBWLAN 是否被其他程序占用；必要时重新插入后再试。详细信息已写入日志。')
                try:
                    state = json.loads((RUNTIME / 'status.json').read_text(encoding='utf-8'))
                except (OSError, ValueError):
                    continue
                if state.get('pid') == self.child.pid and state.get('state') == 'running' and 'tap_rx' in state:
                    self.messages.put(('ready', None))
                    return
                if state.get('state') == 'error':
                    raise RuntimeError('无线链路错误：' + state.get('error', 'unknown'))
            if not self.cancelled.is_set():
                raise RuntimeError('无线链路初始化超时，请重新插入 USBWLAN 后重试。')
        except Exception as exc:
            traceback.print_exc()
            self.stop_child()
            self.messages.put(('error', str(exc)))

    def repair(self):
        if self.preparing:
            return
        self.preparing = True
        self.progress.start()
        self.retry.configure(state='disabled')
        self.label.configure(text='正在修复设备配置，请允许 Windows 管理员确认。完成后自动重新检查。')
        def work():
            # PowerShell waits for the UAC child, retaining a real exit code.
            # Literal paths are single-quoted and escaped as PowerShell literals.
            quote = lambda value: "'" + str(value).replace("'", "''") + "'"
            result_path = RUNTIME / 'repair.json'
            result_path.unlink(missing_ok=True)
            args = subprocess.list2cmdline(['-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', str(ASSETS / 'device_setup.ps1'), '-Mode', 'Install', '-AppPath', sys.executable, '-ResultPath', str(result_path)])
            script = "$ErrorActionPreference='Stop'; try { $p=Start-Process powershell.exe -Verb RunAs -WindowStyle Hidden -ArgumentList " + quote(args) + " -Wait -PassThru; exit $p.ExitCode } catch { exit 5 }"
            try:
                finished = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script], creationflags=subprocess.CREATE_NO_WINDOW, timeout=180)
                result = json.loads(result_path.read_text(encoding='utf-8-sig')) if result_path.exists() else {}
                if finished.returncode == 3010:
                    raise RuntimeError('驱动已安装，需要重新启动 Windows，重启后再打开控制台。')
                if finished.returncode != 0 or not result.get('ok'):
                    raise RuntimeError('设备修复未完成：' + result.get('message', '管理员确认已取消或安装超时。'))
                self.messages.put(('check_again', None))
            except Exception as exc:
                traceback.print_exc()
                self.messages.put(('error', str(exc)))
        threading.Thread(target=work, daemon=True).start()

    def poll(self):
        if self.cancelled.is_set():
            return
        try:
            while True:
                kind, text = self.messages.get_nowait()
                if kind == 'progress':
                    self.label.configure(text=text)
                elif kind == 'check_again':
                    self.preparing = False
                    self.start()
                elif kind == 'error':
                    self.preparing = False
                    self.progress.stop()
                    self.retry.configure(state='normal')
                    self.label.configure(text=text)
                elif kind == 'ready':
                    from radar_control_panel import RadarControlPanel
                    for widget in self.root.winfo_children():
                        widget.destroy()
                    self.panel = RadarControlPanel(self.root)
                    self.backend_started = self.last_backend_progress = time.monotonic()
                    self.root.protocol('WM_DELETE_WINDOW', self.close)
                    self.preparing = False
                    self.root.after(1000, self.check_backend)
                    return
        except queue.Empty:
            pass
        self.root.after(150, self.poll)

    def check_backend(self):
        if self.cancelled.is_set():
            return
        if not (self.recovery_thread and self.recovery_thread.is_alive()):
            state = self.backend_state()
            now = time.monotonic()
            marker = (state.get('pid'), state.get('udp_rx', 0))
            if state and marker != self.last_backend_rx:
                self.last_backend_rx = marker
                self.last_backend_progress = now
            dead = self.child is not None and self.child.poll() is not None
            stalled = now - self.backend_started > 45 and now - self.last_backend_progress > 20
            if (dead or stalled) and self.recovery_attempts < 2:
                self.recovery_attempts += 1
                self.transport_message(f'连接中断，正在停转并恢复无线链路（{self.recovery_attempts}/2）…')
                self.recovery_thread = threading.Thread(target=self.recover_backend, daemon=True)
                self.recovery_thread.start()
            elif (dead or stalled) and self.recovery_attempts >= 2:
                with self.panel.telemetry.lock:
                    already_reported = bool(self.panel.telemetry.transport_error)
                if not already_reported:
                    if self.panel.client:
                        self.panel.client.request('stop')
                    self.transport_message('自动恢复未能保持连接。请关闭软件，给雷达断电 10 秒后重新打开；若 USBWLAN 仍报错，请重新插入。')
        self.root.after(1000, self.check_backend)

    def backend_state(self):
        try:
            state = json.loads((RUNTIME / 'status.json').read_text(encoding='utf-8'))
            if self.child and state.get('pid') == self.child.pid and time.time()-state.get('updated', 0) < 5:
                return state
        except (OSError, ValueError):
            pass
        return {}

    def transport_message(self, message):
        with self.panel.telemetry.lock:
            self.panel.telemetry.transport_error = message
        print('LINK_RECOVERY', message, flush=True)

    def recover_backend(self):
        try:
            if not self.panel.client:
                raise RuntimeError('控制通道尚未就绪')
            # Do not restart the AP until fresh CAN feedback confirms a stop.
            self.panel.client.request('stop')
            deadline = time.monotonic() + 12
            while not self.cancelled.wait(.2):
                with self.panel.telemetry.lock:
                    stopped = (not self.panel.telemetry.motor_running and self.panel.telemetry.actual_rpm == 0
                               and self.panel.telemetry.last_rpm_at > 0
                               and 0 <= time.monotonic()-self.panel.telemetry.last_rpm_at < 2.5)
                if stopped:
                    break
                if time.monotonic() >= deadline:
                    raise RuntimeError('未收到实时 0 RPM 确认，已保留停止请求；请检查 CAN')
            if self.cancelled.is_set():
                return
            self.stop_child()
            self.transport_message('电机已停止，正在重置 USBWLAN 并重建无线链路…')
            subprocess.run(command('--reset'), creationflags=subprocess.CREATE_NO_WINDOW, timeout=12, check=True)
            if self.cancelled.wait(2):
                return
            status = self.check()
            if not status.get('ok'):
                raise RuntimeError(status.get('message') or 'USBWLAN、CAN 或专用网卡未就绪')
            if self.cancelled.is_set():
                return
            (RUNTIME / 'stop').unlink(missing_ok=True)
            (RUNTIME / 'status.json').unlink(missing_ok=True)
            self.child = subprocess.Popen(command('--transport', status['guid'], str(os.getpid())), creationflags=subprocess.CREATE_NO_WINDOW)
            self.backend_started = self.last_backend_progress = time.monotonic()
            self.last_backend_rx = None
            deadline = time.monotonic() + 45
            initial_rx = None
            while not self.cancelled.wait(.5):
                if self.child.poll() is not None:
                    raise RuntimeError('USBWLAN 接收程序再次退出')
                state = self.backend_state()
                received = state.get('udp_rx', 0)
                if initial_rx is None and state:
                    initial_rx = received
                # An AP, association, or old telemetry alone is not a recovery.
                with self.panel.telemetry.lock:
                    fresh_radar = self.panel.telemetry.last_udp_at > self.backend_started
                if state.get('state') == 'running' and initial_rx is not None and received > initial_rx and fresh_radar:
                    self.last_backend_progress = time.monotonic()
                    self.transport_message('')
                    print('LINK_RECOVERED fresh radar UDP; motor remains stopped', flush=True)
                    return
                if time.monotonic() >= deadline:
                    raise RuntimeError('热点已重建，但未收到新的雷达数据')
        except Exception as exc:
            traceback.print_exc()
            if not self.cancelled.is_set():
                self.transport_message(f'无线恢复失败：{exc}。请关闭软件，给雷达断电 10 秒后重新打开；USBWLAN 报错时重新插入。')
                # No unattended reset loop after a failed recovery.
                self.recovery_attempts = 2

    def stop_child(self):
        child = self.child
        if child and child.poll() is None:
            (RUNTIME / 'stop').touch()
            try:
                child.wait(timeout=12)
            except subprocess.TimeoutExpired:
                child.terminate()
                child.wait(timeout=5)
        self.child = None

    def close(self):
        self.cancelled.set()
        if self.panel:
            self.panel.close()
        else:
            self.root.destroy()

    def run(self):
        try:
            self.root.mainloop()
        finally:
            self.cancelled.set()
            if self.recovery_thread:
                self.recovery_thread.join(timeout=70)
            self.stop_child()


def main():
    ctypes.windll.user32.SetProcessDPIAware()
    redirect_log('transport' if '--transport' in sys.argv else 'app')
    if len(sys.argv) > 1:
        if sys.argv[1] == '--self-test':
            self_test(sys.argv[2])
            return
        if sys.argv[1] == '--reset':
            import reset_winusb
            reset_winusb.main()
            return
        if sys.argv[1] == '--transport':
            guid, parent = sys.argv[2:4]
            threading.Thread(target=watch_parent, args=(int(parent),), daemon=True).start()
            import probe_winusb
            sys.argv = [sys.argv[0], '--boot', '--services', '--ap', '--serve', '--tap-guid', guid, '--tap-ip', '192.168.8.1', '--tap-direct']
            probe_winusb.main()
            return
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateMutexW.restype = wintypes.HANDLE
    kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    mutex = kernel.CreateMutexW(None, False, 'Local\\T40Radar-Desktop-0.1')
    if not mutex or ctypes.get_last_error() == 183:
        ctypes.windll.user32.MessageBoxW(None, '雷达控制台已经打开，请使用现有窗口。', 'T40 雷达控制台', 0x40)
        return
    try:
        Launcher().run()
    finally:
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle(mutex)


if __name__ == '__main__':
    try:
        main()
    except BaseException:
        traceback.print_exc()
        sys.exit(1)
