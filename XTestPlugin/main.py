# -*- coding: utf8 -*-
import os
import re
import time
import subprocess
import threading
from multiprocessing.dummy import Pool
from multiprocessing.sharedctypes import Array
from subprocess import TimeoutExpired
import sublime
import sublime_plugin
from .errors import *

SETTINGS = sublime.load_settings('XTestPlugin.sublime-settings')
ADB = SETTINGS.get('adb')
SN = ''


# TODO:add logging file handler

def select_device(func):
    def wrapper(*args, **kwargs):
        global SN
        if len(SN) > 0:
            if SETTINGS.get('debug'):
                print('device:[{0}] selected!'.format(SN))
            if 'command' in kwargs:
                kwargs['command'] = '-s {0} {1}'.format(SN, kwargs['command'])
            else:
                args = list(args)
                args = tuple(['-s {0} {1}'.format(SN, args[0])] + args[1:])
        if SETTINGS.get('debug'):
            print("name:{0}, args:{1}, kwargs:{2}".format(func.__name__, args, kwargs))
        return func(*args, **kwargs)

    return wrapper


def init_adb():
    global ADB
    ADB = SETTINGS.get('adb')
    if os.path.isfile(ADB) and os.path.exists(ADB):
        print('adb exists!')
    else:
        platform = sublime.platform().lower()
        ADB = os.path.join(os.path.dirname(__file__), platform, 'adb')
    os.putenv('PATH', '{0}:{1}'.format(os.getenv('PATH'), os.path.dirname(ADB)))
    return ADB


def clean_adb_output(output_string):
    output = str(output_string)
    replace = [
        'WARNING: linker: app_process has text relocations. This is wasting memory and is a security risk. Please fix.',
    ]
    for i in replace:
        output = re.sub(i, '', output)
    return output


@select_device
def adb_cmd(command, time_out=10):
    p = subprocess.Popen('adb {0}'.format(command), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         cwd=os.path.dirname(__file__), universal_newlines=False, bufsize=1, shell=True)
    if SETTINGS.get('debug'):
        print(p.args)
    try:
        # print('>pid:{0}, return code:{1}'.format(p.pid, p.returncode))
        res = p.communicate(timeout=time_out)[0]
    except (KeyboardInterrupt, TimeoutExpired):
        print('>canceled or timeout')
        p.terminate()  # 通过signal来处理退出逻辑
    else:
        if res:
            return res.decode()


def adb_devices():
    res = adb_cmd('devices', time_out=10)
    devices = {}
    for line in res.split('\n'):
        line = line.strip().split('\t')
        if len(line) == 2:
            devices[line[0]] = line[1]
        else:
            pass
    # TODO:判断状态为device，offline的不记在内
    if len(devices) == 0:
        sublime.error_message(res)
        return None
    else:
        print(devices)
        return devices


def adb_shell_pm_list_packages():
    res = adb_cmd('shell "pm list packages"', time_out=5)
    # 按照换行符'\n'切割为列表，再使用strip()去掉可能存在的'\r'。可以避免不同平台换行不一致的问题
    return [i.strip().replace('package:', '') for i in res.split('\n')]


def package_is_install(package_name, packages=None):
    if not packages:
        packages = adb_shell_pm_list_packages()
    result = False
    for line in packages:
        if package_name in line:
            result = True
            break
        else:
            continue
    else:
        sublime.error_message('"{0}" not installed!'.format(package_name))
        print(packages)
    return result


def adb_shell_ps_process_is_running(proc):
    res = adb_cmd('shell ps', time_out=5)
    result = False
    if res:
        for line in res.split('\n'):
            line = line.strip()
            if proc in line:
                result = True
                break
    else:
        result = None
    return result


