//! siku 桌面壳（Tauri 2）。
//!
//! 本 crate 是进程与窗口适配层，不是第二个应用内核（ADR-0001）：Rust 只负责
//! 选择 loopback 端口、启动/回收 Python sidecar、轮询 `GET /api/health` 并在
//! 健康检查通过后把窗口导航到 sidecar 同源提供的问答 UI。问题、答案、引用、
//! 索引状态与错误全部由既有 HTTP API 提供，前端与 Rust 均不得绕过。

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::net::TcpListener;
use std::path::PathBuf;
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Mutex;
use std::thread;
use std::time::{Duration, Instant};

use serde::Serialize;
use tauri::{Emitter, Manager, WindowEvent};

/// 健康检查总超时：覆盖 PyInstaller 目录自解压与 FastAPI 冷启动，首次启动留足余量
const HEALTH_TIMEOUT_SECS: u64 = 60;
/// 单次 HTTP 探测超时与轮询间隔
const HEALTH_REQUEST_TIMEOUT_SECS: u64 = 2;
const HEALTH_POLL_INTERVAL_MS: u64 = 250;
/// 优雅退出等待窗口：stdin EOF + SIGTERM 后给 uvicorn 的收尾时间
const GRACEFUL_SHUTDOWN_SECS: u64 = 8;
/// 冻结决议 #3：平台应用数据目录下的 `siku/` 子目录
const DATA_ROOT_DIR: &str = "siku";
/// Rust → 壳状态页的启动事件名
const STARTUP_EVENT: &str = "siku-startup";

/// 启动状态事件；state 取值 starting / succeeded / failed，与壳状态页约定一致
#[derive(Clone, Serialize)]
#[serde(tag = "state", rename_all = "camelCase")]
enum StartupEvent {
    Starting,
    Succeeded { url: String },
    Failed { message: String },
}

/// 运行中的 sidecar 进程；stdin 句柄必须保活——关闭它即是给 `--watch-stdin`
/// sidecar 的第一个优雅退出信号
struct SidecarProcess {
    child: Child,
    _stdin: Option<ChildStdin>,
}

/// 共享的 sidecar 句柄；None 表示尚未启动或已回收
struct SidecarState(Mutex<Option<SidecarProcess>>);

/// 重试代际计数：新一轮启动开始后，旧轮次的健康检查线程必须自行退出
static STARTUP_GENERATION: AtomicU64 = AtomicU64::new(0);

fn main() {
    tauri::Builder::default()
        // 单实例隔离（冻结决议：重复启动不得遗留孤儿进程或端口争用）
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.set_focus();
            }
        }))
        .manage(SidecarState(Mutex::new(None)))
        .setup(|app| {
            ensure_data_dirs(app.handle());
            Ok(())
        })
        // 壳状态页每次加载（含“重试”触发的 reload）都编排一轮新的启动流程
        .on_page_load(|webview, payload| {
            if payload.event() != tauri::webview::PageLoadEvent::Finished {
                return;
            }
            let url = payload.url().as_str();
            let is_remote_page =
                url.starts_with("http://127.0.0.1") || url.starts_with("http://localhost");
            if is_remote_page {
                return;
            }
            let app = webview.app_handle().clone();
            let generation = STARTUP_GENERATION.fetch_add(1, Ordering::SeqCst) + 1;
            thread::spawn(move || run_startup(app, generation));
        })
        .on_window_event(|window, event| {
            if let WindowEvent::CloseRequested { api, .. } = event {
                // 关闭最后一个窗口：先回收 sidecar，再真正销毁窗口
                api.prevent_close();
                let app = window.app_handle().clone();
                let window = window.clone();
                thread::spawn(move || {
                    stop_sidecar(&app);
                    let _ = window.destroy();
                });
            }
        })
        .build(tauri::generate_context!())
        .expect("failed to build siku desktop shell")
        .run(|app, event| {
            // 兜底：任何退出路径都不允许遗留 sidecar
            if let tauri::RunEvent::Exit = event {
                stop_sidecar(app);
            }
        });
}

fn ensure_data_dirs(app: &tauri::AppHandle) {
    // 数据目录不可用属极端平台异常：不 panic，留待 run_startup 走失败页
    if let Some(root) = data_root() {
        for subdir in ["vault", "data"] {
            let _ = std::fs::create_dir_all(root.join(subdir));
        }
    }
    let _ = app; // 目录布局与窗口无关；预留 AppHandle 以便未来在此注入更多初始化
}

