# -*- coding: utf8 -*-
import os
import re
import sublime
import sublime_plugin
import subprocess
import traceback
import threading
from .errors import *

SETTINGS = sublime.load_settings('XTestPlugin.sublime-settings')
ADB = SETTINGS.get('adb')


# TODO:add logging file handler

def log(func):
    def wrapper(*args, **kwargs):
        print("name:{0}, args:{1}, kwargs:{2}".format(func.__name__, args, kwargs))
        return func(*args, **kwargs)

    return wrapper


def setup_adb():
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
    return subprocess.check_output(args=cmd, stderr=subprocess.PIPE, universal_newlines=True,
                                   timeout=timeout, shell=True)


def adb_devices():
    # adb_command('start-server')
    stdout = adb_command('devices')
    devices = {}
    if 'windows' in sublime.platform().lower():
        newline = '\r\n'
    else:
        newline = '\n'
    for line in stdout.split(newline):
        if '\t' in line:
            k, v = line.split('\t')
            devices[k] = v
    # TODO:判断状态为device，offline的不记在内
    if len(devices) == 0:
        sublime.error_message(stdout)
        return None
    else:
        print(devices)
        return devices


def adb_shell_package_is_install(package_name):
    stdout = adb_command('shell pm list packages')
    packages = [i.replace('package:', '') for i in stdout.split('\n') if len(i) > 0]
    if len(packages) == 1:
        packages = [i.replace('package:', '') for i in stdout.split('\r\n') if len(i) > 0]

    if package_name in packages:
        return True
    else:
        print(packages)
        sublime.error_message('"{0}" not installed!'.format(package_name))
        return False


def adb_push(local_file, remote_file=None):
    # TODO:timeout按照（实测000）2M/s的速度计算
    assert os.path.exists(local_file)
    speed = 2 * 1024 * 1024  # usb传输速度，默认按照usb2.0计算，实测2M/s【另外可参考：https://www.zhihu.com/question/20186057】
    time_out = int(os.stat(local_file).st_size / speed) + 1
    if not remote_file:
        remote_file = '/sdcard/'
    return adb_command('push "{0}" "{1}"'.format(local_file, remote_file), timeout=time_out)


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
    for i in files:
        adb_push(i, remote_path)


def force_stop():
    adb_command('shell service call activity 79 s16 {0}'.format(SETTINGS.get('xtest').get('package_name')))
    adb_command('shell service call activity 79 s16 {0}'.format(SETTINGS.get('kat').get('package_name')))


class ExampleCommand(sublime_plugin.WindowCommand):
    # TODO：如果执行时，缓冲区更改未保存，则给出提示
    def run(self):
        print(self.__class__.__name__)
        self.window.set_sidebar_visible(True)  # 设置打开sidebar
        setup_adb()
        if adb_devices() is None:  # 检查是否有设备连接
            return
        if SETTINGS.get("is_xtest"):
            params = SETTINGS.get('xtest')
        else:
            params = SETTINGS.get('kat')

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
        #
        # TODO: 根据paramer.lua中的包名，判断apk是否安装
        force_stop()
        # start_xtest()
        cmd = 'shell "log -i \'start\' && am instrument -e class com.kunpeng.kat.base.TestMainInstrumentation -w com.tencent.utest.recorder/com.kunpeng.kat.base.KatInstrumentationTestRunner"'
        xtest = threading.Thread(target=adb_command, args=(cmd, 3600))
        # xtest.daemon = True
        xtest.setDaemon(True)
        xtest.start()

        # TODO： showlog方案改进：通过tail -f 来实时显示日志.检测xtest/kat是否运行


class DoctorCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        print(self.__class__.__name__)
        print("sublime version:{0}, sublime channel:{1}".format(sublime.version(), sublime.channel()))
        print("Platform:{0}\nArch:{1}\n".format(sublime.platform(), sublime.arch()))
        # TODO:从packages.json读取版本号
