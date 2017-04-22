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
        return ADB
    else:
        platform = sublime.platform()
        ADB = os.path.join(os.path.dirname(__file__), platform, 'adb')
        return ADB
        # TODO : 根据系统，使用自带adb。完成后，将设置中adb置为None


def clean_adb_output(output_string):
    output = str(output_string)
    replace = [
        'WARNING: linker: app_process has text relocations. This is wasting memory and is a security risk. Please fix.',
    ]
    for i in replace:
        output = re.sub(i, '', output)
    return output


@log
def adb_command(command, sn=None, timeout=5):  # timeout设置较短的默认值，是为了保证尽快给用户一个反馈，在使用具体命令时可以酌情处理
    global ADB
    setup_adb()
    if sn:
        sn = " -s {0}".format(sn)
    else:
        sn = ''
    cmd = '''"{0}" {1} {2}'''.format(ADB, sn, command)
    print('cmd:\n{0},\ntimeout:{1}'.format(cmd, timeout))
    # 注意adb路径可能存在空格
    p = subprocess.Popen(args=cmd, stderr=subprocess.PIPE,
                         stdout=subprocess.PIPE, shell=True, bufsize=1, env={'ANDROID_HOME': os.path.dirname(ADB)})
    return_code = None
    try:
        return_code = p.wait(timeout)
    except subprocess.TimeoutExpired:
        p.terminate()
        print(traceback.print_exc())
        return_code = 1
    finally:
        print('return code: {0}, pid:{1}'.format(return_code, p.pid))
        stdout = p.stdout.read().decode()
        stderr = p.stderr.read().decode()
        try:  # 防止僵尸进程
            p.kill()
        except ProcessLookupError:
            pass
        return return_code, clean_adb_output(stdout), clean_adb_output(stderr)


def adb_devices():
    adb_command('start-server')
    _, stdout, stderr = adb_command('devices')
    devices = {}
    if 'List of devices attached' in stdout:
        devices_str = stdout
    else:
        devices_str = stderr
    for line in devices_str.split('\n'):
        if '\t' in line:
            k, v = line.split('\t')
            devices[k] = v

    if len(devices) == 0:
        sublime.error_message(stdout)
        return None
    else:
        return devices


def adb_shell(command, timeout=3600):
    return adb_command('shell "{0}"'.format(command), timeout=timeout)


def adb_shell_package_is_install(package_name):
    _, stdout, stderr = adb_shell('pm list packages')
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
        remote_file = SETTINGS.get('xtest_remote')
    return_code, stdout, stderr = adb_command('push "{0}" "{1}"'.format(local_file, remote_file), timeout=time_out)
    if return_code == 0:
        return True
    elif return_code == 1:
        return False
    else:
        return return_code


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
    success = list(filter(lambda x: adb_push(x, remote_path) is True, files))
    if len(success) != len(files):
        print('Warning:{0} of {1} pushed'.format(len(success), len(files)))


def start_xtest():
    _, stdout, stderr = adb_shell(
        'log -p i -t \"XTest XTest start!\" && am instrument -e class {0} -w {1}/{2}'.format(
            SETTINGS.get("xtest_replay_class"), SETTINGS.get("xtest_package_name"),
            SETTINGS.get("xtest_replay_activity"),
            timeout=SETTINGS.get("xtest_timeout"))
    )


def stop_xtest():
    pass


class ExampleCommand(sublime_plugin.WindowCommand):
    # TODO：如果执行时，缓冲区更改未保存，则给出提示
    def run(self):
        print(self.__class__.__name__)
        self.window.set_sidebar_visible(True)  # 设置打开sidebar

        if adb_devices() is None:  # 检查是否有设备连接
            return
        if not adb_shell_package_is_install(SETTINGS.get('xtest_package_name')):  # 检查XTest是否安装
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
        push_files(file_list=files)

        # TODO: 根据paramer.lua中的包名，判断apk是否安装
        stop_xtest()
        start_xtest()
        # threading.Thread(target=start_xtest, name=start_xtest.__name__)
        # TODO： showlog方案改进：解析Main.lua中最后一个脚本，然后找到最后结束的关键字。通过tail -f 来实时显示日志


class DoctorCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        print(self.__class__.__name__)
        print("sublime version:{0}, sublime channel:{1}".format(sublime.version(), sublime.channel()))
        print("Platform:{0}\nArch:{1}\n".format(sublime.platform(), sublime.arch()))
        # TODO:从packages.json读取版本号
