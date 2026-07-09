import Cocoa
import FlutterMacOS

/// Returns true if any application window is currently visible to the user.
func hasVisibleAppWindows() -> Bool {
    return NSApplication.shared.windows.contains { window in
        window.isVisible
    }
}

@main
class AppDelegate: FlutterAppDelegate {
    var launched = false;
  override func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
      dummy_method_to_enforce_bundling()
    // https://github.com/leanflutter/window_manager/issues/214
    // Windows are hidden instead of closed on macOS; termination is handled
    // in Dart via maybeQuitWhenNoWindows() and applicationShouldHandleReopen.
    return false
  }

    override func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        if !hasVisibleAppWindows() {
            NSApplication.shared.terminate(nil)
            return false
        }
        if (launched) {
            handle_applicationShouldOpenUntitledFile();
        }
        return true
    }
    
    override func applicationShouldOpenUntitledFile(_ sender: NSApplication) -> Bool {
        if (launched) {
            handle_applicationShouldOpenUntitledFile();
        }
        return true
    }
    
    override func applicationDidFinishLaunching(_ aNotification: Notification) {
        launched = true;
        NSApplication.shared.activate(ignoringOtherApps: true);
    }

    override func applicationSupportsSecureRestorableState(_ app: NSApplication) -> Bool {
        return true
    }
}
