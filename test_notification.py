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
                
                # 3. 尝试使用AppleScript显示通知
                logger.info("尝试使用AppleScript显示通知...")
                try:
                    # 构建AppleScript命令，添加声音
                    script = f'''
                    display notification "{safe_message}" with title "{safe_title}" subtitle "测试通知" sound name "Sosumi"
                    '''
                    
                    # 执行AppleScript
                    subprocess.run(['osascript', '-e', script], check=True)
                    logger.info("使用AppleScript显示通知成功")
                except Exception as e:
                    logger.error(f"使用AppleScript显示通知失败: {e}")
                
                # 4. 尝试使用直接的通知中心API
                logger.info("尝试使用NSUserNotification显示通知...")
                try:
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
                except Exception as e:
                    logger.error(f"使用NSUserNotification显示通知失败: {e}")
                
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