def adb_push(local_file, remote_file=None):
    assert os.path.exists(local_file)
    speed = 2 * 1024 * 1024  # usb传输速度，按照2M/s速度进行估算
    time_out = int(os.stat(local_file).st_size / speed) + 3
    if not remote_file:
        remote_file = '/sdcard/'
    return adb_cmd('push "{0}" "{1}"'.format(local_file, remote_file), time_out=time_out)


def list_dir(dir_path):
    assert os.path.exists(dir_path) and os.path.isdir(dir_path)
    res = []
    for i in os.listdir(dir_path):
        path = os.path.join(dir_path, i)
        if os.path.isfile(path):
            res.append(path)
        else:
            res += list_dir(path)
    return res


def push_files(file_list, remote_path=None):
    white_list = SETTINGS.get("files_white_list")
    black_list = SETTINGS.get("files_black_list")

    def filter_by_re(text, pattern_list):
        for pattern in pattern_list:
            p = re.compile(str(pattern))
            if p.search(text):
                return True
        else:
            return False

    white = filter(lambda x: filter_by_re(x, white_list), file_list)
    black = filter(lambda x: filter_by_re(x, black_list), file_list)
    files = set(file_list) - set(black) | set(white)
    #  使用线程池，提高效率
    # pool = Pool()
    # pool.map_async(lambda i: adb_push(local_file=i, remote_file=remote_path), files)
    # pool.close()
    # pool.join()
    # print('pool done')
    for i in files:
        adb_push(local_file=i, remote_file=remote_path)


def show_log_and_error(params):
    start = time.time()
    params.get("remote_path")
    remote_result_path = os.path.join(params.get("remote_path"), 'Result')
    logfile_last_line = None
    errorfile_last_line = None

    def print_current_lines_and_get_line_no(text, last_line=None, line_prefix=None):
        if text:
            if 'No such file or directory' in text and 'cat' in text:
                return None
            lines = text.split('\n')
            if lines[-1].strip() == '':
                lines = lines[:-1]
            if last_line:
                lines = lines[lines.index(last_line) + 1:]
            for line in lines:
                print('{prefix}{line}'.format(prefix=line_prefix, line=line.strip()))
                last_line = line
            return last_line
        else:
            return None

    print('waiting for start...')
    while time.time() - start < params.get('time_out'):
        if time.time() - start < 10:  # 留10秒延迟，给XTest/kat初始化（直接sleep会造成sublime阻塞）
            continue

        log_txt = adb_cmd('shell cat {0}'.format(os.path.join(remote_result_path, 'Log.txt')), time_out=10)
        logfile_last_line = print_current_lines_and_get_line_no(log_txt, logfile_last_line, '[Log.txt]')

        error_txt = adb_cmd('shell cat {0}'.format(os.path.join(remote_result_path, 'error.txt')), time_out=10)
        errorfile_last_line = print_current_lines_and_get_line_no(error_txt, errorfile_last_line, '[error.txt]')

        if not adb_shell_ps_process_is_running(params.get("package_name")):
            print('Main Process exited, Test End')
            print(threading.enumerate())
            break


def force_stop():
    adb_cmd('shell service call activity 79 s16 {0}'.format(SETTINGS.get('xtest').get('package_name')), time_out=10)
    adb_cmd('shell service call activity 79 s16 {0}'.format(SETTINGS.get('kat').get('package_name')), time_out=10)


