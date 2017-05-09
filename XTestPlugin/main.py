# -*- coding: utf8 -*-
import os
import re
import threading
import time
import logging

import sublime
import sublime_plugin
from XTestPlugin.libs.errors import *
from XTestPlugin.libs.adb_command import ADB, list_dir
from logging import StreamHandler
from logging.handlers import RotatingFileHandler

SETTINGS_NAME = 'XTestPlugin.sublime-settings'
MODULE_NAME = 'XTestPlugin'

logger = logging.getLogger(MODULE_NAME)
logging.root.setLevel(logging.DEBUG)


def plugin_loaded():
    for i in logging.root.handlers:
        logging.root.removeHandler(i)
    fmt = logging.Formatter("%(asctime)s %(levelname)-5s %(name)20s:%(lineno)-4s %(message)s", "%H:%M:%S")
    sh = StreamHandler()
    sh.setFormatter(fmt)
    sh.setLevel(logging.INFO)

    fmt = logging.Formatter("%(asctime)s %(levelname)-6s - %(name)20s:%(lineno)-5s - %(message)s", "%Y%m%d-%H:%M:%S")
    fh = RotatingFileHandler(filename=os.path.join(os.path.dirname(__file__), 'XTestPlugin.log'), maxBytes=1024 * 1024,
                             backupCount=5, encoding='utf-8')
    fh.setFormatter(fmt)
    fh.setLevel(logging.DEBUG)
    logging.root.addHandler(sh)
    logging.root.addHandler(fh)


# TODO: 需要增加log控制的相关命令行（重置、打开logfile、开启/关闭handler、调整日志级别）


