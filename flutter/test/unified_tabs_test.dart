import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_hbb/common/shared_state.dart';
import 'package:flutter_hbb/models/model.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_hbb/desktop/widgets/tabbar_widget.dart';
import 'package:flutter_hbb/generated_bridge.dart';
import 'package:flutter_hbb/common.dart' as common;
import 'package:get/get.dart';
import 'package:uuid/uuid.dart';
import 'package:flutter_hbb/models/platform_model.dart';

class _Binding extends Fake implements RustdeskImpl {
  @override
  bool isIncomingOnly({dynamic hint}) => false;
  @override
  bool isOutgoingOnly({dynamic hint}) => false;
}

class _Session extends Fake implements FFI {
  _Session(this.sharedStateId);
  @override
  final String sharedStateId;
  @override
  final common.SessionID sessionId = const Uuid().v4obj();
  late final ffiModel = FfiModel(WeakReference(this));
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  setUp(() => platformFFI.setBindingForTesting(_Binding()));

  testWidgets(
      'focus release does not invalidate window adjustment like a tab change',
      (tester) async {
    final controller = DesktopTabController(tabType: DesktopTabType.main);
    for (final key in ['home', 'remote:A']) {
      controller.add(TabInfo(key: key, label: key, page: const SizedBox()));
    }
    final generation = controller.selectionGeneration;
    controller
        .deactivateSelected(); // Blur during the native fullscreen transition.
    expect(controller.selectionGeneration, generation);
    controller.jumpToByKey('home');
    controller.jumpToByKey('remote:A');
    expect(controller.selectionGeneration, greaterThan(generation));
    await tester.pump(const Duration(milliseconds: 110));
  });

  testWidgets('all tab transitions release the old owner before selecting',
      (tester) async {
    final controller = DesktopTabController(tabType: DesktopTabType.main);
    final events = <String>[];
    for (final key in [
      'home',
      'remote:A',
      'file:A',
      'camera:A',
      'terminal:A_1',
      'tcp:A',
      'settings',
      'remote:B'
    ]) {
      controller.add(TabInfo(
          key: key,
          label: key,
          page: SizedBox(key: ValueKey(key)),
          onDeactivate: key.startsWith('remote:')
              ? () => events.add('release:$key:${controller.selectedTab?.key}')
              : null));
    }
    controller.onSelected = (key) => events.add('select:$key');
    for (final target in [
      'file:A',
      'camera:A',
      'terminal:A_1',
      'tcp:A',
      'home',
      'settings',
      'remote:B'
    ]) {
      controller.jumpToByKey('remote:A');
      events.clear();
      controller.jumpToByKey(target);
      expect(events, ['release:remote:A:remote:A', 'select:$target']);
    }
    await tester.pump(const Duration(milliseconds: 110));
  });

  testWidgets('closing a background tab preserves selection and input owner',
      (tester) async {
    final controller = DesktopTabController(tabType: DesktopTabType.main);
    final releases = <String>[];
    for (final key in ['home', 'remote:A', 'file:A', 'remote:B']) {
      controller.add(TabInfo(
          key: key,
          label: key,
          page: SizedBox(key: ValueKey(key)),
          closable: key != 'home',
          onDeactivate: () => releases.add(key)));
    }
    controller.onRemoved = (_, __) {};
    releases.clear();
    controller.closeBy('file:A');
    expect(controller.selectedTab?.key, 'remote:B');
    expect(releases, isEmpty);
    controller.closeBy('home');
    expect(controller.length, 3);
    controller.closeBy('remote:B');
    expect(releases, ['remote:B']);
    expect(controller.selectedTab?.key, 'remote:A');
    await tester.pump(const Duration(milliseconds: 110));
  });

  testWidgets('client connection-manager tabs remain removable by the core',
      (tester) async {
    final controller = DesktopTabController(tabType: DesktopTabType.cm);
    controller.onRemoved = (_, __) {};
    controller.add(TabInfo(
        key: 'incoming',
        label: 'Incoming',
        closable: false,
        page: const SizedBox()));
    controller.remove(0);
    expect(controller.length, 0);
    await tester.pump(const Duration(milliseconds: 110));
  });

  testWidgets('late session errors close only the owning typed tab',
      (tester) async {
    final controller = DesktopTabController(tabType: DesktopTabType.main);
    final remote = const Uuid().v4obj();
    final files = const Uuid().v4obj();
    common.desktopType = common.DesktopType.main;
    Get.put<DesktopTabController>(controller);
    addTearDown(() {
      Get.delete<DesktopTabController>();
      common.desktopType = null;
    });
    controller.onRemoved = (_, __) {};
    for (final entry in {'remote:A': remote, 'file:A': files}.entries) {
      controller.add(TabInfo(
          key: entry.key,
          label: entry.key,
          page: const SizedBox(),
          sessionId: () => entry.value));
    }
    common.closeConnection(sessionId: remote);
    expect(controller.selectedTab?.key, 'file:A');
    expect(controller.length, 1);
    common.closeConnection(sessionId: remote); // already closed; no fallback
    expect(controller.length, 1);
    await tester.pump(const Duration(milliseconds: 110));
  });

