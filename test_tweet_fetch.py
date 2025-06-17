#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
测试脚本 - 测试是否能获取推特数据
"""

import sys
import logging
from tweet_monitor import TweetMonitor

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger("TweetFetchTest")

def test_fetch_tweets():
    """测试获取推文功能"""
    logger.info("开始测试获取推文功能")
    
    # 初始化监控器
    monitor = TweetMonitor()
    
    # 测试账户列表
    test_accounts = ["Reuters", "WSJ", "CNBC"]
    
    for username in test_accounts:
        logger.info(f"尝试获取 @{username} 的推文...")
        
        try:
            # 获取推文
            tweets = monitor.get_tweets(username, max_tweets=3)
            
            if tweets:
                logger.info(f"成功获取 @{username} 的 {len(tweets)} 条推文")
                
                # 打印推文详情
                for i, tweet in enumerate(tweets):
                    logger.info(f"推文 {i+1}:")
                    logger.info(f"  ID: {tweet['id']}")
                    logger.info(f"  内容: {tweet['content'][:100]}...")
                    logger.info(f"  日期: {tweet['date']}")
                    logger.info(f"  URL: {tweet['url']}")
                    logger.info("-" * 50)
            else:
                logger.warning(f"未能获取 @{username} 的推文")
                
        except Exception as e:
            logger.error(f"获取 @{username} 的推文时出错: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    logger.info("测试完成")

if __name__ == "__main__":
    test_fetch_tweets()