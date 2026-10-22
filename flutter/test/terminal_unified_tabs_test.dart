import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_hbb/common.dart' as common;
import 'package:flutter_hbb/desktop/pages/terminal_page.dart';
import 'package:flutter_hbb/desktop/pages/terminal_tab_page.dart';
import 'package:flutter_hbb/desktop/widgets/tabbar_widget.dart';
import 'package:flutter_hbb/generated_bridge.dart';
import 'package:flutter_hbb/models/platform_model.dart';
import 'package:flutter_test/flutter_test.dart';

class _Binding extends Fake implements RustdeskImpl {
  @override
  String mainGetPeerOptionSync(
          {required String id, required String key, dynamic hint}) =>
      '';
  @override
  String mainGetLocalOption({required String key, dynamic hint}) => '';
  @override
  bool mainIsOptionFixed({required String key, dynamic hint}) => false;
  @override
  bool isDisableSettings({dynamic hint}) => false;
  @override
  bool isIncomingOnly({dynamic hint}) => false;
  @override
  bool isOutgoingOnly({dynamic hint}) => false;
}

class _Host extends StatefulWidget {
  const _Host({super.key});
  @override
  State<_Host> createState() => _HostState();
}

class _HostState extends State<_Host> with TerminalTabsMixin<_Host> {
  @override
  final tabController = DesktopTabController(tabType: DesktopTabType.main);
  @override
  bool get unifiedTerminalTabs => true;
  @override
  int windowId() => 0;
  @override
  void initState() {
    super.initState();
    tabController.onRemoved = (_, key) => onTerminalTabRemoved(key);
    tabController.add(TabInfo(
        key: 'home', label: 'Home', page: const SizedBox(), closable: false));
  }

  @override
  Widget build(BuildContext context) => const SizedBox();
}

void main() {
  setUp(() => platformFFI.setBindingForTesting(_Binding()));

  testWidgets(
      'terminal tabs preserve authentication and share the main controller',
      (tester) async {
    final key = GlobalKey<_HostState>();
    await tester.pumpWidget(MaterialApp(home: _Host(key: key)));
    final host = key.currentState!;
    const args = {
      'id': 'peer_with_underscore',
      'password': 'test-password',
      'connToken': 'test-token',
      'forceRelay': true,
      'isSharedPassword': true
    };
    host.openTerminalSession(args);
    host.openTerminalSession(args);
    final tabs = host.tabController.state.value.tabs;
    expect(tabs.map((t) => t.key), [
      'home',
      'terminal:peer_with_underscore_1',
      'terminal:peer_with_underscore_2'
    ]);
    for (final tab in tabs.skip(1)) {
      final page = tab.page as TerminalPage;
      expect(page.tabController, same(host.tabController));
      expect(page.id, 'peer_with_underscore');
      expect(page.password, 'test-password');
      expect(page.connToken, 'test-token');
      expect(page.forceRelay, true);
      expect(page.isSharedPassword, true);
      expect(tab.sessionId, isNotNull);
      expect(tab.onDeactivate, isNotNull);
    }
    host.tabController.add(
        TabInfo(key: 'remote:other', label: 'Other', page: const SizedBox()));
    await host.closeAllTerminalTabs();
    expect(host.tabController.state.value.tabs.map((t) => t.key),
        ['home', 'remote:other']);
    expect(host.tabController.selectedTab?.key, 'remote:other');
    await tester.pump(const Duration(milliseconds: 110));
  });

  testWidgets(
      'terminal new-tab shortcut leaves Home alone and works on the selected terminal',
      (tester) async {
    final key = GlobalKey<_HostState>();
    await tester.pumpWidget(MaterialApp(home: _Host(key: key)));
    final host = key.currentState!;
    final modifier = common.isMacOS
        ? LogicalKeyboardKey.metaLeft
        : LogicalKeyboardKey.controlLeft;
    Future<void> newTabShortcut() async {
      await tester.sendKeyDownEvent(modifier);
      if (!common.isMacOS)
        await tester.sendKeyDownEvent(LogicalKeyboardKey.shiftLeft);
      await tester.sendKeyEvent(LogicalKeyboardKey.keyT);
      if (!common.isMacOS)
        await tester.sendKeyUpEvent(LogicalKeyboardKey.shiftLeft);
      await tester.sendKeyUpEvent(modifier);
    }

    await newTabShortcut();
    expect(host.tabController.length, 1);
    host.openTerminalSession({'id': 'peer', 'connToken': 'test-token'});
    await newTabShortcut();
    expect(host.tabController.length, 3);
    expect((host.tabController.selectedTab!.page as TerminalPage).connToken,
        'test-token');
    await tester.pump(const Duration(milliseconds: 110));
  });
}
