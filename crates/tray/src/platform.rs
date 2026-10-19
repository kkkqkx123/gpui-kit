//! Platform backend selection. Each backend is compiled only for its target OS,
//! so a Linux build never pulls in `objc2` or `tray-icon`.

#[cfg(target_os = "linux")]
mod linux;
#[cfg(target_os = "linux")]
pub use linux::create_backend;

#[cfg(target_os = "macos")]
mod macos;
#[cfg(target_os = "macos")]
pub use macos::create_backend;

#[cfg(target_os = "windows")]
mod windows;
#[cfg(target_os = "windows")]
pub use windows::create_backend;

// Fallback for any platform we do not implement: a no-op backend that always
// reports itself unavailable so the host can degrade gracefully.
#[cfg(not(any(target_os = "linux", target_os = "macos", target_os = "windows")))]
mod null;
#[cfg(not(any(target_os = "linux", target_os = "macos", target_os = "windows")))]
pub use null::create_backend;
