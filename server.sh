#!/usr/bin/env bash
#
# LearnFlux - 一键启停管理脚本
#
#   用法:  ./server.sh {start|stop|restart|status|log}
#
#   start    后台启动服务
#   stop     停止服务（按端口可靠回收，含 uv 衍生子进程）
#   restart  重启（改完 config.jsonc 后用这个让配置生效）
#   status   查看运行状态
#   log      实时滚动查看日志（Ctrl+C 退出）
#
# 设计说明：
#  - 以「端口监听进程」为准来判断运行/停止，避免 uv run 父子进程导致的端口残留。
#  - 端口自动从 config/config.jsonc 的 api.port 读取，改端口无需改脚本。

# 切到脚本所在目录（即项目根），保证从任意路径调用都正确
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

# ---------- 基本路径与端口 ----------
CONFIG_FILE="config/config.jsonc"
PID_FILE="data/server.pid"
LOG_FILE="data/logs/server.out.log"
LOG_FILE_ABS="$SCRIPT_DIR/$LOG_FILE"
LAUNCHD_LABEL="${LEARNFLUX_LAUNCHD_LABEL:-com.learnflux.local}"
LEGACY_LAUNCHD_LABEL="com.codex.vta.devserver"
LAUNCH_AGENT_DIR="${LEARNFLUX_LAUNCH_AGENT_DIR:-${HOME}/Library/LaunchAgents}"
LAUNCH_AGENT_FILE="$LAUNCH_AGENT_DIR/$LAUNCHD_LABEL.plist"
PYTHON_BIN="${LEARNFLUX_PYTHON_BIN:-$(command -v python3 2>/dev/null || true)}"
UV_BIN="${LEARNFLUX_UV_BIN:-$(command -v uv 2>/dev/null || true)}"
STOP_TIMEOUT_SECONDS="${STOP_TIMEOUT_SECONDS:-10}"

# 从配置读取端口（取第一个 "port": NNNN，即 api.port），读取失败回退 8000
PORT="$(grep -oE '"port"[[:space:]]*:[[:space:]]*[0-9]+' "$CONFIG_FILE" 2>/dev/null | grep -oE '[0-9]+' | head -1)"
PORT="${PORT:-8000}"

# ---------- 输出着色（非终端时自动关闭）----------
if [ -t 1 ]; then
    C_OK=$'\033[32m'; C_WARN=$'\033[33m'; C_ERR=$'\033[31m'; C_INFO=$'\033[36m'; C_RST=$'\033[0m'
else
    C_OK=''; C_WARN=''; C_ERR=''; C_INFO=''; C_RST=''
fi
info() { printf '%s\n' "${C_INFO}==>${C_RST} $*"; }
ok()   { printf '%s\n' "${C_OK}[OK]${C_RST} $*"; }
warn() { printf '%s\n' "${C_WARN}[!!]${C_RST} $*"; }
err()  { printf '%s\n' "${C_ERR}[ERR]${C_RST} $*" >&2; }

# 返回监听该端口的进程 PID（可能多个），未运行则为空
listening_pids() { lsof -ti tcp:"$PORT" -sTCP:LISTEN 2>/dev/null; }

# 是否正在运行（以端口是否被监听为准）
is_running() { [ -n "$(listening_pids)" ]; }

# 返回仍存活的指定进程。旧服务关闭监听端口后，后台任务线程可能仍在退出。
alive_pids() {
    local pid
    for pid in "$@"; do
        kill -0 "$pid" 2>/dev/null && printf '%s\n' "$pid"
    done
}

# macOS 使用正式的用户 LaunchAgent，避免服务依附于启动它的终端或 Codex 会话。
use_launchd() {
    command -v launchctl >/dev/null 2>&1 || return 1
    [ "${LEARNFLUX_FORCE_LAUNCHD:-0}" = "1" ] || [ "$(uname -s)" = "Darwin" ]
}

launchd_domain() { printf 'gui/%s\n' "$(id -u)"; }

launchd_job_loaded() {
    local label="${1:-$LAUNCHD_LABEL}"
    use_launchd || return 1
    launchctl print "$(launchd_domain)/$label" >/dev/null 2>&1
}

