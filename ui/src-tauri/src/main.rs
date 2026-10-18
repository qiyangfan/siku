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
use std::sync::{Arc, Condvar, Mutex};
use std::thread;
use std::time::{Duration, Instant};

use serde::Serialize;
use tauri::{Emitter, Manager, WindowEvent};

/// 健康检查总超时：覆盖 PyInstaller 目录自解压与 FastAPI 冷启动，首次启动留足余量
const HEALTH_TIMEOUT_SECS: u64 = 60;
/// 单次 HTTP 探测超时与轮询间隔
const HEALTH_REQUEST_TIMEOUT_SECS: u64 = 2;
const HEALTH_POLL_INTERVAL_MS: u64 = 250;
/// 运行期间的健康检查间隔与故障阈值，短暂抖动不触发恢复页
const MONITOR_INTERVAL_SECS: u64 = 2;
const HEALTH_FAILURE_LIMIT: u8 = 5;
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
    generation: u64,
    child: Child,
    _stdin: Option<ChildStdin>,
    #[cfg(windows)]
    _job: std::os::windows::io::OwnedHandle,
}

/// 启动代际与 sidecar 句柄必须在同一把锁下更新，避免过期启动覆盖新进程。
#[derive(Default)]
struct SidecarRegistry {
    generation: u64,
    process: Option<SidecarProcess>,
    closing: bool,
}

/// 跟踪启动和监视线程；关窗时等待它们完成持有中的进程清理。
#[derive(Default)]
struct LifecycleTracker {
    active_workers: Mutex<usize>,
    idle: Condvar,
}

impl LifecycleTracker {
    fn register(self: &Arc<Self>) -> LifecycleWorker {
        let mut active_workers = match self.active_workers.lock() {
            Ok(guard) => guard,
            Err(poisoned) => poisoned.into_inner(),
        };
        *active_workers = active_workers
            .checked_add(1)
            .expect("lifecycle worker count exhausted");
        LifecycleWorker {
            tracker: Arc::clone(self),
        }
    }

    fn wait_for_idle(&self) {
        let mut active_workers = match self.active_workers.lock() {
            Ok(guard) => guard,
            Err(poisoned) => poisoned.into_inner(),
        };
        while *active_workers > 0 {
            active_workers = match self.idle.wait(active_workers) {
                Ok(guard) => guard,
                Err(poisoned) => poisoned.into_inner(),
            };
        }
    }
}

struct LifecycleWorker {
    tracker: Arc<LifecycleTracker>,
}

impl Drop for LifecycleWorker {
    fn drop(&mut self) {
        let mut active_workers = match self.tracker.active_workers.lock() {
            Ok(guard) => guard,
            Err(poisoned) => poisoned.into_inner(),
        };
        *active_workers = active_workers
            .checked_sub(1)
            .expect("lifecycle worker count underflow");
        if *active_workers == 0 {
            self.tracker.idle.notify_all();
        }
    }
}

impl SidecarRegistry {
    fn advance_generation(&mut self) -> u64 {
        self.generation = self
            .generation
            .checked_add(1)
            .expect("startup generation exhausted");
        self.generation
    }

    fn next_generation(&mut self) -> Option<u64> {
        if self.closing {
            return None;
        }
        Some(self.advance_generation())
    }

    fn begin_shutdown(&mut self) -> u64 {
        if !self.closing {
            self.advance_generation();
            self.closing = true;
        }
        self.generation
    }

    /// 只允许一个窗口关闭处理器取得清理任务；重复关闭事件由首个任务收尾。
    fn try_begin_shutdown(&mut self) -> Option<u64> {
        if self.closing {
            return None;
        }
        Some(self.begin_shutdown())
    }

    fn is_current(&self, generation: u64) -> bool {
        self.generation == generation
    }

