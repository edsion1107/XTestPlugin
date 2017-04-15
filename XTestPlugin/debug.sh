#!/usr/bin/env bash
# pycharm下"一键调试"脚本

# 同步文件变更
rsync -a . ~/Library/Application\ Support/Sublime\ Text\ 3/Packages/

# 启动sublime（需命令行支持）
subl ~/Library/Application\ Support/Sublime\ Text\ 3/Packages/XTestPlugin/main.py