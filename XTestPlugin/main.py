# -*- coding: utf8 -*-
import sublime
import sublime_plugin
import logging
import sys

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler())

SETTINGS = sublime.load_settings('XTestPlugin.sublime-settings')


class ExampleCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        print(SETTINGS.get('default'))


class DoctorCommand(sublime_plugin.TextCommand):
    def run(self, edit):
        logger.info(1)
        # logger.info(SETTINGS.get('adb'))