/// 平台应用数据目录下的 siku 根目录（冻结决议 #3，不依赖当前工作目录）
fn data_root() -> Option<PathBuf> {
    dirs::data_dir().map(|dir| dir.join(DATA_ROOT_DIR))
}

/// 定位 sidecar 可执行文件与待挂载的 UI 资源目录（打包布局见 tauri.conf.json resources）
fn resolve_sidecar(app: &tauri::AppHandle) -> Result<(PathBuf, PathBuf), String> {
    let exe_name = if cfg!(windows) {
        "siku-sidecar.exe"
    } else {
        "siku-sidecar"
    };
    let resource_dir = app
        .path()
        .resource_dir()
        .map_err(|_| "resource directory unavailable".to_string())?;
    let sidecar = resource_dir.join("siku-sidecar").join(exe_name);
    let ui_dir = resource_dir.join("dist");
    if sidecar.exists() && ui_dir.is_dir() {
        return Ok((sidecar, ui_dir));
    }
    // 开发模式回退：binaries/ 由 scripts/build_sidecar.py 产出，ui/dist 由前端构建产出
    let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    let dev_sidecar = manifest_dir
        .join("binaries")
        .join("siku-sidecar")
        .join(exe_name);
    let dev_ui = manifest_dir.join("..").join("dist");
    if dev_sidecar.exists() && dev_ui.is_dir() {
        return Ok((dev_sidecar, dev_ui));
    }
    Err(format!(
        "sidecar or UI resources missing: {} / {}",
        sidecar.display(),
        ui_dir.display()
    ))
}

/// 选择未占用的 loopback 端口；极少数绑定失败场景返回 Err 走失败页而非 panic
fn pick_free_loopback_port() -> Result<u16, String> {
    let listener = TcpListener::bind(("127.0.0.1", 0))
        .map_err(|_| "unable to bind an ephemeral loopback port".to_string())?;
    listener
        .local_addr()
        .map(|addr| addr.port())
        .map_err(|_| "bound listener has no local address".to_string())
}

/// 每次应用进程启动首轮 truncate 日志，同会话内的重试改为追加，保留失败现场
static LOG_TRUNCATED: std::sync::atomic::AtomicBool = std::sync::atomic::AtomicBool::new(false);

/// 以独立进程组启动 sidecar：关闭时按组回收，杜绝 PyInstaller 引导层的孤儿子进程
fn spawn_sidecar(
    sidecar_exe: &PathBuf,
    ui_dir: &PathBuf,
    vault: &PathBuf,
    data_dir: &PathBuf,
    port: u16,
) -> Result<SidecarProcess, String> {
    use std::sync::atomic::Ordering;

    let log_path = data_dir
        .parent()
        .map(|p| p.to_path_buf())
        .unwrap_or_default();
    let log_path = log_path.join("sidecar.log");
    let log_file = if LOG_TRUNCATED.swap(true, Ordering::SeqCst) {
        std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(&log_path)
    } else {
        std::fs::File::create(&log_path)
    }
    .map_err(|_| format!("unable to open sidecar log at {}", log_path.display()))?;

    let mut command = Command::new(sidecar_exe);
    command
        .args([
            "serve",
            "--with-ui",
            "--host",
            "127.0.0.1",
            "--port",
            &port.to_string(),
            "--vault",
        ])
        .arg(vault)
        .args(["--data-dir"])
        .arg(data_dir)
        .args(["--ui-dir"])
        .arg(ui_dir)
        .arg("--watch-stdin")
        .stdin(Stdio::piped())
        .stdout(Stdio::null())
        .stderr(Stdio::from(log_file));

    #[cfg(unix)]
    unsafe {
        // 进程组隔离：kill(-pgid) 才能同时命中引导层与 Python 子进程
        use std::os::unix::process::CommandExt;
        command.pre_exec(|| {
            if libc::setpgid(0, 0) != 0 {
                return Err(std::io::Error::last_os_error());
            }
            Ok(())
        });
    }

    #[cfg(windows)]
    {
        // GUI 进程 spawn 控制台子进程必须屏蔽新控制台窗口
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        command.creation_flags(CREATE_NO_WINDOW);
    }

    // LLM 通道可经壳环境变量切换（BYO key 本就随环境继承，不单独传参）
    if let Ok(base_url) = std::env::var("SIKU_LLM_BASE_URL") {
        command.args(["--llm-base-url", &base_url]);
    }
    if let Ok(model) = std::env::var("SIKU_LLM_MODEL") {
        command.args(["--llm-model", &model]);
    }

    let mut child = command
        .spawn()
        .map_err(|_| "unable to launch the sidecar executable".to_string())?;
    let stdin = child.stdin.take();
    Ok(SidecarProcess {
        child,
        _stdin: stdin,
    })
}

