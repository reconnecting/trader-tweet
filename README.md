# 外汇交易员推文监控器

这是一个用于监控特定Twitter/X账户推文的工具，特别适合关注外汇交易员的实时动态。当监控的账户发布新推文时，系统会立即显示桌面通知。

## 系统要求

- Python 3.9+
- Chrome浏览器（用于Selenium）
- macOS/Linux/Windows

## 安装步骤

1. 克隆或下载此仓库到本地：
```bash
git clone [仓库地址]
cd 外汇交易员推文
```

2. 安装依赖：
```bash
pip3 install -r requirements.txt
```

## 配置说明

1. 编辑`tweet_monitor_config.json`文件配置要监控的Twitter/X账户：
```json
{
    "accounts": [
        {
            "username": "Reuters",
            "last_tweet_id": null
        }
    ],
    "check_interval": 300,
    "notification": {
        "sound": "Ping",
        "icon_path": "twitter_icon.png"
    }
}
```

- `username`: 要监控的Twitter/X账户用户名（不包含@符号）
- `last_tweet_id`: 最后检查的推文ID（首次运行时设为null）
- `check_interval`: 检查间隔时间（单位：秒）

2. 可以添加多个要监控的账户，例如：
```json
{
    "accounts": [
        {
            "username": "Reuters",
            "last_tweet_id": null
        },
        {
            "username": "Bloomberg",
            "last_tweet_id": null
        }
    ],
    "check_interval": 300
}
```

## 使用方法

### 启动监控器

使用提供的shell脚本来控制监控器：

```bash
# 启动监控器
./start_monitor.sh start

# 停止监控器
./start_monitor.sh stop

# 重启监控器
./start_monitor.sh restart

# 查看监控器状态
./start_monitor.sh status
```

### 查看日志

监控器的日志文件位于`logs`目录下：
```bash
tail -f logs/tweet_monitor.log
```

### 测试通知系统

在开始监控之前，你可以使用测试脚本来验证通知系统是否正常工作：

```bash
# 运行通知测试
python3 test_notification.py
```

这将触发一个测试通知，帮助你：
- 确认通知系统配置正确
- 验证通知显示效果
- 测试声音和图标设置
- 检查通知点击功能

### 桌面通知

当检测到新推文时，系统会显示桌面通知，包含：
- 推文作者
- 推文内容
- 发布时间

点击通知可以直接打开推文链接。

#### macOS用户增强通知

macOS用户可以安装terminal-notifier获得更好的通知体验：

```bash
# 使用Homebrew安装
brew install terminal-notifier
```

安装后，系统将自动使用terminal-notifier提供更美观的通知，包括：
- 自定义图标
- 点击直接打开Twitter/X网页
- 系统声音提示

## 故障排除

1. 如果遇到权限问题：
```bash
chmod +x start_monitor.sh
chmod +x tweet_monitor.py
```

2. 如果看不到桌面通知：
- macOS：检查系统偏好设置中的通知设置
- Linux：确保已安装通知服务（如notify-osd）
- Windows：检查系统通知设置

3. 如果无法获取推文：
- 检查网络连接
- 确认Twitter/X账户名称正确
- 检查Chrome浏览器是否正确安装

## 注意事项

1. 推文检查间隔不建议设置太短，以避免触发Twitter/X的访问限制
2. 首次运行时会自动下载Chrome驱动，需要保持网络连接
3. 程序会自动保存最后检查的推文ID，重启后不会重复显示旧推文

## 技术支持

如果遇到问题：
1. 查看日志文件了解详细错误信息
2. 检查配置文件格式是否正确
3. 确保所有依赖都已正确安装

## 更新日志

### v1.1.0
- 改进通知系统：优化terminal-notifier配置
- 添加更好的错误处理机制
- 改进通知图标和声音设置
- 增强通知层级，提供多种通知方式的备选方案
- 添加通知测试脚本，方便验证通知系统

### v1.0.0
- 初始版本发布
- 支持多账户监控
- 实现桌面通知功能
- 添加Selenium支持，提高获取推文的可靠性