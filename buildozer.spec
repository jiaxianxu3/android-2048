[app]

# (str) 应用标题（汉字需确保文件 UTF-8）
title = 2048双模式

# (str) 包名（必须唯一，建议用自己域名反写）
package.name = game2048dual
package.domain = org.workbuddy

# (str) 应用版本（buildozer 必需，否则配置校验不通过）
version = 1.0.0

# (str) 源码目录（buildozer 以本文件所在目录为根）
source.dir = .
source.include_exts = py,png,jpg,jpeg,json,ttf
source.include_patterns = *.py

# (list) 依赖
requirements = kivy==2.3.0

# (str) 入口文件
entrypoint = main.py

# (str) 应用图标与启动图（可选，放同目录）
# presplash.filename = %(source.dir)s/presplash.png
# icon.filename = %(source.dir)s/icon.png

# (str) 横竖屏：portrait 竖屏（手机 2048 推荐）
orientation = portrait
fullscreen = 1
android.wakelock = 1

# (list) 权限：本游戏无需联网/存储等敏感权限
android.permissions =

# Android 构建参数（buildozer 默认即可，下面给保守值）
android.api = 34
android.minapi = 21
android.ndk = 25b
android.accept_sdk_license = True
android.arch = arm64-v8a

# (bool) 是否用 AIDL/内容提供：关闭
android.create_release = False

[buildozer]

# (int) 日志级别
log_level = 2
warn_on_root = 1

# (str) 远程构建（本地不需要）
remote.services =

# (str) 默认命令
# buildozer android debug