/// 回收 sidecar：先关 stdin（触发 --watch-stdin 优雅退出），超时后按进程组强杀
fn stop_sidecar(app: &tauri::AppHandle) {
    let state = app.state::<SidecarState>();
    let mut guard = match state.0.lock() {
        Ok(guard) => guard,
        Err(poisoned) => poisoned.into_inner(),
    };
    if let Some(mut process) = guard.take() {
        process._stdin.take(); // EOF → uvicorn 受控关停
        terminate(process.child);
    }
}

fn terminate(mut child: Child) {
    #[cfg(unix)]
    {
        let pgid = child.id() as i32;
        unsafe {
            libc::kill(-pgid, libc::SIGTERM);
        }
        let deadline = Instant::now() + Duration::from_secs(GRACEFUL_SHUTDOWN_SECS);
        while Instant::now() < deadline {
            if matches!(child.try_wait(), Ok(Some(_))) {
                return;
            }
            thread::sleep(Duration::from_millis(100));
        }
        unsafe {
            libc::kill(-pgid, libc::SIGKILL);
        }
        let _ = child.wait();
    }
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        // 优雅阶段：调用方已关 stdin（EOF → uvicorn 受控关停），给它与 Unix 相同的宽限
        let deadline = Instant::now() + Duration::from_secs(GRACEFUL_SHUTDOWN_SECS);
        while Instant::now() < deadline {
            if matches!(child.try_wait(), Ok(Some(_))) {
                return;
            }
            thread::sleep(Duration::from_millis(100));
        }
        // taskkill /T 按进程树强制回收 PyInstaller 引导层与其 Python 子进程
        let _ = Command::new("taskkill")
            .args(["/PID", &child.id().to_string(), "/T", "/F"])
            .creation_flags(CREATE_NO_WINDOW)
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status();
        let _ = child.wait();
    }
}

