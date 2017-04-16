#!/usr/bin/env bash
# pycharm下"一键调试"脚本
# working directory：～/Documents/XTestPlugin/XTestPlugin
# 同步文件变更

local=.
remote=~/Library/Application\ Support/Sublime\ Text\ 3/Packages/XTestPlugin/

rsync -a ${local} "${remote}"

# 启动sublime（需命令行支持）
subl "${remote}"main.py