install_launch_agent() {
    if [ -z "$PYTHON_BIN" ] || [ ! -x "$PYTHON_BIN" ]; then
        err "未找到可执行的 python3，无法生成 LaunchAgent 配置"
        return 1
    fi
    if [ -z "$UV_BIN" ] || [ ! -x "$UV_BIN" ]; then
        err "未找到可执行的 uv，无法启动服务"
        return 1
    fi

    mkdir -p "$LAUNCH_AGENT_DIR" "$(dirname "$LOG_FILE_ABS")"
    "$PYTHON_BIN" - \
        "$LAUNCH_AGENT_FILE" \
        "$LAUNCHD_LABEL" \
        "$SCRIPT_DIR" \
        "$UV_BIN" \
        "$LOG_FILE_ABS" \
        "${PATH:-/usr/bin:/bin:/usr/sbin:/sbin}" <<'PY'
import os
import plistlib
import sys

plist_path, label, working_dir, uv_bin, log_path, path_value = sys.argv[1:]
service = {
    "Label": label,
    "ProgramArguments": [uv_bin, "run", "python", "main.py", "--start"],
    "WorkingDirectory": working_dir,
    "RunAtLoad": True,
    "KeepAlive": True,
    "ThrottleInterval": 5,
    "ProcessType": "Interactive",
    "StandardOutPath": log_path,
    "StandardErrorPath": log_path,
    "EnvironmentVariables": {
        "PATH": path_value,
        "PYTHONUNBUFFERED": "1",
    },
}
temporary_path = f"{plist_path}.tmp"
with open(temporary_path, "wb") as handle:
    plistlib.dump(service, handle, sort_keys=False)
os.replace(temporary_path, plist_path)
PY
    chmod 644 "$LAUNCH_AGENT_FILE"
}

start_launchd_service() {
    local domain
    domain="$(launchd_domain)"
    install_launch_agent || return 1

    if launchd_job_loaded "$LAUNCHD_LABEL"; then
        launchctl kickstart -k "$domain/$LAUNCHD_LABEL" >/dev/null 2>&1
        return $?
    fi

    if launchctl bootstrap "$domain" "$LAUNCH_AGENT_FILE" >/dev/null 2>&1; then
        return 0
    fi

    # 清理由同名旧配置造成的半加载状态后重试一次。
    launchctl bootout "$domain/$LAUNCHD_LABEL" >/dev/null 2>&1 || true
    launchctl bootstrap "$domain" "$LAUNCH_AGENT_FILE" >/dev/null 2>&1
}

remove_launchd_jobs() {
    local domain label
    use_launchd || return 0
    domain="$(launchd_domain)"

    for label in "$LAUNCHD_LABEL" "$LEGACY_LAUNCHD_LABEL"; do
        if launchd_job_loaded "$label"; then
            warn "卸载后台服务: $label"
            launchctl bootout "$domain/$label" >/dev/null 2>&1 \
                || launchctl remove "$label" >/dev/null 2>&1 \
                || true
        fi
    done
    rm -f "$LAUNCH_AGENT_FILE"
}

# ---------- 启动 ----------
start() {
    if is_running; then
        warn "服务已在运行 (端口 $PORT, PID: $(listening_pids | tr '\n' ' '))"
        info "地址: http://localhost:$PORT"
        return 0
    fi

    mkdir -p "$(dirname "$LOG_FILE")" "$(dirname "$PID_FILE")"
    info "启动服务 (端口 $PORT) ..."

    if use_launchd; then
        info "使用 macOS LaunchAgent 保持服务持续运行"
        if ! start_launchd_service; then
            err "LaunchAgent 注册失败"
            return 1
        fi
        rm -f "$PID_FILE"
    else
        # 非 macOS 平台保留后台启动路径。
        nohup "$UV_BIN" run python main.py --start >>"$LOG_FILE" 2>&1 &
        echo $! > "$PID_FILE"
    fi

    # 等待端口就绪，最多约 30 秒
    local i=0
    while [ "$i" -lt 30 ]; do
        if is_running; then
            ok "启动成功  ->  http://localhost:$PORT"
            info "日志: ./server.sh log    （文件: ${LOG_FILE}）"
            return 0
        fi
        sleep 1
        i=$((i + 1))
    done

    err "启动超时，端口 $PORT 未就绪。最近日志如下："
    tail -n 30 "$LOG_FILE" 2>/dev/null
    if use_launchd; then
        remove_launchd_jobs
    elif [ -f "$PID_FILE" ]; then
        kill "$(cat "$PID_FILE")" 2>/dev/null
    fi
    rm -f "$PID_FILE"
    return 1
}

