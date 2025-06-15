#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import os
import logging
import subprocess
import platform

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("NotificationTest")

def show_notification(title, message):
    """
    显示系统通知
    
    Args:
        title: 通知标题
        message: 通知内容
    """
    logger.info(f"开始显示通知: {title}")
    try:
        # 检测操作系统
        system = platform.system()
        
        # 在macOS上使用多种方法确保通知被用户注意到
        if system == 'Darwin':  # macOS
            try:
                # 准备消息内容，确保引号被正确转义
                safe_title = title.replace('"', '\\"')
                safe_message = message.replace('"', '\\"')
                
                # 1. 使用声音提示（不需要通知权限）
                logger.info("尝试播放系统提示音...")
                try:
                    # 播放系统提示音 - 使用更大音量
                    subprocess.run(['afplay', '/System/Library/Sounds/Sosumi.aiff'], check=True)
                    logger.info("系统提示音播放成功")
                except Exception as e:
                    logger.error(f"播放系统提示音失败: {e}")
                
                # 2. 使用语音提示（不需要通知权限）
                logger.info("尝试使用语音提示...")
                try:
                    # 获取可用的语音列表
                    voices_result = subprocess.run(['say', '-v', '?'], capture_output=True, text=True)
                    logger.info(f"可用语音: {voices_result.stdout[:200]}...")
                    
                    # 使用默认语音
                    voice_message = f"测试通知，{safe_title}"
                    subprocess.run(['say', voice_message], check=True)
                    logger.info("语音提示成功")
                except Exception as e:
                    logger.error(f"语音提示失败: {e}")
                
                # 3. 尝试使用terminal-notifier显示通知
                logger.info("检查是否安装了terminal-notifier...")
                try:
                    # 检查是否安装了terminal-notifier
                    result = subprocess.run(['which', 'terminal-notifier'], 
                                           check=False, capture_output=True, text=True)
                    if result.returncode == 0:
                        logger.info("检测到terminal-notifier已安装")
                        
                        # 构建terminal-notifier命令
                        notifier_cmd = [
                            'terminal-notifier',
                            '-title', safe_title,
                            '-subtitle', '测试通知',
                            '-message', safe_message,
                            '-sound', 'default',
                            '-open', 'https://twitter.com',  # 测试URL
                            '-activate', 'com.apple.Safari',
                            '-contentImage', '/System/Library/CoreServices/CoreTypes.bundle/Contents/Resources/BookmarkIcon.icns',  # 使用系统内置的书签图标
                            '-appIcon', '/Applications/Safari.app/Contents/Resources/Safari.icns'  # 使用Safari图标
                        ]
                        
                        # 执行通知命令
                        subprocess.run(notifier_cmd, check=True)
                        logger.info("使用terminal-notifier显示通知成功")
                    else:
                        logger.info("未检测到terminal-notifier，将使用AppleScript作为备选方案")
                        # 使用AppleScript弹窗
                        popup_script = f'''
                        tell application "System Events"
                            activate
                            display dialog "{safe_message}" buttons {{"关闭", "查看测试链接"}} default button "查看测试链接" with title "{safe_title}" with icon caution
                            if button returned of result is "查看测试链接" then
                                tell application "Safari" to open location "https://twitter.com"
                            end if
                        end tell
                        '''
                        
                        # 执行AppleScript弹窗
                        subprocess.run(['osascript', '-e', popup_script], check=True)
                        logger.info("使用AppleScript弹窗成功")
                        logger.info("提示：安装terminal-notifier可以支持更好的通知体验")
                        logger.info("可以使用以下命令安装：brew install terminal-notifier")
                except Exception as e:
                    logger.error(f"使用AppleScript显示通知失败: {e}")
                
                # 4. 尝试使用直接的通知中心API（仅当PyObjC已安装时）
                try:
                    # 先检查是否可以导入Foundation模块
                    import importlib.util
                    if importlib.util.find_spec("Foundation") is not None:
                        logger.info("尝试使用NSUserNotification显示通知...")
                        # 使用Python的objc桥接来直接访问macOS的通知中心API
                        script = '''
import Foundation
import objc

NSUserNotification = objc.lookUpClass('NSUserNotification')
NSUserNotificationCenter = objc.lookUpClass('NSUserNotificationCenter')

notification = NSUserNotification.alloc().init()
notification.setTitle_("{0}")
notification.setSubtitle_("测试通知")
notification.setInformativeText_("{1}")
notification.setSoundName_("NSUserNotificationDefaultSoundName")

center = NSUserNotificationCenter.defaultUserNotificationCenter()
center.deliverNotification_(notification)
'''.format(safe_title, safe_message)
                        
                        # 将脚本写入临时文件并执行
                        with open('/tmp/notification_script.py', 'w') as f:
                            f.write(script)
                        
                        subprocess.run(['python3', '/tmp/notification_script.py'], check=True)
                        logger.info("使用NSUserNotification显示通知成功")
                    else:
                        logger.info("跳过NSUserNotification通知：未安装PyObjC")
                except Exception as e:
                    logger.info(f"跳过NSUserNotification通知：{e}")
                
                logger.info(f"已尝试使用macOS多种方法显示通知: {title}")
                return
            except Exception as e:
                logger.error(f"使用macOS原生通知方法失败: {e}")
        
        logger.info("所有通知方法已尝试")
    except Exception as e:
        logger.error(f"显示通知失败: {e}")

if __name__ == "__main__":
    print("开始测试通知...")
    show_notification("测试通知", "这是一条测试通知，用于检查通知系统是否正常工作")
    print("通知测试完成")