    fn install_if_current(
        &mut self,
        generation: u64,
        process: SidecarProcess,
    ) -> Result<Option<SidecarProcess>, SidecarProcess> {
        if self.closing
            || !self.is_current(generation)
            || self
                .process
                .as_ref()
                .is_some_and(|current| current.generation >= generation)
        {
            return Err(process);
        }
        Ok(self.process.replace(process))
    }

    fn take_previous(&mut self, generation: u64) -> Option<SidecarProcess> {
        if !self.is_current(generation)
            || !self
                .process
                .as_ref()
                .is_some_and(|process| process.generation < generation)
        {
            return None;
        }
        self.process.take()
    }

    fn take_generation(&mut self, generation: u64) -> Option<SidecarProcess> {
        if !self.is_current(generation)
            || self
                .process
                .as_ref()
                .is_none_or(|process| process.generation != generation)
        {
            return None;
        }
        self.process.take()
    }
}

/// 共享 sidecar 状态；None 表示尚未启动或已回收。
struct SidecarState {
    registry: Mutex<SidecarRegistry>,
    lifecycle: Arc<LifecycleTracker>,
}

impl Default for SidecarState {
    fn default() -> Self {
        Self {
            registry: Mutex::new(SidecarRegistry::default()),
            lifecycle: Arc::new(LifecycleTracker::default()),
        }
    }
}

