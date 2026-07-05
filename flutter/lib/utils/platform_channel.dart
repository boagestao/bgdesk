import 'package:flutter/foundation.dart';
import 'package:flutter/services.dart';
import 'package:flutter_hbb/main.dart';
import 'package:flutter_hbb/common.dart';

/// BGDesk-specific namespace to avoid conflicts with RustDesk when both are installed.
const kBgDeskChannelNamespace = 'br.com.boagestao.bgdesk';

const kBgDeskHostChannel = MethodChannel('$kBgDeskChannelNamespace/host');
const kBgDeskMacOSChannel = MethodChannel('$kBgDeskChannelNamespace/macos');
const kBgDeskSideButtonsChannel =
    MethodChannel('$kBgDeskChannelNamespace/side_buttons');

enum SystemWindowTheme { light, dark }

/// The platform channel for BGDesk.
class RdPlatformChannel {
  RdPlatformChannel._();

  static final RdPlatformChannel _windowUtil = RdPlatformChannel._();

  static RdPlatformChannel get instance => _windowUtil;

  final MethodChannel _hostMethodChannel = kBgDeskHostChannel;

  static const MethodChannel _macOSMethodChannel = kBgDeskMacOSChannel;

  /// Bump the position of the mouse cursor, if applicable
  Future<bool> bumpMouse({required int dx, required int dy}) async {
    // No debug output; this call is too chatty.

    bool? result = await _hostMethodChannel
      .invokeMethod("bumpMouse", {"dx": dx, "dy": dy});

    return result ?? false;
  }

  /// Change the theme of the system window
  Future<void> changeSystemWindowTheme(SystemWindowTheme theme) {
    assert(isMacOS);
    if (kDebugMode) {
      print(
          "[Window ${kWindowId ?? 'Main'}] change system window theme to ${theme.name}");
    }
    return _hostMethodChannel
        .invokeMethod("setWindowTheme", {"themeName": theme.name});
  }

  /// Terminate .app manually.
  Future<void> terminate() {
    assert(isMacOS);
    return _macOSMethodChannel.invokeMethod("terminate");
  }

  /// Whether any application window is currently visible (macOS only).
  Future<bool> hasVisibleWindows() async {
    assert(isMacOS);
    return await _macOSMethodChannel.invokeMethod<bool>("hasVisibleWindows") ??
        false;
  }
}
