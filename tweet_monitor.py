#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
推文监控器 - 监控指定Twitter/X账户的新推文并显示通知
"""

import json
import os
import sys
import time
import threading
import logging
import subprocess
import re
from datetime import datetime
import traceback

# 导入数据库模块
from tweet_db import TweetDB

# 自定义日志格式化器，使用北京时间（UTC+8）
class BeijingTimeFormatter(logging.Formatter):
    def converter(self, timestamp):
        dt = datetime.fromtimestamp(timestamp)
        # 添加8小时，转换为北京时间
        from datetime import timedelta
        beijing_dt = dt + timedelta(hours=8)
        return beijing_dt
    
    def formatTime(self, record, datefmt=None):
        dt = self.converter(record.created)
        if datefmt:
            s = dt.strftime(datefmt)
        else:
            s = dt.strftime("%Y-%m-%d %H:%M:%S")
        return s

# 配置日志
logger = logging.getLogger("TweetMonitor")
logger.setLevel(logging.INFO)

# 创建文件处理器
file_handler = logging.FileHandler("tweet_monitor.log")
file_handler.setLevel(logging.INFO)

# 创建控制台处理器
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)

# 创建格式化器
formatter = BeijingTimeFormatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# 设置处理器的格式化器
file_handler.setFormatter(formatter)
console_handler.setFormatter(formatter)

# 添加处理器到日志记录器
logger.addHandler(file_handler)
logger.addHandler(console_handler)

# 检查依赖
try:
    from plyer import notification
    import requests
    from bs4 import BeautifulSoup
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service
    from selenium.webdriver.common.by import By
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from webdriver_manager.chrome import ChromeDriverManager
except ImportError as e:
    logger.error(f"缺少必要的依赖: {e}")
    logger.info("正在尝试安装依赖...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
        logger.info("依赖安装成功，请重新启动程序")
    except Exception as e:
        logger.error(f"安装依赖失败: {e}")
    sys.exit(1)

# 默认配置
DEFAULT_CONFIG = {
    "check_interval": 300,  # 5分钟，单位：秒
    "accounts": [
        {
            "username": "Reuters",
            "last_tweet_id": None
        }
    ],
    "max_tweets_to_check": 10,
    "notification_timeout": 0  # 通知显示时间，0表示一直显示直到用户关闭
}

CONFIG_FILE = "tweet_monitor_config.json"

class TweetMonitor:
    """推文监控器类"""
    
    def __init__(self):
        """初始化监控器"""
        self.config = self.load_config()
        self.running = False
        self.monitor_thread = None
        # 初始化数据库连接
        self.db = TweetDB()
        
    def load_config(self):
        """加载配置文件，如果不存在则创建默认配置"""
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    logger.info(f"成功加载配置文件: {CONFIG_FILE}")
                    
                    # 确保配置文件结构正确
                    if "accounts" not in config:
                        logger.warning("配置文件中缺少accounts列表，使用默认配置")
                        config["accounts"] = DEFAULT_CONFIG["accounts"]
                    
                    # 确保每个账户都有必需的字段
                    for account in config["accounts"]:
                        if "username" not in account:
                            logger.error("账户配置中缺少username字段")
                            continue
                        if "last_tweet_id" not in account:
                            account["last_tweet_id"] = None
                        elif account["last_tweet_id"] is not None:
                            # 确保last_tweet_id是整数类型
                            try:
                                account["last_tweet_id"] = int(account["last_tweet_id"])
                            except (ValueError, TypeError):
                                logger.warning(f"账户 {account['username']} 的last_tweet_id无效，重置为None")
                                account["last_tweet_id"] = None
                    
                    # 确保所有必需的配置项都存在
                    for key, value in DEFAULT_CONFIG.items():
                        if key not in config:
                            config[key] = value
                    
                    return config
            else:
                # 创建默认配置文件
                config = DEFAULT_CONFIG.copy()
                self.save_config(config)
                return config
                
        except Exception as e:
            logger.error(f"加载配置文件失败: {e}")
            logger.error(traceback.format_exc())
            return DEFAULT_CONFIG.copy()
    
    def save_config(self, config=None):
        """保存配置到文件"""
        if config is None:
            config = self.config
        try:
            # 在保存之前验证配置
            if "accounts" not in config:
                logger.error("尝试保存无效的配置：缺少accounts列表")
                return False
                
            # 创建配置文件的副本，以便我们可以修改它而不影响原始配置
            config_copy = json.loads(json.dumps(config))
            
            # 确保last_tweet_id是字符串类型（用于JSON序列化）
            for account in config_copy["accounts"]:
                if account.get("last_tweet_id") is not None:
                    account["last_tweet_id"] = str(account["last_tweet_id"])
            
            # 创建配置文件目录（如果不存在）
            os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
            
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(config_copy, f, indent=4, ensure_ascii=False)
            logger.info(f"配置已保存到 {CONFIG_FILE}")
            return True
            
        except Exception as e:
            logger.error(f"保存配置失败: {e}")
            logger.error(traceback.format_exc())
            return False
    
    def validate_tweet_date(self, tweet):
        """
        验证推文日期的有效性，如果日期无效则使用当前时间
        
        Args:
            tweet: 推文字典
            
        Returns:
            更新后的推文字典
        """
        current_year = datetime.now().year
        
        try:
            # 解析日期
            if isinstance(tweet['date'], str):
                # 处理不同的日期格式
                date_str = tweet['date']
                if 'Z' in date_str:
                    date_str = date_str.replace('Z', '+00:00')
                parsed_date = datetime.fromisoformat(date_str)
            else:
                parsed_date = tweet['date']
            
            # 检查年份是否合理
            if parsed_date.year < current_year - 1:  # 如果推文比去年还早
                logger.warning(f"推文日期可能不正确: ID={tweet.get('id')}, 日期={tweet['date']}")
                tweet['date'] = datetime.now().isoformat()
                logger.info(f"已将推文日期更新为当前时间: {tweet['date']}")
        except Exception as e:
            logger.warning(f"解析推文日期时出错: {e}, 使用当前时间")
            tweet['date'] = datetime.now().isoformat()
            
        return tweet

    def get_tweets(self, username, max_tweets=10):
        """
        获取指定用户的最新推文
        
        Args:
            username: Twitter/X用户名
            max_tweets: 获取的最大推文数量
            
        Returns:
            推文列表，每个推文是一个字典，包含id、content、date等字段
        """
        # 首先尝试使用Selenium获取推文
        tweets = self.get_tweets_with_selenium(username, max_tweets)
        
        # 验证并更新推文日期
        if tweets:
            tweets = [self.validate_tweet_date(tweet) for tweet in tweets]
            
            # 检查是否所有推文都是旧的
            all_old = True
            for tweet in tweets:
                try:
                    parsed_date = datetime.fromisoformat(tweet['date'].replace('Z', '+00:00'))
                    if parsed_date.year >= datetime.now().year - 1:
                        all_old = False
                        break
                except:
                    all_old = False
            
            # 如果所有推文都是旧的，重试一次
            if all_old:
                logger.warning("检测到所有推文都是旧的，尝试重新获取...")
                driver = None
                try:
                    # 使用新的浏览器会话重试
                    chrome_options = Options()
                    chrome_options.add_argument("--headless=new")
                    chrome_options.add_argument("--incognito")
                    chrome_options.add_argument("--disable-cache")
                    service = Service(ChromeDriverManager().install())
                    driver = webdriver.Chrome(service=service, options=chrome_options)
                    
                    # 访问用户页面并强制刷新
                    url = f"https://twitter.com/{username}"
                    driver.get(url)
                    time.sleep(2)
                    driver.refresh()
                    time.sleep(5)
                    
                    # 重新获取推文
                    tweets = self.get_tweets_with_selenium(username, max_tweets, driver=driver)
                    if tweets:
                        tweets = [self.validate_tweet_date(tweet) for tweet in tweets]
                except Exception as e:
                    logger.error(f"重试获取推文时出错: {e}")
                finally:
                    if driver:
                        try:
                            driver.quit()
                        except:
                            pass
        
        # 如果Selenium方法失败，尝试使用snscrape
        if not tweets:
            try:
                # 使用Python模块直接调用snscrape，而不是通过命令行
                import snscrape.modules.twitter as sntwitter
                import itertools
                
                logger.info(f"尝试使用snscrape获取{username}的推文...")
                
                # 使用sntwitter.TwitterUserScraper获取用户推文
                scraper = sntwitter.TwitterUserScraper(username)
                tweet_list = list(itertools.islice(scraper.get_items(), max_tweets))
                
                if not tweet_list:
                    logger.warning(f"未获取到{username}的推文")
                else:
                    for tweet in tweet_list:
                        tweet_id = tweet.id
                        tweet_url = f"https://x.com/{username}/status/{tweet_id}"
                        
                        tweets.append({
                            'id': int(tweet_id),
                            'content': tweet.rawContent,
                            'date': tweet.date,
                            'url': tweet_url
                        })
                    
                    logger.info(f"成功使用snscrape获取了 {len(tweets)} 条推文")
                    return tweets
                    
            except Exception as e:
                logger.error(f"使用snscrape获取推文时出错: {e}")
                logger.error(traceback.format_exc())
        
        # 如果前两种方法都失败，尝试使用备用方法
        if not tweets:
            logger.info("尝试使用备用方法获取推文...")
            tweets = self.get_tweets_fallback(username, max_tweets)
            
        return tweets
        
    def get_tweets_with_selenium(self, username, max_tweets=10, driver=None, force_refresh=False):
        """
        使用Selenium WebDriver获取推文
        
        Args:
            username: Twitter/X用户名
            max_tweets: 获取的最大推文数量
            driver: 可选的WebDriver实例，如果提供则使用它
            force_refresh: 是否强制刷新页面
            
        Returns:
            推文列表，每个推文是一个字典，包含id、content、date等字段
        """
        tweets = []
        should_close_driver = False
        
        try:
            logger.info(f"尝试使用Selenium获取{username}的推文...")
            
            # 如果没有提供driver，创建一个新的
            if driver is None:
                should_close_driver = True
                # 配置Chrome选项
                chrome_options = Options()
                chrome_options.add_argument("--headless=new")  # 新版无头模式
                chrome_options.add_argument("--no-sandbox")
                chrome_options.add_argument("--disable-dev-shm-usage")
                chrome_options.add_argument("--disable-gpu")
                chrome_options.add_argument("--window-size=1920,1080")
                chrome_options.add_argument("--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
                # 禁用缓存
                chrome_options.add_argument("--disable-application-cache")
                chrome_options.add_argument("--disable-cache")
                chrome_options.add_argument("--disable-offline-load-stale-cache")
                chrome_options.add_argument("--disk-cache-size=0")
                # 添加额外的参数以确保获取最新内容
                chrome_options.add_argument("--incognito")  # 使用隐身模式
                prefs = {
                    "profile.default_content_setting_values.notifications": 2,
                    'disk-cache-size': 0,
                    "profile.managed_default_content_settings.images": 1,
                    "profile.default_content_setting_values.cookies": 1
                }
                chrome_options.add_experimental_option("prefs", prefs)
                
                # 初始化WebDriver
                service = Service(ChromeDriverManager().install())
                driver = webdriver.Chrome(service=service, options=chrome_options)
            
            # 访问Twitter/X用户页面
            url = f"https://twitter.com/{username}"
            logger.info(f"正在访问 {url}")
            driver.get(url)
            
            # 等待页面加载
            wait = WebDriverWait(driver, 30)  # 增加等待时间
            
            # 页面加载和刷新策略
            retry_count = 0
            max_retries = 3
            success = False
            
            while retry_count < max_retries and not success:
                try:
                    # 等待页面基本元素加载
                    wait.until(EC.presence_of_element_located((By.TAG_NAME, 'body')))
                    
                    if force_refresh or retry_count > 0:
                        logger.info(f"执行页面刷新 (尝试 {retry_count + 1}/{max_retries})")
                        driver.refresh()
                        time.sleep(3)  # 给页面一些时间来初始化
                    
                    # 等待推文加载
                    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, '[data-testid="tweet"]')))
                    logger.info("推文元素已加载")
                    
                    # 尝试获取第一条推文的时间戳
                    time_element = driver.find_element(By.CSS_SELECTOR, 'time')
                    if time_element:
                        tweet_date = time_element.get_attribute('datetime')
                        if tweet_date:
                            parsed_date = datetime.fromisoformat(tweet_date.replace('Z', '+00:00'))
                            if parsed_date.year >= datetime.now().year - 1:
                                success = True
                                logger.info("成功获取到最新推文")
                                break
                    
                    if not success:
                        logger.warning("未检测到最新推文，将重试")
                        retry_count += 1
                        time.sleep(2)  # 短暂等待后重试
                        
                except Exception as e:
                    logger.warning(f"页面加载/刷新过程中出错 (尝试 {retry_count + 1}/{max_retries}): {e}")
                    retry_count += 1
                    if retry_count < max_retries:
                        time.sleep(3)  # 在重试之前等待
                
            if success:
                # 滚动页面以加载更多推文
                last_height = driver.execute_script("return document.body.scrollHeight")
                scroll_attempts = 0
                max_scroll_attempts = 3
                
                while scroll_attempts < max_scroll_attempts:
                    # 滚动到页面底部
                    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                    time.sleep(2)  # 等待页面加载
                    
                    # 计算新的滚动高度
                    new_height = driver.execute_script("return document.body.scrollHeight")
                    if new_height == last_height:
                        break
                    last_height = new_height
                    scroll_attempts += 1
                
                # 滚动回顶部以确保获取最新推文
                driver.execute_script("window.scrollTo(0, 0);")
                time.sleep(2)
                
                # 获取推文元素
                tweet_elements = driver.find_elements(By.CSS_SELECTOR, '[data-testid="tweet"]')
                logger.info(f"找到 {len(tweet_elements)} 个推文元素")
                
                # 如果没有找到推文元素，尝试使用备用选择器
                if not tweet_elements:
                    logger.warning("未找到推文元素，尝试使用备用选择器...")
                    # 尝试其他可能的选择器
                    backup_selectors = [
                        'article[data-testid]',
                        'div[aria-label*="Timeline"] div[data-testid]',
                        'div[role="article"]'
                    ]
                    
                    for selector in backup_selectors:
                        try:
                            backup_elements = driver.find_elements(By.CSS_SELECTOR, selector)
                            if backup_elements:
                                logger.info(f"使用备用选择器 '{selector}' 找到 {len(backup_elements)} 个元素")
                                tweet_elements = backup_elements
                                break
                        except Exception as e:
                            logger.warning(f"尝试备用选择器 '{selector}' 时出错: {e}")
                
                # 处理每个推文
                current_year = datetime.now().year
                for i, tweet_element in enumerate(tweet_elements):
                    if i >= max_tweets:
                        break
                        
                    try:
                        # 获取推文ID和URL
                        tweet_link = tweet_element.find_element(By.CSS_SELECTOR, 'a[href*="/status/"]').get_attribute('href')
                        tweet_id = re.search(r'/status/(\d+)', tweet_link).group(1)
                        
                        # 获取推文内容
                        try:
                            content_element = tweet_element.find_element(By.CSS_SELECTOR, '[data-testid="tweetText"]')
                            content = content_element.text
                        except Exception as e:
                            content = "无法获取推文内容"
                            logger.warning(f"无法获取推文内容: {tweet_id}, 错误: {e}")
                        
                        # 获取推文时间
                        try:
                            time_element = tweet_element.find_element(By.CSS_SELECTOR, 'time')
                            tweet_date = time_element.get_attribute('datetime')
                            
                            # 验证日期是否合理
                            if tweet_date:
                                try:
                                    parsed_date = datetime.fromisoformat(tweet_date.replace('Z', '+00:00'))
                                    # 检查年份是否合理 - 如果年份比当前年份早2年以上，可能是错误数据
                                    if parsed_date.year < current_year - 2:
                                        logger.warning(f"发现可能过时的推文: ID={tweet_id}, 日期={tweet_date}")
                                        # 如果是明显过时的推文，尝试使用当前时间
                                        if parsed_date.year < current_year - 5:
                                            logger.info(f"推文日期过旧，使用当前时间替代: {tweet_id}")
                                            tweet_date = datetime.now().isoformat()
                                except Exception as e:
                                    logger.warning(f"解析推文日期时出错: {e}")
                                    tweet_date = datetime.now().isoformat()
                            else:
                                tweet_date = datetime.now().isoformat()
                        except Exception as e:
                            tweet_date = datetime.now().isoformat()
                            logger.warning(f"获取推文时间出错: {e}, 使用当前时间")
                        
                        # 添加到推文列表
                        tweets.append({
                            'id': int(tweet_id),
                            'content': content,
                            'date': tweet_date,
                            'url': tweet_link.replace('twitter.com', 'x.com')  # 更新为x.com域名
                        })
                    except Exception as e:
                        logger.error(f"处理推文时出错: {e}")
                        continue
            else:
                logger.error("在多次尝试后仍未能成功加载推文")
            
            if tweets:
                logger.info(f"成功使用Selenium获取了 {len(tweets)} 条推文")
            else:
                logger.warning("使用Selenium未获取到任何推文")
                
        except Exception as e:
            logger.error(f"使用Selenium获取推文时出错: {e}")
            logger.error(traceback.format_exc())
            return []
            
        finally:
            # 只有在我们创建了driver的情况下才关闭它
            if should_close_driver and driver:
                try:
                    driver.quit()
                    logger.info("已关闭WebDriver")
                except Exception as e:
                    logger.error(f"关闭WebDriver时出错: {e}")
                    # 在关闭失败的情况下，尝试强制结束进程
                    try:
                        import psutil
                        current_process = psutil.Process()
                        children = current_process.children(recursive=True)
                        for child in children:
                            if "chromedriver" in child.name().lower() or "chrome" in child.name().lower():
                                child.terminate()
                        logger.info("已强制结束残留的Chrome进程")
                    except Exception as e2:
                        logger.error(f"强制结束Chrome进程时出错: {e2}")
        
        # 对获取到的推文进行最后的验证和排序
        if tweets:
            try:
                # 按时间倒序排序，确保最新的推文在前面
                tweets.sort(key=lambda x: datetime.fromisoformat(x['date'].replace('Z', '+00:00')), reverse=True)
                
                # 移除任何重复的推文（基于ID）
                seen_ids = set()
                unique_tweets = []
                for tweet in tweets:
                    if tweet['id'] not in seen_ids:
                        seen_ids.add(tweet['id'])
                        unique_tweets.append(tweet)
                
                tweets = unique_tweets[:max_tweets]  # 确保不超过请求的数量
                logger.info(f"成功处理并返回 {len(tweets)} 条推文")
            except Exception as e:
                logger.error(f"处理最终推文列表时出错: {e}")
                # 如果排序失败，至少返回原始推文列表
                tweets = tweets[:max_tweets]
                
        return tweets
    
    def get_tweets_fallback(self, username, max_tweets=10):
        """
        备用方法：使用Twitter/X的GraphQL API获取推文
        
        Args:
            username: Twitter/X用户名
            max_tweets: 获取的最大推文数量
            
        Returns:
            推文列表，每个推文是一个字典，包含id、content、date等字段
        """
        tweets = []
        
        try:
            logger.info(f"尝试使用GraphQL API获取{username}的推文...")
            
            # 使用更真实的User-Agent和必要的headers
            headers = {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': '*/*',
                'Accept-Language': 'en-US,en;q=0.9',
                'Referer': 'https://twitter.com/',
                'Content-Type': 'application/json',
                'Authorization': 'Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA',
                'x-twitter-active-user': 'yes',
                'x-twitter-client-language': 'en',
                'Origin': 'https://twitter.com',
                'Connection': 'keep-alive',
                'Sec-Fetch-Dest': 'empty',
                'Sec-Fetch-Mode': 'cors',
                'Sec-Fetch-Site': 'same-site',
            }
            
            # 使用session保持cookie
            session = requests.Session()
            
            # 首先获取用户ID
            try:
                # 访问用户页面获取初始数据
                user_url = f"https://twitter.com/{username}"
                response = session.get(user_url, headers=headers, timeout=15)
                
                if response.status_code == 200:
                    # 尝试从HTML中提取用户ID
                    html_content = response.text
                    
                    # 尝试直接从HTML中提取推文
                    # 现代Twitter使用JavaScript渲染，所以我们尝试查找初始数据
                    json_data_match = re.search(r'<script id="__NEXT_DATA__" type="application\/json">(.*?)<\/script>', html_content, re.DOTALL)
                    
                    if json_data_match:
                        try:
                            json_data = json.loads(json_data_match.group(1))
                            logger.info("成功提取Twitter初始数据")
                            
                            # 尝试从初始数据中提取推文
                            # 这里的路径可能需要根据Twitter的实际数据结构调整
                            props = json_data.get('props', {})
                            page_props = props.get('pageProps', {})
                            
                            # 提取用户信息
                            user_data = None
                            if 'user' in page_props:
                                user_data = page_props.get('user', {})
                            elif 'profile' in page_props:
                                user_data = page_props.get('profile', {}).get('user', {})
                                
                            if user_data:
                                logger.info(f"找到用户数据: {user_data.get('screen_name', '')}")
                            
                            # 提取推文数据
                            timeline_entries = []
                            
                            # 尝试不同的数据路径
                            if 'timeline' in page_props:
                                timeline_entries = page_props.get('timeline', {}).get('entries', [])
                            elif 'profile' in page_props and 'timeline' in page_props.get('profile', {}):
                                timeline_entries = page_props.get('profile', {}).get('timeline', {}).get('entries', [])
                                
                            logger.info(f"找到 {len(timeline_entries)} 个时间线条目")
                            
                            # 处理推文数据
                            for entry in timeline_entries:
                                if len(tweets) >= max_tweets:
                                    break
                                    
                                try:
                                    content = entry.get('content', {})
                                    tweet_data = content.get('tweet', {})
                                    
                                    if not tweet_data:
                                        # 尝试其他可能的路径
                                        item_content = content.get('item', {}).get('content', {})
                                        tweet_data = item_content.get('tweet', {})
                                        
                                    if tweet_data:
                                        tweet_id = tweet_data.get('id_str', '')
                                        tweet_text = tweet_data.get('full_text', '')
                                        created_at = tweet_data.get('created_at', '')
                                        
                                        if tweet_id:
                                            tweets.append({
                                                'id': int(tweet_id),
                                                'content': tweet_text,
                                                'date': created_at,
                                                'url': f"https://twitter.com/{username}/status/{tweet_id}"
                                            })
                                except Exception as e:
                                    logger.error(f"处理推文条目时出错: {e}")
                                    
                            if tweets:
                                logger.info(f"从Twitter初始数据中提取了 {len(tweets)} 条推文")
                                return tweets
                            else:
                                logger.warning("无法从Twitter初始数据中提取推文")
                                
                        except json.JSONDecodeError as e:
                            logger.error(f"解析Twitter初始数据JSON时出错: {e}")
                    else:
                        logger.warning("未找到Twitter初始数据")
                        
                    # 如果无法从初始数据中提取推文，尝试使用模拟的方式
                    logger.info("尝试使用模拟方式提取推文...")
                    
                    # 查找可能包含推文的元素
                    article_matches = re.findall(r'<article[^>]*>(.*?)</article>', html_content, re.DOTALL)
                    logger.info(f"找到 {len(article_matches)} 个可能的推文文章元素")
                    
                    for i, article in enumerate(article_matches):
                        if i >= max_tweets:
                            break
                            
                        try:
                            # 尝试提取推文ID
                            tweet_id_match = re.search(r'data-testid="tweet"[^>]*data-tweet-id="(\d+)"', article)
                            if not tweet_id_match:
                                tweet_id_match = re.search(r'href="/[^/]+/status/(\d+)"', article)
                                
                            if tweet_id_match:
                                tweet_id = tweet_id_match.group(1)
                                
                                # 尝试提取推文内容
                                content_match = re.search(r'data-testid="tweetText"[^>]*>(.*?)</div>', article, re.DOTALL)
                                content = ""
                                if content_match:
                                    content = content_match.group(1)
                                    # 清理HTML标签
                                    content = re.sub(r'<[^>]+>', ' ', content).strip()
                                    content = re.sub(r'\s+', ' ', content)
                                
                                # 添加到推文列表
                                tweets.append({
                                    'id': int(tweet_id),
                                    'content': content,
                                    'date': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),  # 无法准确获取时间
                                    'url': f"https://twitter.com/{username}/status/{tweet_id}"
                                })
                        except Exception as e:
                            logger.error(f"处理推文文章元素时出错: {e}")
                    
                    if tweets:
                        logger.info(f"从Twitter HTML中提取了 {len(tweets)} 条推文")
                        return tweets
                    else:
                        logger.warning("无法从Twitter HTML中提取推文")
                        
                else:
                    logger.warning(f"访问Twitter用户页面失败，状态码: {response.status_code}")
                    
            except Exception as e:
                logger.error(f"获取Twitter用户数据时出错: {e}")
                logger.error(traceback.format_exc())
                
            # 如果上述方法都失败，尝试使用RSS
            logger.info("尝试使用RSS方法...")
            return self.get_tweets_from_rss(username, max_tweets)
                
        except Exception as e:
            logger.error(f"从Twitter获取推文时出错: {e}")
            logger.error(traceback.format_exc())
            # 尝试RSS方法
            return self.get_tweets_from_rss(username, max_tweets)
            
        return tweets
        
    def get_tweets_from_rss(self, username, max_tweets=10):
        """
        使用RSS订阅获取推文
        
        Args:
            username: Twitter/X用户名
            max_tweets: 获取的最大推文数量
            
        Returns:
            推文列表，每个推文是一个字典，包含id、content、date等字段
        """
        tweets = []
        
        try:
            logger.info(f"尝试从RSS获取{username}的推文...")
            
            # 尝试几个可能的RSS服务
            rss_urls = [
                f"https://nitter.pussthecat.org/{username}/rss",
                f"https://rsshub.app/twitter/user/{username}",
                f"https://fetchrss.com/rss/6479d9b6c5c3a0775e7d9d0c6479d9a5c5c3a0775e7d9c9e.xml"
            ]
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }
            
            for rss_url in rss_urls:
                try:
                    response = requests.get(rss_url, headers=headers, timeout=10)
                    
                    if response.status_code == 200:
                        # 解析RSS内容
                        soup = BeautifulSoup(response.content, 'xml')
                        items = soup.find_all('item')
                        
                        if not items:
                            logger.warning(f"在 {rss_url} 中未找到RSS条目")
                            continue
                            
                        logger.info(f"从 {rss_url} 找到 {len(items)} 个RSS条目")
                        
                        for i, item in enumerate(items):
                            if i >= max_tweets:
                                break
                                
                            try:
                                # 获取链接
                                link = item.find('link')
                                link_text = link.text if link else ""
                                
                                # 提取推文ID
                                tweet_id_match = re.search(r'/status/(\d+)', link_text)
                                tweet_id = tweet_id_match.group(1) if tweet_id_match else None
                                
                                if not tweet_id:
                                    continue
                                    
                                # 获取内容
                                description = item.find('description')
                                content = description.text if description else ""
                                
                                # 清理HTML标签
                                content = re.sub(r'<[^>]+>', '', content).strip()
                                
                                # 获取日期
                                pub_date = item.find('pubDate')
                                date_str = pub_date.text if pub_date else datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                
                                tweets.append({
                                    'id': int(tweet_id),
                                    'content': content,
                                    'date': date_str,
                                    'url': f"https://x.com/{username}/status/{tweet_id}"
                                })
                                
                            except Exception as e:
                                logger.error(f"解析RSS条目时出错: {e}")
                                
                        if tweets:
                            logger.info(f"从RSS成功获取了 {len(tweets)} 条推文")
                            return tweets
                            
                    else:
                        logger.warning(f"获取RSS失败，状态码: {response.status_code}")
                        
                except requests.exceptions.RequestException as e:
                    logger.warning(f"请求RSS {rss_url} 出错: {e}")
                    
        except Exception as e:
            logger.error(f"从RSS获取推文时出错: {e}")
            logger.error(traceback.format_exc())
            
        if not tweets:
            logger.error("所有获取推文的方法都失败")
            
        return tweets
    
    def send_notification(self, tweet):
        """
        发送推文通知
        
        Args:
            tweet: 包含推文信息的字典
        
        Returns:
            bool: 通知是否成功发送
        """
        try:
            # 验证推文数据
            if not isinstance(tweet, dict):
                logger.error(f"无效的推文数据类型: {type(tweet)}")
                return False
                
            required_fields = ['content', 'id']
            for field in required_fields:
                if field not in tweet:
                    logger.error(f"推文数据缺少必要字段: {field}")
                    return False
            
            # 格式化日期
            try:
                if isinstance(tweet.get('date'), str):
                    # 尝试解析日期字符串
                    if 'T' in tweet['date'] and ('Z' in tweet['date'] or '+' in tweet['date']):
                        # ISO格式
                        date_str = tweet['date'].replace('Z', '+00:00')
                        date_obj = datetime.fromisoformat(date_str)
                    else:
                        # 尝试其他常见格式
                        try:
                            date_obj = datetime.strptime(tweet['date'], "%Y-%m-%d %H:%M:%S")
                        except ValueError:
                            date_obj = datetime.strptime(tweet['date'], "%a %b %d %H:%M:%S %z %Y")
                else:
                    # 假设date已经是datetime对象
                    date_obj = tweet['date']
                formatted_date = date_obj.strftime("%Y-%m-%d %H:%M:%S")
            except Exception as e:
                logger.warning(f"格式化日期时出错: {e}, 使用原始日期")
                formatted_date = str(tweet.get('date', '未知时间'))
            
            # 获取用户名（从URL中提取或使用已有的）
            username = tweet.get('username', '')
            if not username and 'url' in tweet:
                match = re.search(r'twitter\.com/([^/]+)', tweet['url']) or re.search(r'x\.com/([^/]+)', tweet['url'])
                if match:
                    username = match.group(1)
            
            # 如果仍然没有用户名，使用"未知用户"
            if not username:
                username = "未知用户"
                logger.warning(f"无法确定推文 {tweet['id']} 的用户名")
            
            # 准备通知内容
            title = f"@{username} 发布了新推文"
            
            # 确保内容不为空
            content = tweet.get('content', '').strip()
            if not content:
                content = "[此推文没有文本内容]"
                logger.warning(f"推文 {tweet['id']} 没有文本内容")
            
            # 限制内容长度，添加省略号
            if len(content) > 200:
                message = f"{content[:200]}...\n\n发布时间: {formatted_date}"
            else:
                message = f"{content}\n\n发布时间: {formatted_date}"
            
            # 打印到终端
            print("\n" + "="*50)
            print(f"新推文 | @{username}")
            print("="*50)
            print(f"内容: {content}")
            print(f"时间: {formatted_date}")
            print(f"链接: {tweet.get('url', '无链接')}")
            print("="*50 + "\n")
            
            # 显示系统通知
            success = self.show_notification(
                title,
                message,
                self.config.get("notification_timeout", 0),
                tweet_url=tweet.get('url')
            )
            
            if success:
                logger.info(f"成功发送推文通知: ID={tweet['id']}")
                return True
            else:
                logger.warning(f"发送推文通知失败: ID={tweet['id']}")
                return False
            
        except Exception as e:
            logger.error(f"发送通知时出错: {str(e)}")
            logger.error(traceback.format_exc())
            return False
    
    def show_notification(self, title, message, timeout=10, tweet_url=None):
        """
        显示系统通知
        
        Args:
            title: 通知标题
            message: 通知内容
            timeout: 通知显示时间（秒），0表示一直显示直到用户关闭
            tweet_url: 推文URL，点击通知时打开
        """
        logger.info(f"开始显示通知: {title}")
        try:
            # 检测操作系统
            import platform
            system = platform.system()
            
            # 在macOS上使用多种方法确保通知被用户注意到
            if system == 'Darwin':  # macOS
                try:
                    # 准备消息内容，确保引号被正确转义
                    safe_title = title.replace('"', '\\"')
                    safe_message = message.replace('"', '\\"')
                    
                    # 1. 使用声音提示（不需要通知权限）
                    import subprocess
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
                        voice_message = f"新推文提醒，{safe_title}"
                        # 不指定语音，使用系统默认语音
                        subprocess.run(['say', voice_message], check=True)
                        logger.info("语音提示成功")
                    except Exception as e:
                        logger.error(f"语音提示失败: {e}")
                    
                    # 4. 尝试使用terminal-notifier显示通知（如果已安装）
                    terminal_notifier_installed = False
                    if tweet_url:  # 只有当有URL时才尝试使用terminal-notifier
                        logger.info("检查是否安装了terminal-notifier...")
                        try:
                            # 检查是否安装了terminal-notifier
                            result = subprocess.run(['which', 'terminal-notifier'], 
                                                   check=False, capture_output=True, text=True)
                            if result.returncode == 0:
                                terminal_notifier_installed = True
                                logger.info("检测到terminal-notifier已安装")
                                
                                # 构建terminal-notifier命令，添加contentImage参数以显示大图标
                                notifier_cmd = [
                                    'terminal-notifier',
                                    '-title', safe_title,
                                    '-subtitle', '推文监控器',
                                    '-message', safe_message,
                                    '-sound', 'default',
                                    '-open', tweet_url,
                                    '-activate', 'com.apple.Safari',  # 激活Safari而不是编辑器
                                    '-contentImage', '/System/Library/CoreServices/CoreTypes.bundle/Contents/Resources/BookmarkIcon.icns',  # 使用系统内置的书签图标
                                    '-appIcon', '/Applications/Safari.app/Contents/Resources/Safari.icns'  # 使用Safari图标
                                ]
                                
                                # 执行通知命令
                                subprocess.run(notifier_cmd, check=True)
                                logger.info("使用terminal-notifier显示通知成功")
                                # 不在这里记录链接，统一在最后记录
                            else:
                                logger.info("未检测到terminal-notifier，将使用AppleScript作为备选方案")
                        except Exception as e:
                            logger.error(f"使用terminal-notifier显示通知失败: {e}")
                            terminal_notifier_installed = False
                    
                    # 5. 如果terminal-notifier未安装或失败，直接使用AppleScript弹窗而不是通知
                    if not terminal_notifier_installed:
                        logger.info("尝试使用AppleScript弹窗...")
                        try:
                            # 直接使用弹窗而不是通知，避免点击通知的问题
                            if tweet_url:
                                popup_script = f'''
                                tell application "System Events"
                                    activate
                                    display dialog "{safe_message}" buttons {{"关闭", "查看推文"}} default button "查看推文" with title "{safe_title}" with icon caution
                                    if button returned of result is "查看推文" then
                                        tell application "Safari" to open location "{tweet_url}"
                                    end if
                                end tell
                                '''
                            else:
                                popup_script = f'''
                                tell application "System Events"
                                    activate
                                    display dialog "{safe_message}" buttons {{"确定"}} default button "确定" with title "{safe_title}" with icon caution
                                end tell
                                '''
                            
                            # 执行AppleScript弹窗
                            subprocess.run(['osascript', '-e', popup_script], check=True)
                            logger.info("使用AppleScript弹窗成功")
                            
                            # 如果有URL，记录链接并提示用户安装terminal-notifier
                            if tweet_url:
                                logger.info(f"通知链接: {tweet_url}")  # 记录通知链接
                                logger.info("提示：安装terminal-notifier可以支持更好的通知体验")
                                logger.info("可以使用以下命令安装：brew install terminal-notifier")
                                
                                # 同时在终端中显示链接，方便用户直接复制
                                print(f"\n新推文链接: {tweet_url}\n")
                        except Exception as e:
                            logger.error(f"使用AppleScript显示通知失败: {e}")
                    
                    logger.info(f"已尝试使用macOS多种方法显示通知: {title}")
                    return
                except Exception as e:
                    logger.error(f"使用macOS原生通知方法失败: {e}")
                    # 如果失败，回退到plyer方法
            
            # 对于其他系统或macOS回退，使用plyer
            logger.info("尝试使用plyer显示通知...")
            kwargs = {
                'title': title,
                'message': message,
                'app_name': "推文监控器",
                'timeout': timeout
            }
            
            # 如果提供了URL，添加点击回调
            if tweet_url:
                # 在不同平台上打开URL的方法
                def open_url():
                    import webbrowser
                    webbrowser.open(tweet_url)
                
                # 添加回调函数
                kwargs['callback'] = open_url
                
                # 添加URL到消息中，以便用户知道可以点击
                kwargs['message'] = f"{message}\n\n点击通知可打开推文链接"
            
            notification.notify(**kwargs)
            logger.info(f"已使用plyer显示通知: {title}")
            if tweet_url:
                logger.info(f"通知链接: {tweet_url}")
        except Exception as e:
            logger.error(f"显示通知失败: {e}")
    
    def check_new_tweets(self):
        """检查所有账户的新推文并显示通知"""
        max_tweets = self.config.get("max_tweets_to_check", 10)  # 从配置中获取最大推文数
        
        # 确保accounts列表存在
        if "accounts" not in self.config:
            logger.error("配置文件中缺少accounts列表")
            self.config["accounts"] = DEFAULT_CONFIG["accounts"]
            self.save_config()
            return
        
        for account in self.config["accounts"]:
            username = account.get("username")
            if not username:
                logger.error("账户配置中缺少username")
                continue
                
            last_tweet_id = account.get("last_tweet_id")
            logger.info(f"正在检查用户 @{username} 的新推文... (上次检查的推文ID: {last_tweet_id})")
            
            try:
                tweets = self.get_tweets(username, max_tweets)
                
                if not tweets:
                    logger.warning(f"未获取到 @{username} 的任何推文")
                    continue
                
                # 打印获取到的所有推文ID，用于调试
                tweet_ids = [str(t['id']) for t in tweets]
                logger.info(f"获取到的推文ID列表: {', '.join(tweet_ids)}")
                
                # 按ID排序（降序）
                tweets.sort(key=lambda x: int(x['id']), reverse=True)
                newest_tweet_id = int(tweets[0]['id'])
                logger.info(f"最新推文ID: {newest_tweet_id}")
                
                # 记录最新的推文ID，即使没有新推文也更新
                should_save_config = False
                
                # 如果是首次运行，只记录最新推文ID，不显示通知
                if last_tweet_id is None:
                    logger.info(f"首次运行，记录 @{username} 的最新推文ID: {newest_tweet_id}")
                    account["last_tweet_id"] = newest_tweet_id
                    should_save_config = True
                else:
                    # 确保last_tweet_id是整数
                    try:
                        last_tweet_id = int(last_tweet_id)
                        logger.info(f"上次检查的推文ID (转换为整数): {last_tweet_id}")
                    except (ValueError, TypeError):
                        logger.warning(f"账户 {username} 的last_tweet_id无效 ({last_tweet_id})，重置为0")
                        last_tweet_id = 0
                    
                    # 检查是否有新推文
                    new_tweets = []
                    for t in tweets:
                        try:
                            tweet_id = int(t['id'])
                            if tweet_id > last_tweet_id:
                                logger.info(f"发现新推文: ID={tweet_id} > 上次ID={last_tweet_id}")
                                new_tweets.append(t)
                            else:
                                logger.info(f"旧推文: ID={tweet_id} <= 上次ID={last_tweet_id}")
                        except (ValueError, TypeError) as e:
                            logger.warning(f"推文ID转换错误: {e}, 原始ID: {t['id']}")
                    
                    if new_tweets:
                        logger.info(f"发现 @{username} 的 {len(new_tweets)} 条新推文")
                        
                        # 处理每条新推文
                        for tweet in new_tweets:
                            # 记录详细的推文信息到日志
                            logger.info(f"新推文详情: ID={tweet['id']}, 用户={username}, "
                                      f"发布时间={tweet['date']}, URL={tweet['url']}")
                            logger.info(f"推文内容: {tweet['content']}")
                            
                            # 保存推文到数据库
                            try:
                                if hasattr(self, 'db') and self.db:
                                    if self.db.save_tweet(tweet):
                                        logger.info(f"成功保存推文到数据库: {tweet['id']}")
                                    else:
                                        logger.warning(f"保存推文到数据库失败: {tweet['id']}")
                            except Exception as e:
                                logger.error(f"保存推文到数据库时出错: {str(e)}")
                                logger.debug(traceback.format_exc())
                        
                        # 更新最后检查的推文ID
                        account["last_tweet_id"] = newest_tweet_id
                        should_save_config = True
                        
                        # 显示通知（最多显示3条新推文）
                        for tweet in new_tweets[:3]:
                            # 添加用户名到推文对象
                            tweet['username'] = username
                            
                            # 发送通知
                            logger.info(f"准备发送推文通知: ID={tweet['id']}")
                            self.send_notification(tweet)
                            
                            # 如果有多条推文，稍微延迟一下，避免通知重叠
                            if len(new_tweets) > 1:
                                time.sleep(2)
                    else:
                        logger.info(f"@{username} 没有发现新推文")
                        # 即使没有新推文，也更新最后检查的推文ID（如果有更新）
                        if newest_tweet_id > last_tweet_id:
                            logger.info(f"更新 @{username} 的最新推文ID: {newest_tweet_id} (原ID: {last_tweet_id})")
                            account["last_tweet_id"] = newest_tweet_id
                            should_save_config = True
                
                # 如果需要，保存配置
                if should_save_config:
                    logger.info(f"保存配置文件，更新 @{username} 的last_tweet_id为 {account['last_tweet_id']}")
                    saved = self.save_config()
                    if saved:
                        logger.info("配置保存成功")
                    else:
                        logger.error("配置保存失败")
                    
            except Exception as e:
                logger.error(f"检查 @{username} 的新推文时出错: {e}")
                logger.error(traceback.format_exc())
                continue
    
    def monitor_loop(self):
        """监控循环，定期检查新推文"""
        while self.running:
            try:
                self.check_new_tweets()
            except Exception as e:
                logger.error(f"监控循环中出错: {e}")
            
            # 等待下一次检查
            interval = self.config["check_interval"]
            logger.info(f"等待 {interval} 秒后进行下一次检查...")
            
            # 分段等待，以便能够及时响应停止信号
            for _ in range(interval // 10):
                if not self.running:
                    break
                time.sleep(10)
            
            # 处理剩余的等待时间
            remaining = interval % 10
            if remaining > 0 and self.running:
                time.sleep(remaining)
    
    def start(self):
        """启动监控"""
        if self.running:
            logger.warning("监控器已经在运行中")
            return
        
        self.running = True
        self.monitor_thread = threading.Thread(target=self.monitor_loop)
        self.monitor_thread.daemon = True
        self.monitor_thread.start()
        
        # 显示所有被监控的账户
        usernames = [account["username"] for account in self.config["accounts"]]
        logger.info(f"监控器已启动，正在监控以下用户: @{', @'.join(usernames)}")
        logger.info(f"检查间隔: {self.config['check_interval']} 秒")
    
    def stop(self):
        """停止监控"""
        if not self.running:
            logger.warning("监控器未在运行")
            return
        
        logger.info("正在停止监控器...")
        self.running = False
        
        if self.monitor_thread:
            self.monitor_thread.join(timeout=30)
            if self.monitor_thread.is_alive():
                logger.warning("监控线程未能在30秒内停止")
            else:
                logger.info("监控器已停止")
        
        # 关闭数据库连接
        if hasattr(self, 'db'):
            try:
                self.db.close()
                logger.info("数据库连接已关闭")
            except Exception as e:
                logger.error(f"关闭数据库连接时出错: {str(e)}")
                logger.debug(traceback.format_exc())
    
    def update_config(self, new_config):
        """更新配置"""
        for key, value in new_config.items():
            if key in self.config:
                self.config[key] = value
        
        self.save_config()
        logger.info("配置已更新")

def test_monitor():
    """测试推文监控器的核心功能"""
    logger.info("开始测试推文监控器...")
    
    try:
        # 创建监控器实例
        monitor = TweetMonitor()
        
        # 获取配置的账户列表
        accounts = monitor.config.get("accounts", [])
        if not accounts:
            logger.error("配置文件中没有账户信息")
            print("错误: 配置文件中没有账户信息。请先使用 --add 命令添加要监控的账户。")
            return False
            
        # 测试每个账户
        for account in accounts:
            username = account.get("username")
            if not username:
                logger.error("账户配置中缺少username")
                continue
                
            print(f"\n测试账户 @{username} 的功能:")
            logger.info(f"\n测试账户 @{username} 的功能:")
            
            # 1. 测试获取推文
            print("1. 测试获取推文功能...")
            logger.info("1. 测试获取推文功能...")
            tweets = monitor.get_tweets(username, 5)
            if tweets:
                print(f"✓ 成功获取到 {len(tweets)} 条推文")
                print(f"第一条推文ID: {tweets[0]['id']}")
                print(f"第一条推文内容: {tweets[0]['content'][:100]}...")
                logger.info(f"✓ 成功获取到 {len(tweets)} 条推文")
                logger.info(f"第一条推文ID: {tweets[0]['id']}")
                logger.info(f"第一条推文内容: {tweets[0]['content'][:100]}...")
            else:
                print("✗ 获取推文失败")
                logger.error("✗ 获取推文失败")
                continue
            
            # 2. 测试通知功能
            print("\n2. 测试通知功能...")
            logger.info("\n2. 测试通知功能...")
            try:
                test_tweet = tweets[0].copy()  # 创建副本避免修改原始数据
                test_tweet['username'] = username
                print(f"尝试发送测试通知，推文ID: {test_tweet['id']}")
                logger.info(f"尝试发送测试通知，推文ID: {test_tweet['id']}")
                
                # 添加测试标记
                test_tweet['content'] = f"[测试通知] {test_tweet['content']}"
                
                success = monitor.send_notification(test_tweet)
                if success:
                    print("✓ 通知发送成功")
                    logger.info("✓ 通知发送成功")
                else:
                    print("✗ 通知发送失败")
                    logger.error("✗ 通知发送失败")
            except Exception as e:
                print(f"✗ 通知发送失败: {e}")
                logger.error(f"✗ 通知发送失败: {e}")
            
            # 3. 测试配置保存
            print("\n3. 测试配置保存功能...")
            logger.info("\n3. 测试配置保存功能...")
            try:
                original_id = account.get("last_tweet_id")
                test_id = tweets[0]['id']
                print(f"尝试将last_tweet_id从 {original_id} 更新为 {test_id}")
                logger.info(f"尝试将last_tweet_id从 {original_id} 更新为 {test_id}")
                
                account["last_tweet_id"] = test_id
                if monitor.save_config():
                    print("✓ 配置保存成功")
                    logger.info("✓ 配置保存成功")
                    # 恢复原始ID
                    account["last_tweet_id"] = original_id
                    monitor.save_config()
                    print(f"✓ 已恢复原始ID: {original_id}")
                    logger.info(f"✓ 已恢复原始ID: {original_id}")
                else:
                    print("✗ 配置保存失败")
                    logger.error("✗ 配置保存失败")
            except Exception as e:
                print(f"✗ 配置保存测试失败: {e}")
                logger.error(f"✗ 配置保存测试失败: {e}")
            
            # 4. 测试新推文检测逻辑
            print("\n4. 测试新推文检测逻辑...")
            logger.info("\n4. 测试新推文检测逻辑...")
            try:
                # 临时将last_tweet_id设置为0来模拟有新推文的情况
                original_id = account.get("last_tweet_id")
                print(f"临时将last_tweet_id从 {original_id} 设置为 0 以模拟新推文")
                logger.info(f"临时将last_tweet_id从 {original_id} 设置为 0 以模拟新推文")
                
                account["last_tweet_id"] = 0
                print("运行check_new_tweets()...")
                logger.info("运行check_new_tweets()...")
                
                monitor.check_new_tweets()
                
                # 恢复原始ID
                print(f"恢复原始ID: {original_id}")
                logger.info(f"恢复原始ID: {original_id}")
                account["last_tweet_id"] = original_id
                monitor.save_config()
                
                print("✓ 新推文检测逻辑测试完成")
                logger.info("✓ 新推文检测逻辑测试完成")
            except Exception as e:
                print(f"✗ 新推文检测逻辑测试失败: {e}")
                logger.error(f"✗ 新推文检测逻辑测试失败: {e}")
            
            # 5. 测试数据库功能（如果启用）
            if hasattr(monitor, 'db') and monitor.db:
                print("\n5. 测试数据库功能...")
                logger.info("\n5. 测试数据库功能...")
                try:
                    test_tweet = tweets[0].copy()
                    test_tweet['username'] = username
                    test_tweet['test_flag'] = True  # 添加测试标记
                    
                    print(f"尝试保存推文到数据库，ID: {test_tweet['id']}")
                    logger.info(f"尝试保存推文到数据库，ID: {test_tweet['id']}")
                    
                    if monitor.db.save_tweet(test_tweet):
                        print("✓ 数据库保存成功")
                        logger.info("✓ 数据库保存成功")
                    else:
                        print("✗ 数据库保存失败")
                        logger.error("✗ 数据库保存失败")
                except Exception as e:
                    print(f"✗ 数据库测试失败: {e}")
                    logger.error(f"✗ 数据库测试失败: {e}")
            
            print("\n测试完成")
            logger.info("\n测试完成")
            return True
            
    except Exception as e:
        print(f"测试过程中出错: {e}")
        logger.error(f"测试过程中出错: {e}")
        logger.error(traceback.format_exc())
        return False

def add_account(username):
    """添加要监控的账户"""
    try:
        # 加载当前配置
        monitor = TweetMonitor()
        
        # 检查账户是否已存在
        for account in monitor.config["accounts"]:
            if account["username"].lower() == username.lower():
                logger.info(f"账户 @{username} 已在监控列表中")
                return True
        
        # 添加新账户
        monitor.config["accounts"].append({
            "username": username,
            "last_tweet_id": None
        })
        
        # 保存配置
        if monitor.save_config():
            logger.info(f"成功添加账户 @{username} 到监控列表")
            return True
        else:
            logger.error(f"保存配置失败，无法添加账户 @{username}")
            return False
    except Exception as e:
        logger.error(f"添加账户时出错: {e}")
        logger.error(traceback.format_exc())
        return False

def remove_account(username):
    """移除监控的账户"""
    try:
        # 加载当前配置
        monitor = TweetMonitor()
        
        # 查找账户
        found = False
        for i, account in enumerate(monitor.config["accounts"]):
            if account["username"].lower() == username.lower():
                # 移除账户
                del monitor.config["accounts"][i]
                found = True
                break
        
        if not found:
            logger.warning(f"账户 @{username} 不在监控列表中")
            return False
        
        # 保存配置
        if monitor.save_config():
            logger.info(f"成功从监控列表中移除账户 @{username}")
            return True
        else:
            logger.error(f"保存配置失败，无法移除账户 @{username}")
            return False
    except Exception as e:
        logger.error(f"移除账户时出错: {e}")
        logger.error(traceback.format_exc())
        return False

def list_accounts():
    """列出所有监控的账户"""
    try:
        # 加载当前配置
        monitor = TweetMonitor()
        
        # 获取账户列表
        accounts = monitor.config["accounts"]
        
        if not accounts:
            print("当前没有监控任何账户")
            return True
        
        # 打印账户列表
        print("\n当前监控的账户列表:")
        print("=" * 50)
        for i, account in enumerate(accounts):
            username = account["username"]
            last_tweet_id = account.get("last_tweet_id", "未知")
            print(f"{i+1}. @{username} (最后检查的推文ID: {last_tweet_id})")
        print("=" * 50)
        
        return True
    except Exception as e:
        logger.error(f"列出账户时出错: {e}")
        logger.error(traceback.format_exc())
        return False

def test_notification(username=None):
    """测试特定账户的通知功能"""
    try:
        # 创建监控器实例
        monitor = TweetMonitor()
        
        # 如果没有指定用户名，使用配置中的第一个账户
        if not username:
            if not monitor.config.get("accounts"):
                print("错误: 配置文件中没有账户信息。请先使用 --add 命令添加要监控的账户。")
                return False
            username = monitor.config["accounts"][0]["username"]
        
        print(f"测试 @{username} 的通知功能...")
        logger.info(f"测试 @{username} 的通知功能...")
        
        # 获取最新的推文
        tweets = monitor.get_tweets(username, 1)
        if not tweets:
            print(f"错误: 无法获取 @{username} 的推文")
            logger.error(f"无法获取 @{username} 的推文")
            return False
        
        # 创建测试通知
        test_tweet = tweets[0].copy()
        test_tweet['username'] = username
        test_tweet['content'] = f"[测试通知] {test_tweet['content']}"
        
        print(f"发送测试通知，推文ID: {test_tweet['id']}")
        logger.info(f"发送测试通知，推文ID: {test_tweet['id']}")
        
        # 发送通知
        success = monitor.send_notification(test_tweet)
        
        if success:
            print("✓ 通知发送成功")
            logger.info("✓ 通知发送成功")
            return True
        else:
            print("✗ 通知发送失败")
            logger.error("✗ 通知发送失败")
            return False
    
    except Exception as e:
        print(f"测试通知时出错: {e}")
        logger.error(f"测试通知时出错: {e}")
        logger.error(traceback.format_exc())
        return False

def show_help():
    """显示帮助信息"""
    print("\n推文监控器 - 使用说明")
    print("=" * 50)
    print("命令行参数:")
    print("  无参数         - 启动监控器")
    print("  --test         - 运行完整测试模式")
    print("  --notify [USER] - 测试通知功能（可选指定用户名）")
    print("  --add USER     - 添加要监控的账户")
    print("  --remove USER  - 移除监控的账户")
    print("  --list         - 列出所有监控的账户")
    print("  --help         - 显示此帮助信息")
    print("=" * 50)
    print("示例:")
    print("  python tweet_monitor.py --add elonmusk")
    print("  python tweet_monitor.py --remove elonmusk")
    print("  python tweet_monitor.py --list")
    print("  python tweet_monitor.py --notify elonmusk")
    print("=" * 50)

def main():
    """主函数"""
    try:
        # 检查命令行参数
        if len(sys.argv) > 1:
            # 处理命令行参数
            arg = sys.argv[1].lower()
            
            if arg == "--test":
                # 运行测试
                logger.info("运行测试模式...")
                success = test_monitor()
                if success:
                    logger.info("测试完成")
                    return 0
                else:
                    logger.error("测试失败")
                    return 1
            
            elif arg == "--add" and len(sys.argv) > 2:
                # 添加账户
                username = sys.argv[2]
                if add_account(username):
                    return 0
                else:
                    return 1
            
            elif arg == "--remove" and len(sys.argv) > 2:
                # 移除账户
                username = sys.argv[2]
                if remove_account(username):
                    return 0
                else:
                    return 1
            
            elif arg == "--list":
                # 列出账户
                if list_accounts():
                    return 0
                else:
                    return 1
            
            elif arg == "--help":
                # 显示帮助信息
                show_help()
                return 0
            
            else:
                # 未知参数
                print(f"未知参数: {arg}")
                show_help()
                return 1
        
        # 正常运行模式
        monitor = TweetMonitor()
        monitor.start()
        
        # 保持程序运行，直到用户按Ctrl+C
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("接收到停止信号")
        finally:
            monitor.stop()
            
    except Exception as e:
        logger.error(f"程序运行时出错: {e}")
        logger.error(traceback.format_exc())
        return 1
    
    return 0

if __name__ == "__main__":
    sys.exit(main())