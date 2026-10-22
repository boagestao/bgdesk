import 'dart:ui' show AppExitResponse;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_hbb/common.dart';
import 'package:flutter_hbb/consts.dart';
import 'package:flutter_hbb/desktop/pages/connection_page.dart';
import 'package:flutter_hbb/desktop/pages/desktop_home_page.dart';
import 'package:flutter_hbb/desktop/pages/desktop_setting_page.dart';
import 'package:flutter_hbb/desktop/widgets/tabbar_widget.dart';
import 'package:flutter_hbb/models/platform_model.dart';
import 'package:flutter_hbb/models/state_model.dart';
import 'package:get/get.dart';
import 'package:window_manager/window_manager.dart';
import 'package:flutter_hbb/common/widgets/dialog.dart';
import 'package:flutter_hbb/common/widgets/overlay.dart';
import 'package:flutter_hbb/desktop/pages/remote_page.dart';
import 'package:flutter_hbb/desktop/pages/file_manager_page.dart';
import 'package:flutter_hbb/desktop/pages/view_camera_page.dart';
import 'package:flutter_hbb/desktop/pages/terminal_page.dart';
import 'package:flutter_hbb/desktop/pages/terminal_tab_page.dart';
import 'package:flutter_hbb/desktop/pages/port_forward_page.dart';
import 'package:flutter_hbb/models/model.dart';
import 'package:flutter_hbb/desktop/widgets/remote_toolbar.dart';
import 'package:flutter_hbb/utils/multi_window_manager.dart';
// import 'package:flutter/services.dart';

import '../../common/shared_state.dart';

class DesktopTabPage extends StatefulWidget {
  const DesktopTabPage({Key? key}) : super(key: key);

  @override
  State<DesktopTabPage> createState() => _DesktopTabPageState();

  static void onAddSetting(
      {SettingsTabKey initialPage = SettingsTabKey.general}) {
    try {
      DesktopTabController tabController = Get.find<DesktopTabController>();
      tabController.add(TabInfo(
          key: kTabLabelSettingPage,
          label: kTabLabelSettingPage,
          selectedIcon: Icons.build_sharp,
          unselectedIcon: Icons.build_outlined,
          page: DesktopSettingPage(
            key: const ValueKey(kTabLabelSettingPage),
            initialTabkey: initialPage,
          )));
    } catch (e) {
      debugPrintStack(label: '$e');
    }
  }
}