  testWidgets(
      'connection errors close all terminal siblings, preserving other tabs',
      (tester) async {
    final controller = DesktopTabController(tabType: DesktopTabType.main);
    final terminal = const Uuid().v4obj();
    common.desktopType = common.DesktopType.main;
    Get.put<DesktopTabController>(controller);
    addTearDown(() {
      Get.delete<DesktopTabController>();
      common.desktopType = null;
    });
    controller.onRemoved = (_, __) {};
    for (final key in [
      'terminal:A_1',
      'terminal:A_2',
      'terminal:B_3',
      'file:A'
    ]) {
      final uuid =
          key.startsWith('terminal:A_') ? terminal : const Uuid().v4obj();
      controller.add(TabInfo(
          key: key, label: key, page: const SizedBox(), sessionId: () => uuid));
    }
    common.closeConnection(sessionId: terminal);
    expect(controller.state.value.tabs.map((t) => t.key),
        ['terminal:B_3', 'file:A']);
    expect(controller.selectedTab?.key, 'file:A');
    common.closeConnection(sessionId: terminal);
    expect(controller.length, 2);
    await tester.pump(const Duration(milliseconds: 110));
  });

  for (final sessionKeys in [
    <String>[],
    ['remote:A'],
    ['file:A'],
    ['terminal:A_1'],
    ['camera:A'],
    ['tcp:A'],
    ['remote:A', 'file:A', 'terminal:A_1']
  ]) {
    for (final approved in [false, true]) {
      test('main close policy $sessionKeys (approved=$approved)', () async {
        final tabs = [
          TabInfo(
              key: 'home',
              label: 'Home',
              page: const SizedBox(),
              closable: false),
          TabInfo(key: 'settings', label: 'Settings', page: const SizedBox()),
          for (final key in sessionKeys)
            // Starting connections count even before they have an initialized UUID.
            TabInfo(
                key: key,
                label: key,
                page: const SizedBox(),
                sessionId: () => null),
        ];
        var confirmations = 0;
        final closed = <String>[];
        final result = await closeMainSessionTabs(
          tabs: tabs,
          confirm: () async {
            confirmations++;
            return approved;
          },
          close: (sessions) async => closed.addAll(sessions.map((t) => t.key)),
        );
        expect(confirmations, sessionKeys.length > 1 ? 1 : 0);
        final shouldClose = sessionKeys.length <= 1 || approved;
        expect(result, shouldClose);
        expect(closed, shouldClose ? sessionKeys : isEmpty);
      });
    }
  }

  test('window close hides before tearing down sessions', () async {
    final events = <String>[];
    final tabs = [
      for (final key in ['remote:A', 'file:A'])
        TabInfo(
            key: key, label: key, page: const SizedBox(), sessionId: () => null)
    ];
    final result = await hideThenCloseMainSessions(
      prepare: () => prepareCloseMainSessionTabs(
        tabs: tabs,
        confirm: () async {
          events.add('confirm');
          return true;
        },
      ),
      hide: () async => events.add('hide'),
      close: (sessions) async =>
          events.add('close:${sessions.map((t) => t.key).join(',')}'),
    );
    expect(result, isTrue);
    expect(events, ['confirm', 'hide', 'close:remote:A,file:A']);
  });

  test('cancelling close leaves the window visible and sessions running',
      () async {
    final events = <String>[];
    final result = await hideThenCloseMainSessions(
      prepare: () => prepareCloseMainSessionTabs(
        tabs: [
          for (final key in ['remote:A', 'file:A'])
            TabInfo(
                key: key,
                label: key,
                page: const SizedBox(),
                sessionId: () => null)
        ],
        confirm: () async => false,
      ),
      hide: () async => events.add('hide'),
      close: (_) async => events.add('close'),
    );
    expect(result, isFalse);
    expect(events, isEmpty);
  });

  test('cancelling a later audit leaves every connection running', () async {
    final events = <String>[];
    final tabs = [
      for (final key in ['remote:A', 'file:A', 'terminal:A_1'])
        TabInfo(
            key: key, label: key, page: const SizedBox(), sessionId: () => null)
    ];
    final gate = Completer<bool>();
    final closing = closeMainSessionTabs(
      tabs: tabs,
      confirm: () => gate.future,
      auditCancelled: (tab) async {
        events.add(tab.key);
        return tab.key == 'file:A';
      },
      close: (_) async => events.add('close'),
    );
    expect(events, isEmpty);
    gate.complete(true);
    expect(await closing, false);
    expect(events, ['remote:A', 'file:A']);
  });

  test('camera and remote connection state for the same peer stay independent',
      () {
    ConnectionTypeState.init('peer');
    ConnectionTypeState.init('camera:peer');
    final remote = _Session('peer');
    final camera = _Session('camera:peer');
    remote.ffiModel.setConnectionType('peer', true, true, 'remote');
    camera.ffiModel.setConnectionType('peer', false, false, 'camera');
    expect(ConnectionTypeState.find('peer').secure.value,
        ConnectionType.strSecure);
    expect(ConnectionTypeState.find('peer').stream_type.value, 'remote');
    expect(ConnectionTypeState.find('camera:peer').secure.value,
        ConnectionType.strInsecure);
    expect(ConnectionTypeState.find('camera:peer').stream_type.value, 'camera');
    ConnectionTypeState.delete('peer');
    ConnectionTypeState.delete('camera:peer');
  });

  testWidgets('rapid selection cannot apply a stale delayed page jump',
      (tester) async {
    final controller = DesktopTabController(tabType: DesktopTabType.main);
    for (final key in ['home', 'remote:A', 'file:A']) {
      controller.add(TabInfo(key: key, label: key, page: Text(key)));
    }
    await tester.pumpWidget(MaterialApp(
        home: PageView(
      controller: controller.state.value.pageController,
      children: controller.state.value.tabs.map((tab) => tab.page).toList(),
    )));
    controller.jumpToByKey('remote:A');
    controller.jumpToByKey('file:A');
    controller.jumpToByKey('home');
    await tester.pump(const Duration(milliseconds: 110));
    expect(controller.state.value.pageController.page, 0);
    expect(controller.selectedTab?.key, 'home');
  });
}