class AutotestCommand(sublime_plugin.WindowCommand):
    adb = None
    run_test_command = ''
    params = {}

    def run(self):
        self.window.set_sidebar_visible(True)  # 设置打开side bar
        self.window.set_status_bar_visible(True)  # 设置打开status bar
        self.window.status_message('[{0}]preparing...'.format(time.time()))
        logger.info('Init...')
        self.adb = ADB(adb_path=sublime.load_settings(SETTINGS_NAME).get("adb"))
        # self.adb.cmd(command='kill-server', time_out=10)  # 【debug】清理进程，防止干扰本次测试。之后可能需要注释掉防止影响多设备运行
        self.select_device_popup()

    def select_device_popup(self):
        def callback(index):
            self.adb.sn = online_devices[index]
            if self.adb.select_device():
                self.load_settings()
            else:
                self.adb.logger.error('device init error')

        online_devices = [i for i in self.adb.devices if 'device' in self.adb.devices.get(i)]
        if len(online_devices) == 0:
            logger.error('no device connect')
        elif len(online_devices) == 1:
            self.adb.sn = online_devices[0]
            self.adb.select_device()
            self.load_settings()
        else:
            self.window.show_quick_panel(items=online_devices, on_select=callback,
                                         flags=sublime.KEEP_OPEN_ON_FOCUS_LOST)

    def load_settings(self):
        # 读取配置
        if sublime.load_settings(SETTINGS_NAME).get("is_xtest"):
            self.params = sublime.load_settings(SETTINGS_NAME).get('xtest')
            run_test_command = "log i 'start' && am instrument -e class {class_name}" \
                               " -w {package_name}/{activity} && log i 'end'"
        else:
            self.params = sublime.load_settings(SETTINGS_NAME).get('kat')
            run_test_command = "log i 'start' && am instrument " \
                               "-w {package_name}/{activity} & log i 'end' "
        self.run_test_command = run_test_command.format(class_name=self.params.get("class"),
                                                        package_name=self.params.get("package_name"),
                                                        activity=self.params.get("activity"), )
        self.adb.logger.debug(self.run_test_command)
        if self.params.get('cleanup_every_time'):
            self.adb.logger.info('Clean up...')
            self.adb.logger.debug(self.adb.adb_path)
            self.adb.shell('rm -rf {0}'.format(self.params.get('remote_path')))
            self.adb.shell('mkdir -p {0}'.format(self.params.get('remote_path')))
            self.adb.logger.info('Done')

        if self.params.get('restart_adb'):
            logger.info('restarting adb...')
            self.adb.cmd('kill-server')
            self.adb.cmd('start-server')
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

        white_list = sublime.load_settings(SETTINGS_NAME).get("files_white_list")
        black_list = sublime.load_settings(SETTINGS_NAME).get("files_black_list")

        def filter_by_re(text, pattern_list):
            for pattern in pattern_list:
                p = re.compile(str(pattern))
                if p.search(text):
                    return True
            else:
                return False

        white = filter(lambda x: filter_by_re(x, white_list), files)
        black = filter(lambda x: filter_by_re(x, black_list), files)
        files = set(files) - set(black) | set(white)  # 这里确定了白名单优先级更高
        self.adb.logger.info('pushing files...')
        push_result = filter(lambda x: self.adb.push(local_file=x, remote_file=self.params.get('remote_path')), files)
        push_failed = len(list(files)) - len(list(push_result))
        if push_failed != 0:
            self.adb.logger.warning('{0} of {1} file push failed!'.format(push_failed, len(files)))
        else:
            self.check_packages()

    def check_packages(self):

        def package_not_install():
            self.adb.logger.error('Package Not Installed')
            sublime.error_message('"{0}" not installed'.format(self.params.get('package_name')))
            return

        installed_packages = self.adb.shell_pm_list_packages()  # 获取设备中已安装app的列表
        if self.params.get('package_name') not in installed_packages:  # 检查XTest/KAT是否安装
            package_not_install()

        # 根据Parameter.lua中的包名，判断apk是否安装
        parameter_lua_path = os.path.join(self.params.get('remote_path'), 'Parameter.lua')
        parameter_lua = self.adb.shell('cat {0}'.format(parameter_lua_path))
        if 'No such file or directory' in parameter_lua:
            sublime.error_message(can_not_found_scripts)
            return
        app_package_name = None
        for line in parameter_lua.split('\n'):
            res = re.search('^\s*PackageName\s*=\s*[\'"](\S+)[\'"].*', line, re.IGNORECASE)
            if res:
                app_package_name = res.groups()[0]
                break
        else:  # 找不到包名时，可能是设备中不存在文件
            sublime.error_message(can_not_found_scripts)
        if app_package_name:
            if app_package_name not in installed_packages:
                package_not_install()
            else:
                self.start_test()

    def force_stop(self):
        logger.info('Force stop processes.')
        self.adb.shell('service call activity 79 s16 {0}'.format(
            sublime.load_settings(SETTINGS_NAME).get('xtest').get('package_name')), time_out=10)
        self.adb.shell('service call activity 79 s16 {0}'.format(
            sublime.load_settings(SETTINGS_NAME).get('kat').get('package_name')), time_out=10)

    def show_log_and_error(self):
        start = time.time()
        remote_result_path = os.path.join(self.params.get("remote_path"), 'Result')
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
                    self.adb.logger.info('{prefix}{line}'.format(prefix=line_prefix, line=line.strip()))
                    last_line = line
                return last_line
            else:
                return None

        self.adb.logger.info('waiting for start...')
        while time.time() - start < self.params.get('time_out'):
            if time.time() - start < self.params.get('waiting_for_start'):  # 预留给XTest/kat初始化的时间（直接sleep会造成sublime阻塞）
                continue

            log_txt = self.adb.shell('cat {0}'.format(os.path.join(remote_result_path, 'Log.txt')), time_out=10)
            logfile_last_line = print_current_lines_and_get_line_no(log_txt, logfile_last_line, '[Log.txt]')

            error_txt = self.adb.shell('cat {0}'.format(os.path.join(remote_result_path, 'error.txt')), time_out=10)
            errorfile_last_line = print_current_lines_and_get_line_no(error_txt, errorfile_last_line, '[error.txt]')

            if self.params.get("package_name") not in self.adb.shell_ps():
                self.adb.logger.info('Main Process exited, Test End\n\n\n\n\n')
                self.adb.logger.debug(threading.enumerate())
                break

    def start_test(self):
        self.force_stop()  # 可以同时杀掉XTest/kat的进程（仅启动app但未运行自动化测试也会被kill），这样后面才能根据ps结果判断是否在运行

        # 启动脚本
        self.adb.logger.info('\ttesting...')
        run_test = threading.Thread(target=self.adb.shell,
                                    kwargs={'command': self.run_test_command, 'time_out': self.params.get('time_out')},
                                    daemon=True)
        run_test.start()

        # 实时显示log和error
        cat_log = threading.Thread(target=self.show_log_and_error, daemon=True)
        cat_log.start()


class DoctorCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        print(self.__class__.__name__)
        print("sublime version:{0}, sublime channel:{1}".format(sublime.version(), sublime.channel()))
        print("Platform:{0}\nArch:{1}\n".format(sublime.platform(), sublime.arch()))
        # TODO:从packages.json读取版本号
