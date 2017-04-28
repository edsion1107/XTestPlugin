# -*- coding: utf8 -*-
import os
import re
import time
import subprocess
import threading
from subprocess import TimeoutExpired
import sublime
import sublime_plugin
from .errors import *

SETTINGS = sublime.load_settings('XTestPlugin.sublime-settings')
ADB = SETTINGS.get('adb')


# TODO:add logging file handler

def log(func):
    def wrapper(*args, **kwargs):
        print("name:{0}, args:{1}, kwargs:{2}".format(func.__name__, args, kwargs))
        return func(*args, **kwargs)

    return wrapper


def init_adb():
    global ADB
    ADB = SETTINGS.get('adb')
    if os.path.isfile(ADB) and os.path.exists(ADB):
        print('adb exists!')
    else:
        platform = sublime.platform()
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


def adb_command(command, timeout=5):
    cmd = 'adb ' + command
    print("\tadb command:{0}\n\ttimeout:{1}".format(command, timeout))
    return subprocess.check_output(args=cmd, stderr=subprocess.STDOUT, universal_newlines=True,
                                   timeout=timeout, shell=True)


def adb_cmd(command, time_out=10):
    p = subprocess.Popen('adb {0}'.format(command), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         cwd=os.path.dirname(__file__), universal_newlines=False, bufsize=1, shell=True)
    # print(p.args)
    try:
        # print('>pid:{0}, return code:{1}'.format(p.pid, p.returncode))
        res = p.communicate(timeout=time_out)[0]
    except (KeyboardInterrupt, TimeoutExpired):
        print('>canceled or timeout')
        p.terminate()  # 通过signal来处理退出逻辑
    else:
        if res:
            return res.decode()
            # finally:
            #     print('>pid:{pid}, return_code:{return_code}'.format(pid=p.pid, return_code=p.returncode))


def adb_devices():
    # adb_command('start-server')
    # stdout = adb_command('devices')
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


def adb_shell_package_is_install(package_name):
    # stdout = adb_command('shell pm list packages')
    res = adb_cmd('shell "pm list packages"', time_out=5)
    # 按照换行符'\n'切割为列表，再使用strip()去掉可能存在的'\r'。可以避免不同平台换行不一致的问题
    result = False
    for line in res.split('\n'):
        line = line.strip().replace('package:', '')
        if package_name in line:
            result = True
            break
        else:
            continue
    else:
        sublime.error_message('"{0}" not installed!'.format(package_name))
        print(res)
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
    # TODO:timeout按照（实测000）2M/s的速度计算
    assert os.path.exists(local_file)
    speed = 2 * 1024 * 1024  # usb传输速度，默认按照usb2.0计算，实测2M/s【另外可参考：https://www.zhihu.com/question/20186057】
    time_out = int(os.stat(local_file).st_size / speed) + 3
    if not remote_file:
        remote_file = '/sdcard/'
    # return adb_command('push "{0}" "{1}"'.format(local_file, remote_file), timeout=time_out)
    return adb_cmd('push "{0}" "{1}"'.format(local_file, remote_file), time_out=time_out)


def multiple_adb():
    # TODO：多个设备时需要选择
    pass


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

    # TODO：可以改为进程池，看能否提高性能
    for i in files:
        adb_push(i, remote_path)


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
    # adb_command('shell service call activity 79 s16 {0}'.format(SETTINGS.get('xtest').get('package_name')))
    adb_cmd('shell service call activity 79 s16 {0}'.format(SETTINGS.get('xtest').get('package_name')), time_out=10)
    # adb_command('shell service call activity 79 s16 {0}'.format(SETTINGS.get('kat').get('package_name')))
    adb_cmd('shell service call activity 79 s16 {0}'.format(SETTINGS.get('kat').get('package_name')), time_out=10)


class ExampleCommand(sublime_plugin.WindowCommand):
    # TODO：如果执行时，缓冲区更改未保存，则给出提示
    def run(self):
        print(self.__class__.__name__)
        self.window.set_sidebar_visible(True)  # 设置打开sidebar
        init_adb()
        adb_cmd(command='kill-server', time_out=10)  # 【debug】清理进程，防止干扰本次测试。之后可能需要注释掉防止影响多设备运行
        if adb_devices() is None:  # 检查是否有设备连接
            return
        if SETTINGS.get("is_xtest"):
            params = SETTINGS.get('xtest')
            command = 'shell "log i \'start\' && am instrument -e class {class_name} -w {package_name}/{activity}"'
        else:
            params = SETTINGS.get('kat')
            command = 'shell "log i \'start\' && am instrument -w {package_name}/{activity}"'

        if not adb_shell_package_is_install(params.get('package_name')):  # 检查XTest是否安装
            return

        # 确定文件（脚本）路径
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
        # print(files_root_path)
        files = list_dir(files_root_path)
        push_files(file_list=files, remote_path=params.get('remote_path'))

        # TODO: 根据paramter.lua中的包名，判断apk是否安装
        force_stop()  # 可以同时杀掉XTest/kat的进程（仅启动app但未运行自动化测试也会被kill），这样后面才能根据ps结果判断是否在运行

        command = command.format(class_name=params.get("class"), package_name=params.get("package_name"),
                                 activity=params.get("activity"), )

        run_test = threading.Thread(target=adb_cmd, kwargs={'command': command, 'time_out': params.get('time_out')},
                                    daemon=True)
        run_test.start()
        cat_log = threading.Thread(target=show_log_and_error, args=(params,), daemon=True)
        cat_log.start()


class DoctorCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        print(self.__class__.__name__)
        print("sublime version:{0}, sublime channel:{1}".format(sublime.version(), sublime.channel()))
        print("Platform:{0}\nArch:{1}\n".format(sublime.platform(), sublime.arch()))
        # TODO:从packages.json读取版本号
