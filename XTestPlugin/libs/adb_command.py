#!/usr/bin/env python3
# -*- coding:utf-8 -*-
# __author__ = 'edsion'
import os
import platform
import subprocess
import logging

MODULE_NAME = 'adb'


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


class ADB:
    adb_path = ''
    sn = ''
    devices = {}

    def __init__(self, adb_path='', sn=None):
        if sn:
            self.sn = sn
        self.logger = logging.getLogger('XTestPlugin').getChild(MODULE_NAME)

        self.logger.info('Setup adb...')
        self.adb_path = adb_path
        self.setup_adb(adb_path)
        self.refresh_devices()
        self.logger.info('Done!')

    def setup_adb(self, adb_path=''):
        if ' -s ' in adb_path:
            adb_path = adb_path.split(' -s ')[0]
            self.logger.debug('clean sn')
        elif ' -s ' in self.adb_path:
            self.adb_path = self.adb_path.split(' -s ')[0]
            self.logger.debug('clean sn')

        def add_env_path(p):
            # path = os.getenv('PATH')
            # print(path)
            os.putenv('PATH', '{0}:{1}'.format(p, os.getenv('PATH')))

        # adb路径中含空格时，python的os.path模块都可以正确处理，但是subprocess的shell=True时，调用外部程序时空格后面的字符串会被分割为参数
        if os.path.isfile(adb_path) and os.path.exists(adb_path):
            dirname = os.path.dirname(adb_path)
            add_env_path(dirname)
            self.adb_path = adb_path.split(dirname)[-1]
            self.logger.debug('adb exists, find adb by args')
        elif os.path.isfile(self.adb_path) and os.path.exists(self.adb_path):
            dirname = os.path.dirname(self.adb_path)
            add_env_path(dirname)
            self.adb_path = self.adb_path.split(dirname)[-1]
            self.logger.debug('adb exists, find adb by self')
        else:
            system = platform.platform()
            self.logger.debug(system)
            if 'Darwin' in system:
                self.adb_path = 'adb'
                add_env_path(os.path.join(os.path.dirname(__file__), 'macOS'))
                # self.adb_path = os.path.join(os.path.dirname(__file__), 'macOS', 'adb')
            elif 'Windows' in system:
                self.adb_path = 'adb.exe'
                add_env_path(os.path.join(os.path.dirname(__file__), 'Windows'))
            else:
                self.logger.error('not support! ')
                raise OSError('not support! ')

        logging.debug(self.adb_path)
        return self.adb_path

    def cmd(self, command, time_out=10):
        p = subprocess.Popen('{adb_with_sn} {cmd}'.format(adb_with_sn=self.adb_path, cmd=command),
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=os.path.dirname(__file__),
                             universal_newlines=False, bufsize=1, shell=True)
        self.logger.debug('{adb} {cmd}'.format(adb=self.adb_path, cmd=command))
        try:
            # print('>pid:{0}, return code:{1}'.format(p.pid, p.returncode))
            res = p.communicate(timeout=time_out)[0]
        except (KeyboardInterrupt, subprocess.TimeoutExpired):
            self.logger.warning('cancel or timeout')
            p.terminate()  # 通过signal来处理退出逻辑
        else:
            if res:
                res = res.decode()
                if 'not found' in res and 'bin/sh:' in res:
                    self.logger.debug(res)
                    self.logger.warning('command:[{0}] not support! '.format(p.args))
                else:
                    return res

    def refresh_devices(self):
        res = self.cmd('devices', time_out=10)
        self.devices = {}
        for line in res.split('\n'):
            line = line.strip().split('\t')
            if len(line) == 2:
                self.devices[line[0]] = line[1]
            else:
                pass
        else:
            self.logger.debug(self.devices)
            return self.devices

    def select_device(self):
        # self.setup_adb()  #adb devices 命令会忽略-s参数，所以不需要在这里重新设置adb以达到清理参数的作用
        self.refresh_devices()

        if self.sn and len(self.sn) > 0:  # 设置了有效的sn时直接返回
            self.logger = logging.getLogger(self.sn)
            if self.devices[self.sn] == 'device':  # 设备在线时，设置logger和adb_path
                self.logger.debug('device state check: Pass!')
                self.adb_path = ' '.join([self.adb_path, '-s', self.sn])
                self.logger.debug(self.adb_path)
                return self.sn
            else:  # 设备掉线时，重设logger和adb_path
                self.logger.error('device state error')
                self.setup_adb(self.adb_path)
                return
        else:  # sn无效时
            self.logger.debug(self.devices)
            return

    def shell_pm_list_packages(self):
        res = self.cmd('shell "pm list packages"', time_out=5)
        packages_list = [i.strip().replace('package:', '') for i in res.split('\n') if len(i) > 0]
        self.logger.debug(packages_list)
        return packages_list

    def shell_ps(self):
        res = self.shell('ps', time_out=10)
        process_list = []
        if res:
            res = res.split('\n')
            if res[0].strip().split(' ')[-1].lower() != 'name':
                self.logger.warning('Something Unsupported!')
            process_list = [i.strip().split(' ')[-1] for i in res if len(i) > 0]
            self.logger.debug(process_list)
        return process_list

    def shell(self, command, time_out=10):
        return self.cmd('shell "{0}"'.format(command), time_out=time_out)

    def push(self, local_file, remote_file='/sdcard/'):
        assert os.path.exists(local_file)
        assert os.path.isfile(local_file)
        speed = 2 * 1024 * 1024  # usb传输速度，按照2M/s速度进行估算
        time_out = int(os.stat(local_file).st_size / speed) + 3
        res = self.cmd('push "{0}" "{1}"'.format(local_file, remote_file), time_out=time_out)
        self.logger.debug(res)
        if 'error:' in res:
            return False
        else:
            return True


if __name__ == '__main__':
    adb = ADB('/Users/edsion/android-sdk-macosx/platform-tools/adb')
    p = subprocess.check_output('which adb', shell=True)
    print(p)
    adb = ADB()
    p = subprocess.check_output('which adb', shell=True)
    print(p)
