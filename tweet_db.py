#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
推文数据库模块 - 负责存储和检索推文数据
"""

import sqlite3
import os
import json
import logging
from datetime import datetime
import traceback

# 配置日志
logger = logging.getLogger("TweetDB")

class TweetDB:
    """推文数据库类，负责存储和检索推文数据"""
    
    def __init__(self, db_path="tweets.db"):
        """
        初始化数据库连接
        
        Args:
            db_path: 数据库文件路径
        """
        self.db_path = db_path
        self.conn = None
        self.cursor = None
        
        try:
            # 检查数据库文件目录是否存在
            db_dir = os.path.dirname(db_path)
            if db_dir and not os.path.exists(db_dir):
                os.makedirs(db_dir)
                
            # 连接到数据库
            self.conn = sqlite3.connect(db_path)
            self.conn.row_factory = sqlite3.Row  # 使查询结果可以通过列名访问
            self.cursor = self.conn.cursor()
            
            # 创建表（如果不存在）
            self.create_tables()
            
            logger.info(f"数据库连接成功: {db_path}")
        except Exception as e:
            logger.error(f"初始化数据库时出错: {str(e)}")
            logger.debug(traceback.format_exc())
            # 如果初始化失败，确保资源被释放
            self.close()
            raise
    
    def create_tables(self):
        """创建必要的数据库表"""
        try:
            # 创建推文表
            self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS tweets (
                id INTEGER PRIMARY KEY,
                username TEXT NOT NULL,
                content TEXT NOT NULL,
                tweet_date TEXT,
                url TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                raw_data TEXT,
                is_processed INTEGER DEFAULT 0
            )
            ''')
            
            # 创建索引
            self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_tweets_username ON tweets (username)')
            self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_tweets_date ON tweets (tweet_date)')
            self.cursor.execute('CREATE INDEX IF NOT EXISTS idx_tweets_processed ON tweets (is_processed)')
            
            self.conn.commit()
            logger.info("数据库表创建/验证成功")
        except Exception as e:
            logger.error(f"创建数据库表时出错: {str(e)}")
            logger.debug(traceback.format_exc())
            raise
    
    def save_tweet(self, tweet):
        """
        保存推文到数据库
        
        Args:
            tweet: 包含推文信息的字典，必须包含id、content字段
            
        Returns:
            bool: 保存成功返回True，否则返回False
        """
        if not self.conn:
            logger.error("数据库未连接")
            return False
            
        try:
            # 验证必要字段
            if 'id' not in tweet or 'content' not in tweet:
                logger.error("推文缺少必要字段: id 或 content")
                return False
                
            # 提取字段
            tweet_id = tweet['id']
            content = tweet['content']
            
            # 提取可选字段，使用默认值
            username = tweet.get('username', '')
            if not username and 'url' in tweet:
                # 尝试从URL中提取用户名
                import re
                match = re.search(r'twitter\.com/([^/]+)', tweet['url']) or re.search(r'x\.com/([^/]+)', tweet['url'])
                if match:
                    username = match.group(1)
            
            tweet_date = tweet.get('date', datetime.now().isoformat())
            url = tweet.get('url', '')
            
            # 将整个推文对象转换为JSON存储
            raw_data = json.dumps(tweet)
            
            # 检查推文是否已存在
            self.cursor.execute('SELECT id FROM tweets WHERE id = ?', (tweet_id,))
            existing = self.cursor.fetchone()
            
            if existing:
                # 更新现有推文
                self.cursor.execute('''
                UPDATE tweets 
                SET content = ?, username = ?, tweet_date = ?, url = ?, raw_data = ?
                WHERE id = ?
                ''', (content, username, tweet_date, url, raw_data, tweet_id))
                logger.info(f"更新现有推文: {tweet_id}")
            else:
                # 插入新推文
                self.cursor.execute('''
                INSERT INTO tweets (id, username, content, tweet_date, url, raw_data)
                VALUES (?, ?, ?, ?, ?, ?)
                ''', (tweet_id, username, content, tweet_date, url, raw_data))
                logger.info(f"插入新推文: {tweet_id}")
            
            self.conn.commit()
            return True
            
        except Exception as e:
            logger.error(f"保存推文时出错: {str(e)}")
            logger.debug(traceback.format_exc())
            # 回滚事务
            if self.conn:
                self.conn.rollback()
            return False
    
    def get_tweet(self, tweet_id):
        """
        根据ID获取推文
        
        Args:
            tweet_id: 推文ID
            
        Returns:
            dict: 包含推文信息的字典，如果未找到则返回None
        """
        if not self.conn:
            logger.error("数据库未连接")
            return None
            
        try:
            self.cursor.execute('SELECT * FROM tweets WHERE id = ?', (tweet_id,))
            row = self.cursor.fetchone()
            
            if row:
                # 将行转换为字典
                tweet = dict(row)
                # 如果有原始数据，解析为字典
                if 'raw_data' in tweet and tweet['raw_data']:
                    try:
                        raw_data = json.loads(tweet['raw_data'])
                        # 合并原始数据和数据库字段
                        tweet.update(raw_data)
                    except:
                        pass
                return tweet
            else:
                return None
                
        except Exception as e:
            logger.error(f"获取推文时出错: {str(e)}")
            logger.debug(traceback.format_exc())
            return None
    
    def get_tweets(self, username=None, limit=100, offset=0, processed=None):
        """
        获取推文列表
        
        Args:
            username: 可选，按用户名过滤
            limit: 返回的最大记录数
            offset: 起始偏移量
            processed: 可选，按处理状态过滤 (True/False)
            
        Returns:
            list: 包含推文信息的字典列表
        """
        if not self.conn:
            logger.error("数据库未连接")
            return []
            
        try:
            query = 'SELECT * FROM tweets'
            params = []
            conditions = []
            
            # 添加过滤条件
            if username:
                conditions.append('username = ?')
                params.append(username)
                
            if processed is not None:
                conditions.append('is_processed = ?')
                params.append(1 if processed else 0)
                
            # 组合条件
            if conditions:
                query += ' WHERE ' + ' AND '.join(conditions)
                
            # 添加排序和分页
            query += ' ORDER BY tweet_date DESC LIMIT ? OFFSET ?'
            params.extend([limit, offset])
            
            self.cursor.execute(query, params)
            rows = self.cursor.fetchall()
            
            # 将行转换为字典列表
            tweets = []
            for row in rows:
                tweet = dict(row)
                # 如果有原始数据，解析为字典
                if 'raw_data' in tweet and tweet['raw_data']:
                    try:
                        raw_data = json.loads(tweet['raw_data'])
                        # 合并原始数据和数据库字段
                        tweet.update(raw_data)
                    except:
                        pass
                tweets.append(tweet)
                
            return tweets
                
        except Exception as e:
            logger.error(f"获取推文列表时出错: {str(e)}")
            logger.debug(traceback.format_exc())
            return []
    
    def mark_as_processed(self, tweet_id, processed=True):
        """
        标记推文为已处理/未处理
        
        Args:
            tweet_id: 推文ID
            processed: 是否已处理
            
        Returns:
            bool: 操作成功返回True，否则返回False
        """
        if not self.conn:
            logger.error("数据库未连接")
            return False
            
        try:
            self.cursor.execute(
                'UPDATE tweets SET is_processed = ? WHERE id = ?', 
                (1 if processed else 0, tweet_id)
            )
            self.conn.commit()
            return True
                
        except Exception as e:
            logger.error(f"标记推文状态时出错: {str(e)}")
            logger.debug(traceback.format_exc())
            if self.conn:
                self.conn.rollback()
            return False
    
    def search_tweets(self, keyword, username=None, limit=100, offset=0):
        """
        搜索推文
        
        Args:
            keyword: 搜索关键词
            username: 可选，按用户名过滤
            limit: 返回的最大记录数
            offset: 起始偏移量
            
        Returns:
            list: 包含推文信息的字典列表
        """
        if not self.conn:
            logger.error("数据库未连接")
            return []
            
        try:
            query = 'SELECT * FROM tweets WHERE content LIKE ?'
            params = [f'%{keyword}%']
            
            # 添加用户名过滤
            if username:
                query += ' AND username = ?'
                params.append(username)
                
            # 添加排序和分页
            query += ' ORDER BY tweet_date DESC LIMIT ? OFFSET ?'
            params.extend([limit, offset])
            
            self.cursor.execute(query, params)
            rows = self.cursor.fetchall()
            
            # 将行转换为字典列表
            tweets = []
            for row in rows:
                tweet = dict(row)
                # 如果有原始数据，解析为字典
                if 'raw_data' in tweet and tweet['raw_data']:
                    try:
                        raw_data = json.loads(tweet['raw_data'])
                        # 合并原始数据和数据库字段
                        tweet.update(raw_data)
                    except:
                        pass
                tweets.append(tweet)
                
            return tweets
                
        except Exception as e:
            logger.error(f"搜索推文时出错: {str(e)}")
            logger.debug(traceback.format_exc())
            return []
    
    def get_stats(self):
        """
        获取数据库统计信息
        
        Returns:
            dict: 包含统计信息的字典
        """
        if not self.conn:
            logger.error("数据库未连接")
            return {}
            
        try:
            stats = {}
            
            # 获取总推文数
            self.cursor.execute('SELECT COUNT(*) FROM tweets')
            stats['total_tweets'] = self.cursor.fetchone()[0]
            
            # 获取用户数量
            self.cursor.execute('SELECT COUNT(DISTINCT username) FROM tweets')
            stats['total_users'] = self.cursor.fetchone()[0]
            
            # 获取已处理/未处理的推文数
            self.cursor.execute('SELECT COUNT(*) FROM tweets WHERE is_processed = 1')
            stats['processed_tweets'] = self.cursor.fetchone()[0]
            
            self.cursor.execute('SELECT COUNT(*) FROM tweets WHERE is_processed = 0')
            stats['unprocessed_tweets'] = self.cursor.fetchone()[0]
            
            # 获取最早和最新的推文日期
            self.cursor.execute('SELECT MIN(tweet_date), MAX(tweet_date) FROM tweets')
            min_date, max_date = self.cursor.fetchone()
            stats['earliest_date'] = min_date
            stats['latest_date'] = max_date
            
            # 获取每个用户的推文数量
            self.cursor.execute('''
            SELECT username, COUNT(*) as tweet_count 
            FROM tweets 
            GROUP BY username 
            ORDER BY tweet_count DESC
            ''')
            stats['tweets_by_user'] = {row[0]: row[1] for row in self.cursor.fetchall()}
            
            return stats
                
        except Exception as e:
            logger.error(f"获取统计信息时出错: {str(e)}")
            logger.debug(traceback.format_exc())
            return {}
    
    def close(self):
        """关闭数据库连接"""
        try:
            if self.cursor:
                self.cursor.close()
                self.cursor = None
                
            if self.conn:
                self.conn.close()
                self.conn = None
                
            logger.info("数据库连接已关闭")
        except Exception as e:
            logger.error(f"关闭数据库连接时出错: {str(e)}")
            logger.debug(traceback.format_exc())

# 测试代码
if __name__ == "__main__":
    # 配置日志
    logging.basicConfig(level=logging.INFO)
    
    # 测试数据库功能
    db = TweetDB()
    
    # 测试保存推文
    test_tweet = {
        'id': 123456789,
        'username': 'test_user',
        'content': '这是一条测试推文',
        'date': '2023-01-01T12:00:00',
        'url': 'https://twitter.com/test_user/status/123456789'
    }
    
    if db.save_tweet(test_tweet):
        print("推文保存成功")
    else:
        print("推文保存失败")
    
    # 测试获取推文
    retrieved_tweet = db.get_tweet(123456789)
    if retrieved_tweet:
        print(f"获取推文成功: {retrieved_tweet['content']}")
    else:
        print("获取推文失败")
    
    # 测试获取推文列表
    tweets = db.get_tweets(username='test_user', limit=10)
    print(f"获取到 {len(tweets)} 条推文")
    
    # 测试搜索推文
    search_results = db.search_tweets('测试')
    print(f"搜索到 {len(search_results)} 条包含'测试'的推文")
    
    # 测试标记推文为已处理
    if db.mark_as_processed(123456789):
        print("标记推文为已处理成功")
    else:
        print("标记推文为已处理失败")
    
    # 测试获取统计信息
    stats = db.get_stats()
    print("数据库统计信息:")
    for key, value in stats.items():
        print(f"  {key}: {value}")
    
    # 关闭数据库连接
    db.close()
    print("测试完成")