class _DesktopTabPageState extends State<DesktopTabPage>
    with WidgetsBindingObserver, TerminalTabsMixin<DesktopTabPage> {
  @override
  bool get unifiedTerminalTabs => true;
  @override
  int windowId() => kMainWindowId;
  @override
  bool get terminalOperationsBlocked =>
      _exitPending || super.terminalOperationsBlocked;
  @override
  final tabController = DesktopTabController(tabType: DesktopTabType.main);
  final _connectionPageKey = GlobalKey<ConnectionPageState>();

  _DesktopTabPageState() {
    RemoteCountState.init();
    Get.put<DesktopTabController>(tabController);
    tabController.add(TabInfo(
        key: kTabLabelHomePage,
        label: kTabLabelHomePage,
        selectedIcon: Icons.home_sharp,
        unselectedIcon: Icons.home_outlined,
        closable: false,
        page: DesktopHomePage(
          key: const ValueKey(kTabLabelHomePage),
          connectionPageKey: _connectionPageKey,
        )));
    if (bind.isIncomingOnly()) {
      tabController.onSelected = (key) {
        if (key == kTabLabelHomePage) {
          windowManager.setSize(getIncomingOnlyHomeSize());
          setResizable(false);
        } else {
          windowManager.setSize(getIncomingOnlySettingsSize());
          setResizable(true);
        }
      };
    } else {
      rustDeskWinManager.sessionTabOpener = _openSession;
      rustDeskWinManager.terminalSessionRestorer = restoreTerminalSessions;
      rustDeskWinManager.hasMainSessionTabs = () => _sessionTabs.isNotEmpty;
      tabController.onSelected = _selectSession;
    }
    tabController.onRemoved = (_, key) {
      onTerminalTabRemoved(key);
      if (key.startsWith('remote:')) {
        final id = key.substring('remote:'.length);
        ConnectionTypeState.delete(id);
        stateGlobal.relativeMouseModeState.remove(id);
      }
      RemoteCountState.find().value =
          _sessionTabs.where((t) => t.page is RemotePage).length;
    };
  }

  bool _inputInitialized = false;
  bool _exitPending = false;
  List<TabInfo>? _pendingHiddenClose;

  Iterable<TabInfo> get _sessionTabs =>
      tabController.state.value.tabs.where((t) => t.sessionId != null);

  void _addConnection() {
    // Selection releases remote input before bringing the local ID field forward.
    tabController.jumpToByKey(kTabLabelHomePage);
    final state = tabController.state.value;
    if (state.pageController.hasClients) {
      state.pageController.jumpToPage(state.selected);
    }
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted && tabController.selectedTab?.key == kTabLabelHomePage) {
        _connectionPageKey.currentState?.prepareNewConnection();
      }
    });
  }

  void _selectSession(String key) {
    if (tabController.selectedTab?.key != key) return;
    final page = tabController.widget(key);
    if (page is RemotePage) {
      final ffi = page.initializedFfi;
      if (ffi != null) bind.setCurSessionId(sessionId: ffi.sessionId);
      UnreadChatCountState.find(page.id).value = 0;
    }
  }

  Future<void> _openSession(WindowType type, Map<String, dynamic> args) async {
    if (_exitPending || !mounted) return;
    if (!_inputInitialized) {
      bind.mainInitInputSource();
      stateGlobal.getInputSource(force: true);
      draggablePositions.load();
      _inputInitialized = true;
    }
    final id = args['id'] as String;
    if (type == WindowType.Terminal) {
      openTerminalSession(args);
      await windowOnTop(null);
      return;
    }
    final key = switch (type) {
      WindowType.RemoteDesktop => 'remote:$id',
      WindowType.FileTransfer => 'file:$id',
      WindowType.ViewCamera => 'camera:$id',
      WindowType.PortForward => '${args['isRDP'] == true ? 'rdp' : 'tcp'}:$id',
      _ => throw ArgumentError.value(type, 'type'),
    };
    final existing = tabController.widget(key);
    if (existing != null) {
      tabController.jumpToByKey(key);
      if ((existing is RemotePage || existing is ViewCameraPage) &&
          args['display'] != null) {
        final ffi = existing is RemotePage
            ? existing.initializedFfi
            : (existing as ViewCameraPage).initializedFfi;
        if (ffi != null)
          openMonitorInTheSameTab(args['display'], ffi, ffi.ffiModel.pi);
      }
    } else {
      if (type == WindowType.RemoteDesktop) ConnectionTypeState.init(id);
      final Widget page;
      final IconData icon;
      switch (type) {
        case WindowType.RemoteDesktop:
          icon = Icons.desktop_windows;
          page = RemotePage(
              key: UniqueKey(),
              id: id,
              tabKey: key,
              password: args['password'],
              isSharedPassword: args['isSharedPassword'],
              forceRelay: args['forceRelay'],
              switchUuid: args['switch_uuid'],
              toolbarState: ToolbarState(),
              tabController: tabController);
        case WindowType.FileTransfer:
          icon = Icons.folder_outlined;
          page = FileManagerPage(
              key: UniqueKey(),
              id: id,
              tabKey: key,
              password: args['password'],
              isSharedPassword: args['isSharedPassword'],
              forceRelay: args['forceRelay'],
              connToken: args['connToken'],
              tabController: tabController);
        case WindowType.ViewCamera:
          icon = Icons.videocam_outlined;
          page = ViewCameraPage(
              key: UniqueKey(),
              id: id,
              tabKey: key,
              password: args['password'],
              isSharedPassword: args['isSharedPassword'],
              forceRelay: args['forceRelay'],
              connToken: args['connToken'],
              toolbarState: ToolbarState(),
              tabController: tabController);
        case WindowType.PortForward:
          icon = Icons.compare_arrows;
          page = PortForwardPage(
              key: UniqueKey(),
              id: id,
              tabKey: key,
              password: args['password'],
              isSharedPassword: args['isSharedPassword'],
              forceRelay: args['forceRelay'],
              connToken: args['connToken'],
              isRDP: args['isRDP'] == true,
              tabController: tabController);
        default:
          return;
      }
      tabController.add(TabInfo(
        key: key,
        label: getDesktopTabLabel(
            id, bind.mainGetPeerOptionSync(id: id, key: 'alias')),
        selectedIcon: icon,
        unselectedIcon: icon,
        onDeactivate: page is RemotePage
            ? page.deactivateInput
            : page is ViewCameraPage
                ? page.deactivateInput
                : null,
        sessionId: () => _pageFfi(page)?.sessionId,
        onTabCloseButton: () async {
          if (!await desktopTryShowTabAuditDialogCloseCancelled(
              id: key, tabController: tabController)) {
            if (identical(tabController.widget(key), page))
              tabController.closeBy(key);
          }
        },
        page: page,
      ));
      RemoteCountState.find().value =
          _sessionTabs.where((t) => t.page is RemotePage).length;
    }
    await windowOnTop(null);
    await rustDeskWinManager.registerActiveWindow(kMainWindowId);
  }

  FFI? _pageFfi(Widget page) => switch (page) {
        RemotePage() => page.initializedFfi,
        FileManagerPage() => page.initializedFfi,
        ViewCameraPage() => page.initializedFfi,
        TerminalPage() => page.initializedFfi,
        PortForwardPage() => page.initializedFfi,
        _ => null,
      };

  Future<List<TabInfo>?> _prepareCloseSessions({bool audit = true}) =>
      prepareCloseMainSessionTabs(
        tabs: tabController.state.value.tabs,
        confirm: () => closeConfirmDialog(allowPreference: false),
        auditCancelled: audit
            ? (tab) => desktopTryShowTabAuditDialogCloseCancelled(
                id: tab.key, tabController: tabController, forceGlobal: true)
            : null,
      );

  Future<void> _executeCloseSessions(List<TabInfo> tabs) async {
    final connections =
        tabs.map((tab) => _pageFfi(tab.page)).whereType<FFI>().toSet();
    await closeAllTerminalTabs();
    for (final tab in tabs) {
      if (identical(tabController.widget(tab.key), tab.page))
        tabController.closeBy(tab.key);
    }
    // Let pages dispose first; then await the same idempotent native shutdown.
    await WidgetsBinding.instance.endOfFrame;
    await Future.wait([
      ...tabs
          .where((t) => t.page is FileManagerPage)
          .map((t) => (t.page as FileManagerPage).closeSession()),
      ...connections
          .where((ffi) => ffi.connType != ConnType.fileTransfer)
          .map((ffi) => ffi.close()),
    ]);
  }

  Future<bool> _handleMainWindowClose() async {
    if (_exitPending) return false;
    tabController.deactivateSelected();
    final sessions = await _prepareCloseSessions(audit: false);
    if (sessions == null) return false;
    _pendingHiddenClose = sessions;
    _exitPending = true;
    return true;
  }

  Future<void> _closeSessionsAfterWindowHidden() async {
    final sessions = _pendingHiddenClose;
    _pendingHiddenClose = null;
    try {
      if (sessions != null && sessions.isNotEmpty) {
        await _executeCloseSessions(sessions);
      }
    } finally {
      _exitPending = false;
    }
  }

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    // HardwareKeyboard.instance.addHandler(_handleKeyEvent);
  }

  @override
  Future<AppExitResponse> didRequestAppExit() async {
    if (bind.isIncomingOnly()) return AppExitResponse.exit;
    if (_exitPending) return AppExitResponse.cancel;
    _exitPending = true;
    try {
      if (_sessionTabs.isNotEmpty) {
        tabController.deactivateSelected();
        await windowOnTop(null);
      }
      final closed = await hideThenCloseMainSessions(
        prepare: () => _prepareCloseSessions(),
        hide: () async {
          if (await windowManager.isVisible()) await windowManager.hide();
        },
        close: _executeCloseSessions,
      );
      if (!closed) return AppExitResponse.cancel;
      await rustDeskWinManager.closeAllSubWindows();
      return AppExitResponse.exit;
    } finally {
      _exitPending = false;
    }
  }

  /*
  bool _handleKeyEvent(KeyEvent event) {
    if (!mouseIn && event is KeyDownEvent) {
      print('key down: ${event.logicalKey}');
      shouldBeBlocked(_block, canBeBlocked);
    }
    return false; // allow it to propagate
  }
  */

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    if (!bind.isIncomingOnly()) {
      rustDeskWinManager.sessionTabOpener = null;
      rustDeskWinManager.terminalSessionRestorer = null;
      rustDeskWinManager.hasMainSessionTabs = null;
    }
    // HardwareKeyboard.instance.removeHandler(_handleKeyEvent);
    Get.delete<DesktopTabController>();

    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    void switchTab(int delta) {
      final state = tabController.state.value;
      if (state.tabs.length > 1) {
        tabController.jumpTo(
            (state.selected + delta + state.tabs.length) % state.tabs.length);
      }
    }

    final tabWidget = Container(
        child: Scaffold(
            backgroundColor: Theme.of(context).colorScheme.background,
            body: CallbackShortcuts(
                bindings: bind.isIncomingOnly()
                    ? const {}
                    : {
                        const SingleActivator(LogicalKeyboardKey.tab,
                            control: true): () => switchTab(1),
                        const SingleActivator(LogicalKeyboardKey.tab,
                            control: true, shift: true): () => switchTab(-1),
                      },
                child: DesktopTab(
                  controller: tabController,
                  onWindowCloseButton:
                      bind.isIncomingOnly() ? null : _handleMainWindowClose,
                  onWindowHidden: bind.isIncomingOnly()
                      ? null
                      : _closeSessionsAfterWindowHidden,
                  tabMenuBuilder: terminalTabMenu,
                  tabBuilder: (key, icon, label, theme) {
                    final page = tabController.widget(key);
                    if (page is! RemotePage)
                      return Row(children: [icon, label]);
                    return Obx(() {
                      final connection = ConnectionTypeState.find(page.id);
                      final secure =
                          connection.secure.value == ConnectionType.strSecure;
                      return Row(children: [
                        icon,
                        if (connection.isValid())
                          Tooltip(
                            message:
                                '${getConnectionText(secure, connection.direct.value == ConnectionType.strDirect, connection.stream_type.value)}\n${translate('Fingerprint')}: ${FingerprintState.find(page.id).value}',
                            child: Padding(
                                padding: const EdgeInsets.only(right: 5),
                                child: Icon(
                                    secure
                                        ? Icons.lock_outline
                                        : Icons.lock_open,
                                    size: theme.iconSize)),
                          ),
                        label,
                        unreadMessageCountBuilder(
                            UnreadChatCountState.find(page.id)),
                      ]);
                    });
                  },
                  tail: Offstage(
                    offstage: bind.isIncomingOnly(),
                    child: ActionIcon(
                      message: 'New Connection',
                      icon: Icons.add,
                      onTap: _addConnection,
                      isClose: false,
                    ),
                  ),
                ))));
    return isMacOS || kUseCompatibleUiMode
        ? tabWidget
        : Obx(
            () => DragToResizeArea(
              resizeEdgeSize: stateGlobal.resizeEdgeSize.value,
              enableResizeEdges: windowManagerEnableResizeEdges,
              child: tabWidget,
            ),
          );
  }
}
