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
    "username": "Reuters",
    "last_tweet_id": None,
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
        # 首先尝试加载新格式的config.json
        if os.path.exists("config.json"):
            try:
                with open("config.json", 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    logger.info("成功加载config.json配置文件")
                    return config
            except Exception as e:
                logger.error(f"加载config.json配置文件失败: {e}")
        
        # 如果新格式不存在，尝试加载旧格式
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    # 确保所有必要的配置项都存在
                    for key, value in DEFAULT_CONFIG.items():
                        if key not in config:
                            config[key] = value
                    return config
            except Exception as e:
                logger.error(f"加载配置文件失败: {e}")
                return DEFAULT_CONFIG.copy()
        else:
            # 创建默认配置文件
            self.save_config(DEFAULT_CONFIG)
            return DEFAULT_CONFIG.copy()
    
    def save_config(self, config=None):
        """保存配置到文件"""
        if config is None:
            config = self.config
        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=4)
            logger.info("配置已保存")
        except Exception as e:
            logger.error(f"保存配置失败: {e}")
    
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
        
    def get_tweets_with_selenium(self, username, max_tweets=10):
        """
        使用Selenium WebDriver获取推文
        
        Args:
            username: Twitter/X用户名
            max_tweets: 获取的最大推文数量
            
        Returns:
            推文列表，每个推文是一个字典，包含id、content、date等字段
        """
        tweets = []
        driver = None
        
        try:
            logger.info(f"尝试使用Selenium获取{username}的推文...")
            
            # 配置Chrome选项
            chrome_options = Options()
            chrome_options.add_argument("--headless")  # 无头模式
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--disable-gpu")
            chrome_options.add_argument("--window-size=1920,1080")
            chrome_options.add_argument("--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
            
            # 初始化WebDriver
            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=chrome_options)
            
            # 访问Twitter/X用户页面
            url = f"https://twitter.com/{username}"
            logger.info(f"正在访问 {url}")
            driver.get(url)
            
            # 等待页面加载
            wait = WebDriverWait(driver, 20)
            
            # 等待推文加载
            try:
                wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, '[data-testid="tweet"]')))
                logger.info("推文元素已加载")
            except Exception as e:
                logger.warning(f"等待推文元素超时: {e}")
                
            # 获取推文元素
            tweet_elements = driver.find_elements(By.CSS_SELECTOR, '[data-testid="tweet"]')
            logger.info(f"找到 {len(tweet_elements)} 个推文元素")
            
            # 处理每个推文
            for i, tweet_element in enumerate(tweet_elements):
                if i >= max_tweets:
                    break
                    
                try:
                    # 获取推文ID
                    tweet_link = tweet_element.find_element(By.CSS_SELECTOR, 'a[href*="/status/"]').get_attribute('href')
                    tweet_id = re.search(r'/status/(\d+)', tweet_link).group(1)
                    
                    # 获取推文内容
                    try:
                        content_element = tweet_element.find_element(By.CSS_SELECTOR, '[data-testid="tweetText"]')
                        content = content_element.text
                    except:
                        content = "无法获取推文内容"
                    
                    # 获取推文时间
                    try:
                        time_element = tweet_element.find_element(By.CSS_SELECTOR, 'time')
                        tweet_date = time_element.get_attribute('datetime')
                    except:
                        tweet_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    
                    # 添加到推文列表
                    tweets.append({
                        'id': int(tweet_id),
                        'content': content,
                        'date': tweet_date,
                        'url': tweet_link
                    })
                    
                except Exception as e:
                    logger.error(f"处理推文元素时出错: {e}")
            
            if tweets:
                logger.info(f"成功使用Selenium获取了 {len(tweets)} 条推文")
            else:
                logger.warning("使用Selenium未获取到任何推文")
                
        except Exception as e:
            logger.error(f"使用Selenium获取推文时出错: {e}")
            logger.error(traceback.format_exc())
            
        finally:
            # 关闭WebDriver
            if driver:
                try:
                    driver.quit()
                except:
                    pass
                    
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
        """
        try:
            # 格式化日期
            try:
                if isinstance(tweet['date'], str):
                    # 尝试解析日期字符串
                    date_obj = datetime.strptime(tweet['date'], "%Y-%m-%dT%H:%M:%S%z")
                else:
                    # 假设date已经是datetime对象
                    date_obj = tweet['date']
                formatted_date = date_obj.strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                formatted_date = str(tweet['date'])
            
            # 获取用户名（从URL中提取或使用已有的）
            username = tweet.get('username', '')
            if not username and 'url' in tweet:
                match = re.search(r'twitter\.com/([^/]+)', tweet['url']) or re.search(r'x\.com/([^/]+)', tweet['url'])
                if match:
                    username = match.group(1)
            
            # 准备通知内容
            title = f"@{username} 发布了新推文"
            message = f"{tweet['content'][:200]}...\n\n发布时间: {formatted_date}"
            
            # 打印到终端
            print("\n" + "="*50)
            print(f"新推文 | @{username}")
            print("="*50)
            print(f"内容: {tweet['content']}")
            print(f"时间: {formatted_date}")
            print(f"链接: {tweet['url']}")
            print("="*50 + "\n")
            
            # 显示系统通知
            self.show_notification(
                title,
                message,
                self.config.get("notification_timeout", 0),
                tweet_url=tweet.get('url')
            )
            
        except Exception as e:
            logger.error(f"发送通知时出错: {str(e)}")
            logger.debug(traceback.format_exc())
    
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
        max_tweets = 10  # 每个账户检查的最大推文数
        
        for account in self.config["accounts"]:
            username = account["username"]
            last_tweet_id = account["last_tweet_id"]
            
            logger.info(f"正在检查用户 @{username} 的新推文...")
            
            try:
                tweets = self.get_tweets(username, max_tweets)
                
                if not tweets:
                    logger.warning(f"未获取到 @{username} 的任何推文")
                    continue
                
                # 按ID排序（降序）
                tweets.sort(key=lambda x: x['id'], reverse=True)
                newest_tweet_id = tweets[0]['id']
                
                # 如果是首次运行，只记录最新推文ID，不显示通知
                if last_tweet_id is None:
                    logger.info(f"首次运行，记录 @{username} 的最新推文ID: {newest_tweet_id}")
                    account["last_tweet_id"] = newest_tweet_id
                    self.save_config()
                    continue
                
                # 检查是否有新推文
                new_tweets = [t for t in tweets if t['id'] > last_tweet_id]
                
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
                            if self.db.save_tweet(tweet):
                                logger.info(f"成功保存推文到数据库: {tweet['id']}")
                            else:
                                logger.warning(f"保存推文到数据库失败: {tweet['id']}")
                        except Exception as e:
                            logger.error(f"保存推文到数据库时出错: {str(e)}")
                            logger.debug(traceback.format_exc())
                    
                    # 更新最后检查的推文ID
                    account["last_tweet_id"] = newest_tweet_id
                    self.save_config()
                    
                    # 显示通知（最多显示3条新推文）
                    for tweet in new_tweets[:3]:
                        # 添加用户名到推文对象
                        tweet['username'] = username
                        
                        # 发送通知
                        self.send_notification(tweet)
                        
                        # 如果有多条推文，稍微延迟一下，避免通知重叠
                        if len(new_tweets) > 1:
                            time.sleep(2)
                else:
                    logger.info(f"@{username} 没有发现新推文")
                    
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

def main():
    """主函数"""
    try:
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