fn main() {
    tauri::Builder::default()
        // 单实例隔离（冻结决议：重复启动不得遗留孤儿进程或端口争用）
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.set_focus();
            }
        }))
        .manage(SidecarState::default())
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
            if is_remote_page || is_recovery_url(url) {
                return;
            }
            let shell_page_url = strip_shell_page_query(url);
            let app = webview.app_handle().clone();
            let Some((generation, worker)) = next_startup_generation(&app) else {
                return;
            };
            thread::spawn(move || {
                let _worker = worker;
                run_startup(app, generation, shell_page_url);
            });
        })
        .on_window_event(|window, event| {
            if let WindowEvent::CloseRequested { api, .. } = event {
                // 关闭最后一个窗口：先回收 sidecar，再真正销毁窗口
                api.prevent_close();
                let app = window.app_handle().clone();
                let window = window.clone();
                let Some(generation) = begin_shutdown(&app) else {
                    return;
                };
                thread::spawn(move || {
                    stop_previous_sidecar(&app, generation);
                    wait_for_lifecycle_workers(&app);
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
    generation: u64,
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

    #[cfg(windows)]
    let job = create_sidecar_job()?;

    let mut child = command
        .spawn()
        .map_err(|_| "unable to launch the sidecar executable".to_string())?;

    #[cfg(windows)]
    if let Err(error) = assign_sidecar_to_job(&job, &child) {
        // 赋组失败时尽可能先清理刚启动的进程，再报告启动失败。
        match child.try_wait() {
            Ok(Some(_status)) => {}
            Ok(None) => kill_process_tree(child.id()),
            Err(_) => {
                let _ = child.kill();
            }
        }
        let _ = child.wait();
        return Err(format!("unable to track sidecar process tree: {error}"));
    }

    let stdin = child.stdin.take();
    Ok(SidecarProcess {
        generation,
        child,
        _stdin: stdin,
        #[cfg(windows)]
        _job: job,
    })
}

#[cfg(windows)]
fn create_sidecar_job() -> Result<std::os::windows::io::OwnedHandle, String> {
    use std::os::windows::io::{AsRawHandle, FromRawHandle, OwnedHandle};
    use windows_sys::Win32::System::JobObjects::{
        CreateJobObjectW, JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE, JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
        JobObjectExtendedLimitInformation, SetInformationJobObject,
    };

    unsafe {
        let raw_job = CreateJobObjectW(std::ptr::null(), std::ptr::null());
        if raw_job.is_null() {
            return Err("unable to create sidecar job object".to_string());
        }
        let job = OwnedHandle::from_raw_handle(raw_job as _);
        let mut limits = JOBOBJECT_EXTENDED_LIMIT_INFORMATION::default();
        limits.BasicLimitInformation.LimitFlags |= JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        let configured = SetInformationJobObject(
            job.as_raw_handle() as _,
            JobObjectExtendedLimitInformation,
            (&limits as *const JOBOBJECT_EXTENDED_LIMIT_INFORMATION).cast(),
            std::mem::size_of_val(&limits) as u32,
        );
        if configured == 0 {
            return Err("unable to configure sidecar job object".to_string());
        }
        Ok(job)
    }
}

#[cfg(windows)]
fn assign_sidecar_to_job(
    job: &std::os::windows::io::OwnedHandle,
    child: &Child,
) -> Result<(), String> {
    use std::os::windows::io::AsRawHandle;
    use windows_sys::Win32::System::JobObjects::AssignProcessToJobObject;

    let assigned =
        unsafe { AssignProcessToJobObject(job.as_raw_handle() as _, child.as_raw_handle() as _) };
    if assigned == 0 {
        Err("unable to assign sidecar to job object".to_string())
    } else {
        Ok(())
    }
}

fn next_startup_generation(app: &tauri::AppHandle) -> Option<(u64, LifecycleWorker)> {
    let state = app.state::<SidecarState>();
    let mut registry = match state.registry.lock() {
        Ok(guard) => guard,
        Err(poisoned) => poisoned.into_inner(),
    };
    let generation = registry.next_generation()?;
    let worker = state.lifecycle.register();
    Some((generation, worker))
}

fn register_monitor_worker(app: &tauri::AppHandle, generation: u64) -> Option<LifecycleWorker> {
    let state = app.state::<SidecarState>();
    let registry = match state.registry.lock() {
        Ok(guard) => guard,
        Err(poisoned) => poisoned.into_inner(),
    };
    if registry.closing || !registry.is_current(generation) {
        return None;
    }
    Some(state.lifecycle.register())
}

fn wait_for_lifecycle_workers(app: &tauri::AppHandle) {
    let state = app.state::<SidecarState>();
    state.lifecycle.wait_for_idle();
}

fn begin_shutdown(app: &tauri::AppHandle) -> Option<u64> {
    let state = app.state::<SidecarState>();
    let mut registry = match state.registry.lock() {
        Ok(guard) => guard,
        Err(poisoned) => poisoned.into_inner(),
    };
    registry.try_begin_shutdown()
}

fn is_current_generation(app: &tauri::AppHandle, generation: u64) -> bool {
    let state = app.state::<SidecarState>();
    let registry = match state.registry.lock() {
        Ok(guard) => guard,
        Err(poisoned) => poisoned.into_inner(),
    };
    registry.is_current(generation)
}

fn emit_startup_event(app: &tauri::AppHandle, generation: u64, event: StartupEvent) -> bool {
    let state = app.state::<SidecarState>();
    let registry = match state.registry.lock() {
        Ok(guard) => guard,
        Err(poisoned) => poisoned.into_inner(),
    };
    if !registry.is_current(generation) {
        return false;
    }
    let _ = app.emit(STARTUP_EVENT, event);
    true
}

/// 仅在代际仍有效时回收之前启动的 sidecar。
fn stop_previous_sidecar(app: &tauri::AppHandle, generation: u64) -> bool {
    let process = {
        let state = app.state::<SidecarState>();
        let mut registry = match state.registry.lock() {
            Ok(guard) => guard,
            Err(poisoned) => poisoned.into_inner(),
        };
        if !registry.is_current(generation) {
            return false;
        }
        registry.take_previous(generation)
    };
    if let Some(process) = process {
        terminate_sidecar(process);
    }
    true
}

/// 仅回收指定启动代际的 sidecar，避免旧监视器误杀用户已重新启动的进程。
fn stop_sidecar_generation(app: &tauri::AppHandle, generation: u64) -> bool {
    let process = {
        let state = app.state::<SidecarState>();
        let mut registry = match state.registry.lock() {
            Ok(guard) => guard,
            Err(poisoned) => poisoned.into_inner(),
        };
        registry.take_generation(generation)
    };
    if let Some(process) = process {
        terminate_sidecar(process);
        return true;
    }
    false
}

fn install_sidecar(app: &tauri::AppHandle, generation: u64, process: SidecarProcess) -> bool {
    let previous = {
        let state = app.state::<SidecarState>();
        let mut registry = match state.registry.lock() {
            Ok(guard) => guard,
            Err(poisoned) => poisoned.into_inner(),
        };
        match registry.install_if_current(generation, process) {
            Ok(previous) => previous,
            Err(process) => {
                drop(registry);
                terminate_sidecar(process);
                return false;
            }
        }
    };
    if let Some(previous) = previous {
        terminate_sidecar(previous);
    }
    true
}

/// 应用退出兜底：回收当前已登记的 sidecar。
fn stop_sidecar(app: &tauri::AppHandle) {
    let Some(generation) = begin_shutdown(app) else {
        return;
    };
    stop_previous_sidecar(app, generation);
    wait_for_lifecycle_workers(app);
    stop_previous_sidecar(app, generation);
}

fn terminate_sidecar(mut process: SidecarProcess) {
    process._stdin.take(); // EOF → uvicorn 受控关停
    terminate(process.child);
    // Windows 的 Job Object 在此作用域结束时关闭；kill-on-close 会收回全部后代进程。
}

fn terminate(child: Child) {
    terminate_with_grace(child, Duration::from_secs(GRACEFUL_SHUTDOWN_SECS));
}

fn terminate_with_grace(mut child: Child, graceful_shutdown: Duration) {
    #[cfg(unix)]
    {
        let pgid = child.id() as i32;
        unsafe {
            libc::kill(-pgid, libc::SIGTERM);
        }
        let deadline = Instant::now() + graceful_shutdown;
        while Instant::now() < deadline {
            let _ = child.try_wait();
            if !process_group_exists(pgid) {
                let _ = child.wait();
                return;
            }
            thread::sleep(Duration::from_millis(100));
        }
        kill_process_tree(pgid as u32);
        let _ = child.wait();
    }
    #[cfg(windows)]
    {
        // 优雅阶段：调用方已关 stdin（EOF → uvicorn 受控关停），给它与 Unix 相同的宽限
        let deadline = Instant::now() + graceful_shutdown;
        let mut exited = false;
        while Instant::now() < deadline {
            match child.try_wait() {
                Ok(Some(_)) => {
                    exited = true;
                    break;
                }
                Err(_) => break,
                Ok(None) => {}
            }
            thread::sleep(Duration::from_millis(100));
        }
        if exited {
            let _ = child.wait();
        } else if child.kill().is_ok() {
            let _ = child.wait();
        }
        // 若根进程句柄无法单独结束它，调用返回后释放的 Job Object 会终止整组进程。
    }
}

#[cfg(unix)]
fn process_group_exists(process_group_id: i32) -> bool {
    let result = unsafe { libc::kill(-process_group_id, 0) };
    result == 0 || std::io::Error::last_os_error().raw_os_error() == Some(libc::EPERM)
}

/// 回收指定 sidecar 根进程所在的进程树；适用于根进程已退出但后代仍存活的场景。
#[cfg(unix)]
fn kill_process_tree(process_id: u32) {
    unsafe {
        libc::kill(-(process_id as i32), libc::SIGKILL);
    }
}

/// 赋组失败时回收仍由本壳直接持有的 Windows sidecar 进程树。
#[cfg(windows)]
fn kill_process_tree(process_id: u32) {
    use std::os::windows::process::CommandExt;
    const CREATE_NO_WINDOW: u32 = 0x0800_0000;
    let _ = Command::new("taskkill")
        .args(["/PID", &process_id.to_string(), "/T", "/F"])
        .creation_flags(CREATE_NO_WINDOW)
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status();
}

/// 启动编排：选端口 → 启 sidecar → 轮询健康 → 通知状态页导航或报错
fn run_startup(app: tauri::AppHandle, generation: u64, shell_page_url: String) {
    let emit = |event: StartupEvent| emit_startup_event(&app, generation, event);
    if !emit(StartupEvent::Starting) {
        return;
    }

    // 重试场景：先回收上一轮可能残留的 sidecar
    if !stop_previous_sidecar(&app, generation) {
        return;
    }

    let (sidecar_exe, ui_dir) = match resolve_sidecar(&app) {
        Ok(paths) => paths,
        Err(_) => {
            emit(StartupEvent::Failed {
                message: "应用资源不完整：本地服务或界面文件缺失，请重新安装。".to_string(),
            });
            return;
        }
    };
    let root = match data_root() {
        Some(root) => root,
        None => {
            emit(StartupEvent::Failed {
                message: "无法定位系统应用数据目录，请重新启动或重新安装。".to_string(),
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
                message: "无法分配本地服务端口，请重新启动。".to_string(),
            });
            return;
        }
    };

    let process = match spawn_sidecar(&sidecar_exe, &ui_dir, &vault, &data_dir, port, generation) {
        Ok(process) => process,
        Err(_) => {
            emit(StartupEvent::Failed {
                message: "无法启动本地服务，请重试；若反复失败请重新安装应用。".to_string(),
            });
            return;
        }
    };
    // 只有当前代际能登记进程；过期线程只回收自己刚启动的进程。
    if !install_sidecar(&app, generation, process) {
        return;
    }

    let health_url = format!("http://127.0.0.1:{port}/api/health");
    let app_url = format!("http://127.0.0.1:{port}/");
    let agent = health_check_agent();
    let deadline = Instant::now() + Duration::from_secs(HEALTH_TIMEOUT_SECS);

    loop {
        if !is_current_generation(&app, generation) {
            // 新一轮启动已接管，本轮立即退役
            return;
        }
        let process_status = {
            let state = app.state::<SidecarState>();
            let mut registry = match state.registry.lock() {
                Ok(guard) => guard,
                Err(poisoned) => poisoned.into_inner(),
            };
            if !registry.is_current(generation) {
                return;
            }
            let Some(process) = registry.process.as_mut() else {
                return;
            };
            if process.generation != generation {
                return;
            }
            let status = process.child.try_wait();
            match status {
                Ok(Some(_status)) => registry.process.take().map(|process| (true, process)),
                Err(_) => registry.process.take().map(|process| (false, process)),
                Ok(None) => None,
            }
        };
        if let Some((exited, process)) = process_status {
            // 回收整棵进程树；Windows 同时释放 Job Object 句柄。
            terminate_sidecar(process);
            if exited {
                emit(StartupEvent::Failed {
                    message:
                        "本地服务启动后立即退出，请查看数据目录中的 sidecar 日志，或重新启动。"
                            .to_string(),
                });
            } else {
                emit(StartupEvent::Failed {
                    message: "无法确认本地服务状态，请重新启动。".to_string(),
                });
            }
            return;
        }
        // 身份缓解：要求响应体是 siku 健康形状（{"status":"ok",...}）而非任意 200，
        // 降低把临时占用端口的其他本地服务误认为 siku 服务的风险
        let healthy = health_is_ok(&agent, &health_url);
        if healthy {
            if !emit(StartupEvent::Succeeded { url: app_url }) {
                return;
            }
            let Some(worker) = register_monitor_worker(&app, generation) else {
                return;
            };
            let app = app.clone();
            thread::spawn(move || {
                let _worker = worker;
                monitor_sidecar(app, generation, shell_page_url, health_url);
            });
            return;
        }
        if Instant::now() >= deadline {
            if stop_sidecar_generation(&app, generation) {
                emit(StartupEvent::Failed {
                    message:
                        "本地服务健康检查超时，请重新启动；若反复失败请查看数据目录中的 sidecar 日志。"
                            .to_string(),
                });
            }
            return;
        }
        thread::sleep(Duration::from_millis(HEALTH_POLL_INTERVAL_MS));
    }
}

/// 在健康检查通过后持续监视壳启动的 sidecar，故障时返回壳内置恢复页。
fn monitor_sidecar(
    app: tauri::AppHandle,
    generation: u64,
    shell_page_url: String,
    health_url: String,
) {
    let agent = health_check_agent();
    let mut consecutive_failures = 0_u8;

    loop {
        if !is_current_generation(&app, generation) {
            return;
        }

        let process_status = {
            let state = app.state::<SidecarState>();
            let mut registry = match state.registry.lock() {
                Ok(guard) => guard,
                Err(poisoned) => poisoned.into_inner(),
            };
            if !registry.is_current(generation) {
                return;
            }
            let Some(process) = registry.process.as_mut() else {
                return;
            };
            if process.generation != generation {
                return;
            }
            let status = process.child.try_wait();
            match status {
                Ok(Some(_)) | Err(_) => registry.process.take(),
                Ok(None) => None,
            }
        };

        if let Some(process) = process_status {
            // 已退出和状态不明都需释放持有的进程树句柄，避免遗留启动器或子进程。
            terminate_sidecar(process);
            if is_current_generation(&app, generation) {
                show_recovery_page(&app, generation, &shell_page_url);
            }
            return;
        }

        if health_is_ok(&agent, &health_url) {
            consecutive_failures = 0;
        } else {
            consecutive_failures = consecutive_failures.saturating_add(1);
            if consecutive_failures >= HEALTH_FAILURE_LIMIT {
                let stopped = stop_sidecar_generation(&app, generation);
                if stopped {
                    show_recovery_page(&app, generation, &shell_page_url);
                }
                return;
            }
        }
        thread::sleep(Duration::from_secs(MONITOR_INTERVAL_SECS));
    }
}

/// 健康检查专用 HTTP agent：ureq 3 经 config builder 配全局超时。
fn health_check_agent() -> ureq::Agent {
    ureq::Agent::config_builder()
        .timeout_global(Some(Duration::from_secs(HEALTH_REQUEST_TIMEOUT_SECS)))
        .build()
        .new_agent()
}

/// 健康接口必须返回 siku 的成功标记，不能只依赖任意 HTTP 200。
fn health_is_ok(agent: &ureq::Agent, health_url: &str) -> bool {
    agent
        .get(health_url)
        .call()
        .ok()
        .filter(|response| response.status() == 200)
        .and_then(|response| response.into_body().read_to_string().ok())
        .map(|body| health_body_is_ok(&body))
        .unwrap_or(false)
}

fn health_body_is_ok(body: &str) -> bool {
    serde_json::from_str::<serde_json::Value>(body)
        .ok()
        .and_then(|payload| payload.get("status")?.as_str().map(str::to_owned))
        .is_some_and(|status| status == "ok")
}

/// 去掉启动页已有查询与片段，得到稳定的壳页面地址。
fn strip_shell_page_query(url: &str) -> String {
    url.split(['?', '#']).next().unwrap_or(url).to_string()
}

/// 运行期恢复标记下的壳页只显示恢复操作，不会自动再启动一个 sidecar。
fn is_recovery_url(url: &str) -> bool {
    url.split_once('?')
        .map(|(_, query)| query.split('&').any(|field| field == "recovery=1"))
        .unwrap_or(false)
}

fn recovery_page_url(shell_page_url: &str) -> String {
    format!("{}?recovery=1", strip_shell_page_query(shell_page_url))
}

fn show_recovery_page(app: &tauri::AppHandle, generation: u64, shell_page_url: &str) {
    let state = app.state::<SidecarState>();
    let registry = match state.registry.lock() {
        Ok(guard) => guard,
        Err(poisoned) => poisoned.into_inner(),
    };
    if !registry.is_current(generation) {
        return;
    }
    let Some(window) = app.get_webview_window("main") else {
        return;
    };
    let recovery_url = recovery_page_url(shell_page_url);
    if let Ok(script_url) = serde_json::to_string(&recovery_url) {
        let _ = window.eval(format!("window.location.replace({script_url});"));
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
    fn recovery_page_url_discards_old_query_and_fragment() {
        assert_eq!(
            recovery_page_url("tauri://localhost/index.html?old=1#home"),
            "tauri://localhost/index.html?recovery=1"
        );
    }

    #[test]
    fn recovery_url_is_detected_without_matching_other_query_values() {
        assert!(is_recovery_url("tauri://localhost/index.html?recovery=1"));
        assert!(!is_recovery_url(
            "tauri://localhost/index.html?not-recovery=1"
        ));
    }

    #[test]
    fn health_body_matches_json_status_without_requiring_compact_serialization() {
        assert!(health_body_is_ok(r#"{"status":"ok"}"#));
        assert!(health_body_is_ok(
            "{ \"status\" : \"ok\", \"version\" : \"0.1.0\" }"
        ));
        assert!(!health_body_is_ok(r#"{"metadata":{"status":"ok"}}"#));
        assert!(!health_body_is_ok(r#"{"status":"failed"}"#));
        assert!(!health_body_is_ok("not json"));
    }

    fn test_sidecar_process(generation: u64) -> SidecarProcess {
        let mut command = if cfg!(windows) {
            let mut command = Command::new("cmd.exe");
            command.args(["/C", "ping -n 60 127.0.0.1 > NUL"]);
            command
        } else {
            let mut command = Command::new("/bin/sh");
            command.args(["-c", "sleep 30"]);
            command
        };
        #[cfg(unix)]
        unsafe {
            use std::os::unix::process::CommandExt;
            command.pre_exec(|| {
                if libc::setpgid(0, 0) != 0 {
                    return Err(std::io::Error::last_os_error());
                }
                Ok(())
            });
        }
        let child = command
            .spawn()
            .expect("failed to spawn registry test process");
        #[cfg(windows)]
        let job = {
            let job = create_sidecar_job().expect("failed to create sidecar job");
            assign_sidecar_to_job(&job, &child).expect("failed to assign test process to job");
            job
        };
        SidecarProcess {
            generation,
            child,
            _stdin: None,
            #[cfg(windows)]
            _job: job,
        }
    }

    #[test]
    fn late_startup_cannot_replace_or_stop_newer_sidecar() {
        let mut registry = SidecarRegistry::default();
        let stale_generation = registry
            .next_generation()
            .expect("startup should be accepted");
        let current_generation = registry
            .next_generation()
            .expect("startup should be accepted");
        let current_process = test_sidecar_process(current_generation);
        let previous = match registry.install_if_current(current_generation, current_process) {
            Ok(previous) => previous,
            Err(process) => {
                terminate_sidecar(process);
                panic!("current process was rejected");
            }
        };
        assert!(previous.is_none());

        let stale_process = test_sidecar_process(stale_generation);
        let stale_process = match registry.install_if_current(stale_generation, stale_process) {
            Err(process) => process,
            Ok(_) => panic!("stale startup replaced the current sidecar"),
        };
        terminate_sidecar(stale_process);

        assert_eq!(
            registry.process.as_ref().map(|process| process.generation),
            Some(current_generation)
        );
        assert!(registry.take_generation(stale_generation).is_none());
        let current_process = registry
            .take_generation(current_generation)
            .expect("current sidecar should remain registered");
        terminate_sidecar(current_process);
    }

    #[test]
    fn shutdown_rejects_pending_startups() {
        let mut registry = SidecarRegistry::default();
        let generation = registry
            .next_generation()
            .expect("startup should be accepted");
        assert!(registry.try_begin_shutdown().is_some());

        let process = test_sidecar_process(generation);
        let process = match registry.install_if_current(generation, process) {
            Err(process) => process,
            Ok(_) => panic!("shutdown accepted a pending sidecar"),
        };
        terminate_sidecar(process);
        assert!(registry.next_generation().is_none());
    }

    #[test]
    fn repeated_close_requests_start_only_one_shutdown_task() {
        let mut registry = SidecarRegistry::default();

        let first = registry
            .try_begin_shutdown()
            .expect("first close request should own shutdown cleanup");

        assert_eq!(registry.try_begin_shutdown(), None);
        assert_eq!(registry.generation, first);
    }

    #[test]
    fn shutdown_waits_until_lifecycle_worker_finishes_cleanup() {
        let tracker = Arc::new(LifecycleTracker::default());
        let worker = tracker.register();
        let waiter_tracker = Arc::clone(&tracker);
        let (started_tx, started_rx) = std::sync::mpsc::channel();
        let (finished_tx, finished_rx) = std::sync::mpsc::channel();
        let waiter = thread::spawn(move || {
            started_tx
                .send(())
                .expect("waiter should announce before blocking");
            waiter_tracker.wait_for_idle();
            finished_tx
                .send(())
                .expect("waiter should report completed cleanup");
        });

        started_rx
            .recv()
            .expect("waiter should start before checking the guard");
        assert_eq!(
            finished_rx.recv_timeout(Duration::from_millis(50)),
            Err(std::sync::mpsc::RecvTimeoutError::Timeout)
        );

        drop(worker);
        finished_rx
            .recv_timeout(Duration::from_secs(1))
            .expect("shutdown should continue after cleanup finishes");
        waiter.join().expect("waiter thread should exit cleanly");
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
        let child = command.spawn().expect("failed to spawn test process");
        let shell_pid = child.id();
        terminate(child);
        // 组内任意成员存活即失败：轮询组内代表性 PID（子 shell 与其 sleep 孩子）
        thread::sleep(Duration::from_millis(200));
        let alive = unsafe { libc::kill(shell_pid as i32, 0) } == 0;
        assert!(!alive, "process group member survived termination");
    }

    #[cfg(unix)]
    #[test]
    fn terminate_kills_descendants_after_leader_exits() {
        // 模拟启动器先退出、忽略 SIGTERM 的子进程仍运行；终止流程必须继续检查整个进程组。
        let mut command = Command::new("/bin/sh");
        command.args(["-c", "sh -c \"trap '' TERM; exec sleep 30\" & exit 0"]);
        unsafe {
            use std::os::unix::process::CommandExt;
            command.pre_exec(|| {
                if libc::setpgid(0, 0) != 0 {
                    return Err(std::io::Error::last_os_error());
                }
                Ok(())
            });
        }
        let mut child = command.spawn().expect("failed to spawn test launcher");
        let process_group_id = child.id() as i32;
        child.wait().expect("test launcher failed to exit");
        assert!(
            process_group_exists(process_group_id),
            "test child was not started"
        );

        terminate_with_grace(child, Duration::from_millis(50));

        let deadline = Instant::now() + Duration::from_secs(2);
        while process_group_exists(process_group_id) && Instant::now() < deadline {
            thread::sleep(Duration::from_millis(10));
        }
        assert!(
            !process_group_exists(process_group_id),
            "descendant survived after the sidecar leader exited"
        );
    }

    #[cfg(windows)]
    #[test]
    fn closing_sidecar_job_terminates_its_process_tree() {
        let job = create_sidecar_job().expect("failed to create sidecar job");
        let mut child = Command::new("cmd.exe")
            .args(["/C", "ping -n 60 127.0.0.1 > NUL"])
            .spawn()
            .expect("failed to spawn process tree");
        assign_sidecar_to_job(&job, &child).expect("failed to assign process to job");

        drop(job);

        let deadline = Instant::now() + Duration::from_secs(5);
        loop {
            if let Some(status) = child.try_wait().expect("failed to inspect test child") {
                assert!(!status.success(), "job closure did not terminate the child");
                break;
            }
            assert!(
                Instant::now() < deadline,
                "job closure left the child running"
            );
            thread::sleep(Duration::from_millis(50));
        }
    }
}
