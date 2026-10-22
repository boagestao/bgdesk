import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_hbb/common.dart' as common;
import 'package:flutter_hbb/common/widgets/dialog.dart';
import 'package:flutter_hbb/desktop/widgets/remote_toolbar.dart';
import 'package:flutter_hbb/desktop/widgets/tabbar_widget.dart';
import 'package:flutter_hbb/generated_bridge.dart';
import 'package:flutter_hbb/models/input_model.dart';
import 'package:flutter_hbb/models/model.dart';
import 'package:flutter_hbb/models/platform_model.dart';
import 'package:uuid/uuid.dart';

class _Binding extends Fake implements RustdeskImpl {
  @override
  String translate(
          {required String name, required String locale, dynamic hint}) =>
      name;
  @override
  String mainGetLocalOption({required String key, dynamic hint}) => 'Y';
  @override
  bool mainIsOptionFixed({required String key, dynamic hint}) => true;
  @override
  String sessionGetAuditServerSync(
          {required common.SessionID sessionId,
          required String typ,
          dynamic hint}) =>
      'https://audit.example';
  @override
  String sessionGetAuditGuid(
          {required common.SessionID sessionId, dynamic hint}) =>
      sessionId.toString();
  @override
  String sessionGetLastAuditNote(
          {required common.SessionID sessionId, dynamic hint}) =>
      '';
  @override
  bool willSessionCloseCloseSession(
          {required common.SessionID sessionId, dynamic hint}) =>
      true;
}

class _Session extends Fake implements FFI {
  @override
  final common.SessionID sessionId = const Uuid().v4obj();
  @override
  final dialogManager = common.OverlayDialogManager();
}

class _AuditPage extends StatelessWidget {
  final FFI ffi;
  final localOverlay = common.OverlayKeyState();
  _AuditPage(this.ffi) {
    ffi.dialogManager.setOverlayState(localOverlay);
  }
  @override
  Widget build(BuildContext context) => Overlay(
      key: localOverlay.key,
      initialEntries: [OverlayEntry(builder: (_) => const SizedBox())]);
}

class _Input extends Fake implements InputModel {
  bool selected = true;
  int generation = 0;
  bool Function()? selectionReader;
  int Function()? generationReader;
  @override
  bool Function() get isSessionSelected =>
      () => selectionReader?.call() ?? selected;
  @override
  int get inputActivationGeneration => generationReader?.call() ?? generation;
}

class _ScreenSession extends Fake implements FFI {
  @override
  bool closed = false;
  @override
  final _Input inputModel = _Input();
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  setUp(() => platformFFI.setBindingForTesting(_Binding()));

  for (final cancel in [true, false]) {
    testWidgets(
        'exit audit stays visible for a hidden session (cancel=$cancel)',
        (tester) async {
      final session = _Session();
      final page = _AuditPage(session);
      final tabs = DesktopTabController(tabType: DesktopTabType.main);
      tabs.state.value.tabs
          .add(TabInfo(key: 'remote:A', label: 'A', page: page));
      await tester.pumpWidget(MaterialApp(
          navigatorKey: common.globalKey,
          theme: common.MyTheme.lightTheme,
          home: Scaffold(body: Offstage(offstage: true, child: page))));
      expect(page.localOverlay.key!.currentState, isNotNull);
      final result = desktopTryShowTabAuditDialogCloseCancelled(
          id: 'remote:A', tabController: tabs, forceGlobal: true);
      await tester.pumpAndSettle();
      expect(find.byType(AlertDialog), findsOneWidget);
      await tester.tap(find.text(cancel ? 'Cancel' : 'OK'));
      await tester.pumpAndSettle();
      expect(await result, cancel);
      expect(find.byType(AlertDialog), findsNothing);
    });
  }

  for (final reselect in [false, true]) {
    testWidgets(
        'late screen lookup cannot adjust a deactivated session (reselect=$reselect)',
        (tester) async {
      final screen = Completer<Object>();
      var requested = false;
      final mutations = <String>[];
      final messenger =
          TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger;
      const sizes = MethodChannel('flutter/windowsize');
      const windows = MethodChannel('window_manager');
      messenger.setMockMethodCallHandler(sizes, (call) async {
        expect(call.method, 'getWindowInfo');
        requested = true;
        return screen.future;
      });
      messenger.setMockMethodCallHandler(windows, (call) async {
        mutations.add(call.method);
        return null;
      });
      addTearDown(() {
        messenger.setMockMethodCallHandler(sizes, null);
        messenger.setMockMethodCallHandler(windows, null);
      });
      final session = _ScreenSession();
      final tabs = DesktopTabController(tabType: DesktopTabType.main);
      for (final key in ['remote:A', 'home']) {
        tabs.state.value.tabs
            .add(TabInfo(key: key, label: key, page: const SizedBox()));
      }
      session.inputModel.selectionReader =
          () => tabs.selectedTab?.key == 'remote:A';
      session.inputModel.generationReader = () => tabs.selectionGeneration;
      var fullscreenExits = 0;
      final adjustor = ScreenAdjustor(
          id: 'A', ffi: session, cbExitFullscreen: () => fullscreenExits++);
      final pending = adjustor.doAdjustWindow();
      await tester.pump();
      expect(requested, isTrue);
      tabs.jumpToByKey('home');
      if (reselect) tabs.jumpToByKey('remote:A');
      screen.complete({
        'frame': [0.0, 0.0, 800.0, 600.0],
        'scaleFactor': 1.0,
        'screen': {
          'frame': [0.0, 0.0, 1920.0, 1080.0],
          'visibleFrame': [0.0, 0.0, 1920.0, 1040.0],
          'scaleFactor': 1.0
        }
      });
      await tester.pump();
      await pending;
      expect(fullscreenExits, 0);
      expect(mutations, isEmpty);
      await tester.pump(const Duration(milliseconds: 110));
    });
  }
}
