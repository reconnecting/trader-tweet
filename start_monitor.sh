#!/bin/bash

# 推文监控器启动脚本
# 提供启动、停止、重启和查看状态功能

# 配置
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MONITOR_SCRIPT="$SCRIPT_DIR/tweet_monitor.py"
PID_FILE="$SCRIPT_DIR/tweet_monitor.pid"
LOG_FILE="$SCRIPT_DIR/tweet_monitor.log"
REQUIREMENTS_FILE="$SCRIPT_DIR/requirements.txt"

# 颜色定义
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
NC='\033[0m' # 无颜色

# 检查Python是否安装
check_python() {
    if ! command -v python3 &> /dev/null; then
        echo -e "${RED}错误: 未找到Python3。请安装Python3后再试。${NC}"
        exit 1
    fi
    
    echo -e "${GREEN}✓ 已找到Python3: $(python3 --version)${NC}"
}

# 检查并安装依赖
check_dependencies() {
    echo -e "${BLUE}正在检查依赖...${NC}"
    
    if [ ! -f "$REQUIREMENTS_FILE" ]; then
        echo -e "${RED}错误: 未找到requirements.txt文件${NC}"
        exit 1
    fi
    
    # 检查pip是否安装
    if ! python3 -m pip --version &> /dev/null; then
        echo -e "${YELLOW}警告: pip未安装，正在尝试安装...${NC}"
        if command -v apt-get &> /dev/null; then
            sudo apt-get update && sudo apt-get install -y python3-pip
        elif command -v brew &> /dev/null; then
            brew install python3-pip
        else
            echo -e "${RED}错误: 无法自动安装pip。请手动安装pip后再试。${NC}"
            exit 1
        fi
    fi
    
    echo -e "${BLUE}正在安装依赖...${NC}"
    python3 -m pip install -r "$REQUIREMENTS_FILE"
    
    if [ $? -ne 0 ]; then
        echo -e "${RED}错误: 安装依赖失败${NC}"
        exit 1
    fi
    
    echo -e "${GREEN}✓ 依赖安装成功${NC}"
}

# 检查脚本是否存在
check_script() {
    if [ ! -f "$MONITOR_SCRIPT" ]; then
        echo -e "${RED}错误: 未找到监控脚本: $MONITOR_SCRIPT${NC}"
        exit 1
    fi
    
    # 确保脚本有执行权限
    chmod +x "$MONITOR_SCRIPT"
    echo -e "${GREEN}✓ 监控脚本已找到${NC}"
}

# 检查进程是否在运行
is_running() {
    if [ -f "$PID_FILE" ]; then
        local pid=$(cat "$PID_FILE")
        if ps -p "$pid" > /dev/null; then
            return 0 # 正在运行
        fi
    fi
    return 1 # 未运行
}

# 启动监控器
start_monitor() {
    echo -e "${BLUE}正在启动推文监控器...${NC}"
    
    # 检查是否已经在运行
    if is_running; then
        echo -e "${YELLOW}警告: 推文监控器已经在运行中 (PID: $(cat "$PID_FILE"))${NC}"
        return 0
    fi
    
    # 检查Python和依赖
    check_python
    check_dependencies
    check_script
    
    # 启动监控器
    cd "$SCRIPT_DIR"
    nohup python3 "$MONITOR_SCRIPT" > "$LOG_FILE" 2>&1 &
    
    # 保存PID
    echo $! > "$PID_FILE"
    
    # 检查是否成功启动
    sleep 2
    if is_running; then
        echo -e "${GREEN}✓ 推文监控器已成功启动 (PID: $(cat "$PID_FILE"))${NC}"
    else
        echo -e "${RED}错误: 启动推文监控器失败${NC}"
        echo -e "${YELLOW}请检查日志文件: $LOG_FILE${NC}"
        exit 1
    fi
}

# 停止监控器
stop_monitor() {
    echo -e "${BLUE}正在停止推文监控器...${NC}"
    
    # 检查是否在运行
    if ! is_running; then
        echo -e "${YELLOW}警告: 推文监控器未在运行${NC}"
        # 清理可能存在的PID文件
        [ -f "$PID_FILE" ] && rm "$PID_FILE"
        return 0
    fi
    
    # 获取PID并发送终止信号
    local pid=$(cat "$PID_FILE")
    kill "$pid"
    
    # 等待进程终止
    echo -e "${BLUE}等待进程终止...${NC}"
    local count=0
    while ps -p "$pid" > /dev/null && [ $count -lt 10 ]; do
        sleep 1
        ((count++))
    done
    
    # 如果进程仍在运行，强制终止
    if ps -p "$pid" > /dev/null; then
        echo -e "${YELLOW}警告: 进程未响应，正在强制终止...${NC}"
        kill -9 "$pid"
        sleep 1
    fi
    
    # 检查是否成功停止
    if ! ps -p "$pid" > /dev/null; then
        echo -e "${GREEN}✓ 推文监控器已停止${NC}"
        rm "$PID_FILE"
    else
        echo -e "${RED}错误: 无法停止推文监控器 (PID: $pid)${NC}"
        exit 1
    fi
}

# 重启监控器
restart_monitor() {
    echo -e "${BLUE}正在重启推文监控器...${NC}"
    stop_monitor
    sleep 2
    start_monitor
}

# 查看状态
status_monitor() {
    if is_running; then
        local pid=$(cat "$PID_FILE")
        local uptime=$(ps -o etime= -p "$pid")
        echo -e "${GREEN}推文监控器正在运行 (PID: $pid)${NC}"
        echo -e "${BLUE}运行时间: $uptime${NC}"
        
        # 显示最近的日志
        if [ -f "$LOG_FILE" ]; then
            echo -e "\n${BLUE}最近的日志:${NC}"
            tail -n 10 "$LOG_FILE"
        fi
    else
        echo -e "${YELLOW}推文监控器未在运行${NC}"
        # 清理可能存在的PID文件
        [ -f "$PID_FILE" ] && rm "$PID_FILE"
    fi
}

# 显示帮助信息
show_help() {
    echo -e "${BLUE}推文监控器控制脚本${NC}"
    echo -e "用法: $0 {start|stop|restart|status|help}"
    echo -e ""
    echo -e "  ${GREEN}start${NC}    启动推文监控器"
    echo -e "  ${GREEN}stop${NC}     停止推文监控器"
    echo -e "  ${GREEN}restart${NC}  重启推文监控器"
    echo -e "  ${GREEN}status${NC}   查看推文监控器状态"
    echo -e "  ${GREEN}help${NC}     显示此帮助信息"
}

# 主逻辑
case "$1" in
    start)
        start_monitor
        ;;
    stop)
        stop_monitor
        ;;
    restart)
        restart_monitor
        ;;
    status)
        status_monitor
        ;;
    help|--help|-h)
        show_help
        ;;
    *)
        echo -e "${YELLOW}未知的命令: $1${NC}"
        show_help
        exit 1
        ;;
esac

exit 0