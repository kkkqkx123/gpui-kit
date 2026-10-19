//! Events produced by the tray backends and bridged to the GPUI main thread.

use crate::menu::MenuItemId;

/// An event originating from the native tray.
#[derive(Debug, Clone)]
pub enum TrayEvent {
    /// Tray icon activated (typically a left click). Coordinates are screen
    /// pixels, useful as a hint for where to place a window.
    IconActivated { x: i32, y: i32 },
    /// Tray icon secondary activated (typically a middle click).
    IconSecondaryActivated { x: i32, y: i32 },
    /// A menu item was activated; `id` identifies the originating item.
    MenuItemActivated { id: MenuItemId },
    /// Backend state changed; refresh the native presentation.
    Refresh,
}
