#!/usr/bin/env python3
# -*- coding:utf-8 -*-
# __author__ = 'edsion'

no_file_or_folder = """
您的工程中找不到文件（夹），请尝试以下步骤后，再重新执行此操作：
macOS: File -> Open...
    或: Project -> Add Folder to Project...
Windows: File -> Open File...
    或: File -> Open Folder...
    或: Project -> Add Folder to Project...
"""
too_many_files_or_folders = """
无法确定目标文件(夹)，请尝试：
1. 点击左侧sidebar，选择一个文件，使之打开进入编辑状态
2. 重新执行此操作
"""
can_not_found_scripts = """
找不到待测脚本，请尝试：
1. 如果*push文件错误*请检查配置文件中指定的"remote_path"路径下脚本文件是否存在
【注意】一定要先选择或打开一个待执行的脚本，才能确定需要push的文件列表
2. 如果*push文件错误*禁用配置文件中的"cleanup_every_time"，然后手动push脚本到设备
3. 如果*sd卡无写入权限*请重启手机后再试
"""