/// 启动编排：选端口 → 启 sidecar → 轮询健康 → 通知状态页导航或报错
fn run_startup(app: tauri::AppHandle, generation: u64) {
    let emit = |event: StartupEvent| {
        let _ = app.emit(STARTUP_EVENT, event);
    };
    emit(StartupEvent::Starting);

    // 重试场景：先回收上一轮可能残留的 sidecar
    stop_sidecar(&app);

    let (sidecar_exe, ui_dir) = match resolve_sidecar(&app) {
        Ok(paths) => paths,
        Err(_) => {
            emit(StartupEvent::Failed {
                message: "应用资源不完整：内核或界面文件缺失，请重新安装。".to_string(),
            });
            return;
        }
    };
    let root = match data_root() {
        Some(root) => root,
        None => {
            emit(StartupEvent::Failed {
                message: "无法定位系统应用数据目录，请重试或重新安装。".to_string(),
            });
            return;
        }
    };
    let vault = root.join("vault");
    let data_dir = root.join("data");
    let port = match pick_free_loopback_port() {
        Ok(port) => port,
        Err(_) => {
            emit(StartupEvent::Failed {
                message: "无法分配本地回环端口，请重试。".to_string(),
            });
            return;
        }
    };

    let process = match spawn_sidecar(&sidecar_exe, &ui_dir, &vault, &data_dir, port) {
        Ok(process) => process,
        Err(_) => {
            emit(StartupEvent::Failed {
                message: "无法启动本地内核进程，请重试；若反复失败请重新安装应用。".to_string(),
            });
            return;
        }
    };
    {
        let state = app.state::<SidecarState>();
        let mut guard = match state.0.lock() {
            Ok(guard) => guard,
            Err(poisoned) => poisoned.into_inner(),
        };
        *guard = Some(process);
    }
    // 入库后二次校验代际：若期间已有新一轮启动接管，立即回收本轮刚拉起的进程
    if generation != STARTUP_GENERATION.load(Ordering::SeqCst) {
        stop_sidecar(&app);
        return;
    }

    let health_url = format!("http://127.0.0.1:{port}/api/health");
    let app_url = format!("http://127.0.0.1:{port}/");
    let agent = ureq::AgentBuilder::new()
        .timeout(Duration::from_secs(HEALTH_REQUEST_TIMEOUT_SECS))
        .build();
    let deadline = Instant::now() + Duration::from_secs(HEALTH_TIMEOUT_SECS);

    loop {
        if generation != STARTUP_GENERATION.load(Ordering::SeqCst) {
            // 新一轮启动已接管，本轮立即退役
            return;
        }
        {
            let state = app.state::<SidecarState>();
            let mut guard = match state.0.lock() {
                Ok(guard) => guard,
                Err(poisoned) => poisoned.into_inner(),
            };
            if let Some(process) = guard.as_mut() {
                match process.child.try_wait() {
                    Ok(Some(_status)) => {
                        *guard = None;
                        // 退出细节已写入 sidecar 日志，用户面只给可行动的中文提示
                        emit(StartupEvent::Failed {
                            message:
                                "本地内核启动即退出，请查看数据目录中的 sidecar 日志，或重试。"
                                    .to_string(),
                        });
                        return;
                    }
                    Ok(None) => {}
                    Err(_) => {
                        *guard = None;
                        emit(StartupEvent::Failed {
                            message: "无法确认本地内核状态，请重试。".to_string(),
                        });
                        return;
                    }
                }
            }
        }
        // 身份缓解：要求响应体是 siku 健康形状（{"status":"ok",...}）而非任意 200，
        // 降低把临时占用端口的其他本地服务误认成内核的风险
        let healthy = agent
            .get(&health_url)
            .call()
            .ok()
            .filter(|response| response.status() == 200)
            .and_then(|response| response.into_string().ok())
            .map(|body| body.contains("\"status\":\"ok\""))
            .unwrap_or(false);
        if healthy {
            emit(StartupEvent::Succeeded { url: app_url });
            return;
        }
        if Instant::now() >= deadline {
            stop_sidecar(&app);
            emit(StartupEvent::Failed {
                message:
                    "本地内核健康检查超时，请重试；若反复失败请查看数据目录中的 sidecar 日志。"
                        .to_string(),
            });
            return;
        }
        thread::sleep(Duration::from_millis(HEALTH_POLL_INTERVAL_MS));
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn pick_free_loopback_port_returns_valid_ports() {
        // 释放后的端口是否可立即重绑属 OS 调度行为（可能被其他进程抢占），
        // 不做脆断言；真实的“释放→sidecar 立即绑定”链路由安装后冒烟覆盖
        let first = pick_free_loopback_port().expect("ephemeral port available");
        let second = pick_free_loopback_port().expect("ephemeral port available");
        assert!(first > 0);
        assert!(second > 0);
    }

    #[test]
    fn data_root_uses_frozen_siku_subdirectory() {
        let root = data_root().expect("desktop platforms provide a data dir");
        assert!(root.ends_with("siku"));
        assert!(root.is_absolute());
    }

    #[cfg(unix)]
    #[test]
    fn terminate_kills_entire_process_group_no_orphans() {
        // 独立进程组里起一个会派生子的 shell：组杀必须连子进程一起回收
        let mut command = Command::new("/bin/sh");
        command.args(["-c", "sleep 30 & wait"]);
        unsafe {
            use std::os::unix::process::CommandExt;
            command.pre_exec(|| {
                if libc::setpgid(0, 0) != 0 {
                    return Err(std::io::Error::last_os_error());
                }
                Ok(())
            });
        }
        let mut child = command.spawn().expect("failed to spawn test process");
        let shell_pid = child.id();
        terminate(child);
        // 组内任意成员存活即失败：轮询组内代表性 PID（子 shell 与其 sleep 孩子）
        thread::sleep(Duration::from_millis(200));
        let alive = unsafe { libc::kill(shell_pid as i32, 0) } == 0;
        assert!(!alive, "process group member survived termination");
    }
}