class AutotestCommand(sublime_plugin.WindowCommand):
    devices = {}
    online_devices = []
    selected_device = ''

    def select_device(self, devices):
        self.devices = devices
        self.online_devices = [i for i in devices if 'device' in devices[i]]
        if len(devices) == 0:
            return
        elif len(devices) > 1:
            self.window.show_quick_panel(items=self.online_devices, on_select=self.device_selected,
                                         flags=sublime.KEEP_OPEN_ON_FOCUS_LOST)
        else:
            self.selected_device = list(devices)[0]
            global SN
            SN = self.selected_device
            self.load_settings()

    def device_selected(self, *args):
        index = args[0]
        self.selected_device = self.online_devices[index]
        global SN
        SN = self.selected_device
        self.load_settings()

    def run(self):
        print(self.__class__.__name__)
        self.window.set_sidebar_visible(True)  # 设置打开side bar
        self.window.set_status_bar_visible(True)  # 设置打开status bar
        self.window.status_message('[{0}]preparing...'.format(time.time()))
        init_adb()
        adb_cmd(command='kill-server', time_out=10)  # 【debug】清理进程，防止干扰本次测试。之后可能需要注释掉防止影响多设备运行
        devices = adb_devices()
        self.select_device(devices)

    def load_settings(self):
        # 读取配置
        if SETTINGS.get("is_xtest"):
            self.params = SETTINGS.get('xtest')
            self.run_test_command = 'shell "log i \'start\' && ' \
                                    'am instrument -e class {class_name} -w {package_name}/{activity} &&' \
                                    ' log i \'end\'"'
        else:
            self.params = SETTINGS.get('kat')
            self.run_test_command = 'shell "log i \'start\' ' \
                                    '&& am instrument -w {package_name}/{activity} &&' \
                                    ' log i \'end\' "'
        self.find_and_push_files()

    def find_and_push_files(self):
        # 确定文件（脚本）路径，并push到设备
        files_root_path = os.getcwd()
        current_file_path = self.window.active_view().file_name()
        if current_file_path:
            files_root_path = os.path.dirname(current_file_path)
        else:  # 如果未打开任何文件（无任何文件在编辑状态）
            if len(self.window.folders()) > 1:
                sublime.error_message(too_many_files_or_folders)
            elif len(self.window.folders()) < 1:
                sublime.error_message(no_file_or_folder)
            else:
                files_root_path = self.window.folders()[0]  # 只有一个文件夹的情况
        files = list_dir(files_root_path)
        push_files(file_list=files, remote_path=self.params.get('remote_path'))
        self.check_packages()

    def check_packages(self):
        installed_packages = adb_shell_pm_list_packages()  # 获取设备中已安装app的列表
        if not package_is_install(self.params.get('package_name'), installed_packages):  # 检查XTest/KAT是否安装
            return

        # 根据Parameter.lua中的包名，判断apk是否安装
        parameter_lua_path = self.params.get('remote_path')
        if parameter_lua_path.endswith('/'):
            parameter_lua = adb_cmd('shell cat {0}Parameter.lua'.format(parameter_lua_path))
        else:
            parameter_lua = adb_cmd('shell cat {0}/Parameter.lua'.format(parameter_lua_path))
        app_package_name = None
        for line in parameter_lua.split('\n'):
            res = re.search('^\s*PackageName\s*=\s*[\'"](\S+)[\'"].*', line, re.IGNORECASE)
            if res:
                app_package_name = res.groups()[0]
                break
        if not package_is_install(app_package_name, installed_packages):
            return
        self.start_test()

    def start_test(self):
        force_stop()  # 可以同时杀掉XTest/kat的进程（仅启动app但未运行自动化测试也会被kill），这样后面才能根据ps结果判断是否在运行

        # 启动脚本
        run_test_command = self.run_test_command.format(class_name=self.params.get("class"),
                                                        package_name=self.params.get("package_name"),
                                                        activity=self.params.get("activity"), )
        run_test = threading.Thread(target=adb_cmd,
                                    kwargs={'command': run_test_command, 'time_out': self.params.get('time_out')},
                                    daemon=True)
        run_test.start()

        # 实时显示log和error
        cat_log = threading.Thread(target=show_log_and_error, args=(self.params,), daemon=True)
        cat_log.start()


class DoctorCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        print(self.__class__.__name__)
        print("sublime version:{0}, sublime channel:{1}".format(sublime.version(), sublime.channel()))
        print("Platform:{0}\nArch:{1}\n".format(sublime.platform(), sublime.arch()))
        # TODO:从packages.json读取版本号
