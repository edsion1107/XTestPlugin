# -*- coding: utf8 -*-
import os
import re
import io
import time
import signal
import subprocess
from tempfile import NamedTemporaryFile
from subprocess import TimeoutExpired
from multiprocessing import Process
from multiprocessing.sharedctypes import Array
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


def adb_cmd(command, time_out=10, is_daemon=False):
    default_temp_file = 'temp.txt'
    if is_daemon:
        output = NamedTemporaryFile()
    else:
        output = subprocess.PIPE

    def run():
        p = subprocess.Popen('adb {0}'.format(command), stdout=output, stderr=subprocess.STDOUT,
                             cwd=os.path.dirname(__file__), universal_newlines=False, bufsize=1, shell=True)
        print(p.args)

        def handler(sig, frame):
            print('>Got signal: ', sig)
            p.terminate()

        try:
            signal.signal(signal.SIGTERM, handler)
            print('>pid:{0}, return code:{1}'.format(p.pid, p.returncode))
            if is_daemon:
                p.wait(timeout=time_out)
            else:
                res = p.communicate(timeout=time_out)[0]
                with open(default_temp_file, 'wb') as f:
                    f.write(res)
        except (KeyboardInterrupt, TimeoutExpired):
            print('>canceled or timeout')
            p.terminate()  # 通过signal来处理退出逻辑
        finally:
            print('>>>pid:{0}, return code:{1}'.format(p.pid, p.returncode))

    t = Process(target=run, daemon=is_daemon)
    try:
        t.start()
        print('name:{0}, pid:{1}, is alive:{2}'.format(t.name, t.pid, t.is_alive()))
        if is_daemon:
            pass
        else:
            t.join(time_out)
    except KeyboardInterrupt:
        print('Canceled!')
        t.terminate()
    finally:
        print('name:{0}, pid:{1}, is alive:{2}'.format(t.name, t.pid, t.is_alive()))
        if is_daemon:
            return output.name
        else:
            return default_temp_file


def adb_devices():
    # adb_command('start-server')
    # stdout = adb_command('devices')
    res = adb_cmd('devices', time_out=10, is_daemon=False)
    devices = {}
    with open(res, 'r') as f:
        for line in f:
            line = line.strip().split('\t')
            if len(line) == 2:
                devices[line[0]] = line[1]
            else:
                pass
        # TODO:判断状态为device，offline的不记在内
        if len(devices) == 0:
            sublime.error_message(f.read())
            return None
        else:
            print(devices)
            return devices


def adb_shell_package_is_install(package_name):
    # stdout = adb_command('shell pm list packages')
    res = adb_cmd('shell "pm list packages"', time_out=5, is_daemon=False)
    # 按照换行符'\n'切割为列表，再使用strip()去掉可能存在的'\r'
    result = False
    with open(res, 'r') as f:
        for line in f:
            line = line.strip().replace('package:', '')
            if package_name in line:
                result = True
                break
            else:
                continue
        else:
            sublime.error_message('"{0}" not installed!'.format(package_name))
            print(f.read())
    return result


def adb_shell_ps_process_is_running(proc):
    stdout = adb_cmd('shell ps', time_out=5, is_daemon=False).decode()
    process = [i for i in stdout.split('\n') if proc in i]
    if len(process) > 0:
        return True
    else:
        return False


def adb_push(local_file, remote_file=None):
    # TODO:timeout按照（实测000）2M/s的速度计算
    assert os.path.exists(local_file)
    speed = 2 * 1024 * 1024  # usb传输速度，默认按照usb2.0计算，实测2M/s【另外可参考：https://www.zhihu.com/question/20186057】
    time_out = int(os.stat(local_file).st_size / speed) + 3
    if not remote_file:
        remote_file = '/sdcard/'
    # return adb_command('push "{0}" "{1}"'.format(local_file, remote_file), timeout=time_out)
    return adb_cmd('push "{0}" "{1}"'.format(local_file, remote_file), time_out=time_out, is_daemon=False)


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

    # TODO：改为进程池
    for i in files:
        print(adb_push(i, remote_path))


def force_stop():
    # adb_command('shell service call activity 79 s16 {0}'.format(SETTINGS.get('xtest').get('package_name')))
    adb_cmd('shell service call activity 79 s16 {0}'.format(SETTINGS.get('xtest').get('package_name')), time_out=10,
            is_daemon=False)
    # adb_command('shell service call activity 79 s16 {0}'.format(SETTINGS.get('kat').get('package_name')))
    adb_cmd('shell service call activity 79 s16 {0}'.format(SETTINGS.get('kat').get('package_name')), time_out=10,
            is_daemon=False)


class ExampleCommand(sublime_plugin.WindowCommand):
    # TODO：如果执行时，缓冲区更改未保存，则给出提示
    def run(self):
        print(self.__class__.__name__)
        self.window.set_sidebar_visible(True)  # 设置打开sidebar
        init_adb()
        adb_cmd(command='kill-server', time_out=10, is_daemon=False)  # 【debug】清理进程，防止干扰本次测试。之后可能需要注释掉防止影响多设备运行
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
        force_stop()
        print(adb_shell_ps_process_is_running(params.get("package_name")))
        command = command.format(class_name=params.get("class"), package_name=params.get("package_name"),
                                 activity=params.get("activity"), )
        # run_command = threading.Thread(target=adb_command,
        #                                kwargs={'command': command, 'timeout': params.get('time_out')})

        # run_command = Process(target=adb_command, kwargs={'command': command, 'timeout': params.get('time_out')},
        #                       daemon=True)
        # print('start running')
        # run_command.start()

        # run_test_proc, run_test_stdout = adb_cmd(command=command, time_out=params.get('time_out'), is_daemon=True)
        # TODO : 检测到kat退出，则强制结束run_test进程
        # TODO： 检测xtest/kat是否运行
        # cat_log = Process(target=adb_command, kwargs={'command': 'shell tail -f /sdcard/kat/Result/Log.txt',
        #                                               'timeout': params.get('time_out')},daemon=False)
        # cat_log.start()
        # adb_shell_tail('/sdcard/kat/Result/Log.txt', timeout=params.get('time_out'))
        # adb_cmd(command='shell "tail -f /sdcard/kat/Result/Log.txt"', time_out=params.get('time_out'),
        #         is_daemon=True, pre_sleep=10)
        # start = time.time()
        # params.get("remote_path")
        # remote_result_path = os.path.join(params.get("remote_path"), 'Result')
        # logfile = adb_cmd('shell cat '.format(os.path.join(remote_result_path, 'Log.txt'))).decode()
        # logfile_pos = 0
        # error_file = adb_cmd('shell cat '.format(os.path.join(remote_result_path, 'Log.txt'))).decode()
        # error_file_pos = 0
        # while time.time() - start < params.get('time_out'):
        #     with open(logfile, 'r') as log_f:
        #         log_f.seek(logfile_pos, 0)
        #         for line in log_f:
        #             print('[Log.txt]{0}'.format(line))
        #         else:
        #             logfile_pos = log_f.tell()
        #     with open(error_file, 'r') as error_f:
        #         error_f.seek(error_file_pos, 0)
        #         for line in error_f:
        #             print('[error.txt]{0}'.format(line))
        #         else:
        #             error_file_pos = error_f.tell()


class DoctorCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        print(self.__class__.__name__)
        print("sublime version:{0}, sublime channel:{1}".format(sublime.version(), sublime.channel()))
        print("Platform:{0}\nArch:{1}\n".format(sublime.platform(), sublime.arch()))
        # TODO:从packages.json读取版本号