# ---------- 停止 ----------
stop() {
    local has_launchd=0
    if launchd_job_loaded "$LAUNCHD_LABEL" \
        || launchd_job_loaded "$LEGACY_LAUNCHD_LABEL" \
        || [ -f "$LAUNCH_AGENT_FILE" ]; then
        has_launchd=1
    fi

    if ! is_running && [ ! -f "$PID_FILE" ] && [ "$has_launchd" -eq 0 ]; then
        warn "服务未运行"
        return 0
    fi
    info "停止服务 ..."

    # 收集要终止的 PID：端口监听者（真正占用 8000 的 uvicorn 进程）+ PID 文件记录的父进程
    local pids
    pids="$(listening_pids)"
    if [ -f "$PID_FILE" ]; then
        pids="$pids
$(cat "$PID_FILE" 2>/dev/null)"
    fi
    pids="$(printf '%s\n' "$pids" | grep -E '^[0-9]+$' | sort -u)"

    # 先禁用 KeepAlive，再等待当前进程优雅退出。
    remove_launchd_jobs

    if [ -z "$pids" ]; then
        rm -f "$PID_FILE"
        if is_running; then
            warn "未找到运行中的进程"
            return 1
        fi
        ok "已停止"
        return 0
    fi

    # 1) 先发 SIGTERM 让 uvicorn 优雅退出（执行 shutdown 清理）
    printf '%s\n' "$pids" | xargs kill 2>/dev/null

    # 2) 等待旧进程完全退出；仅等待端口释放会让新旧实例短暂重叠，
    #    导致新实例跳过中断任务恢复。
    local i=0
    local alive
    while [ "$i" -lt "$STOP_TIMEOUT_SECONDS" ]; do
        alive="$(alive_pids $pids)"
        [ -n "$alive" ] || break
        sleep 1
        i=$((i + 1))
    done

    # 3) 仍未退出则强制结束已跟踪的父子进程
    alive="$(alive_pids $pids)"
    if [ -n "$alive" ]; then
        warn "优雅停止超时，强制结束 ..."
        printf '%s\n' "$alive" | xargs kill -9 2>/dev/null
        sleep 1
    fi

    rm -f "$PID_FILE"

    if is_running; then
        err "停止失败，端口 $PORT 仍被占用: $(listening_pids | tr '\n' ' ')"
        return 1
    fi
    ok "已停止"
}

# ---------- 状态 ----------
status() {
    if is_running; then
        ok "运行中  (端口 $PORT, PID: $(listening_pids | tr '\n' ' '))"
        info "地址: http://localhost:$PORT"
    elif launchd_job_loaded "$LAUNCHD_LABEL"; then
        warn "LaunchAgent 已注册，但端口 $PORT 尚未就绪"
        info "日志: $LOG_FILE"
    else
        warn "未运行"
    fi
}

# ---------- 日志 ----------
logs() {
    if [ ! -f "$LOG_FILE" ]; then
        warn "暂无日志文件: $LOG_FILE"
        return 0
    fi
    info "实时日志 (Ctrl+C 退出)  -  $LOG_FILE"
    tail -n 50 -f "$LOG_FILE"
}

# ---------- 命令分发 ----------
case "${1:-}" in
    start)        start ;;
    stop)         stop ;;
    restart)      stop; echo; start ;;
    status)       status ;;
    log|logs)     logs ;;
    *)
        printf '用法: %s {start|stop|restart|status|log}\n\n' "$0"
        printf '  start    后台启动服务\n'
        printf '  stop     停止服务\n'
        printf '  restart  重启（改完配置后用）\n'
        printf '  status   查看运行状态\n'
        printf '  log      实时查看日志\n'
        exit 1
        ;;
esac
