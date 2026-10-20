#!/usr/bin/env python3
"""Drop uni_links' unused Android v1 entry point for Flutter 3.29 and newer.

The pinned plugin already implements FlutterPlugin/ActivityAware (embedding v2).
Flutter removed PluginRegistry.Registrar; its old static registration method must
not be compiled. Keep the v2 engine/activity and deep-link handlers unchanged.
https://docs.flutter.dev/release/breaking-changes/v1-android-embedding
"""
import json
from pathlib import Path

LEGACY = '''    /** Plugin registration. */
    public static void registerWith(@NonNull PluginRegistry.Registrar registrar) {
        // Detect if we've been launched in background
        if (registrar.activity() == null) {
            return;
        }

        final UniLinksPlugin instance = new UniLinksPlugin();
        instance.context = registrar.context();
        register(registrar.messenger(), instance);

        instance.handleIntent(registrar.context(), registrar.activity().getIntent());
        registrar.addNewIntentListener(instance);
    }

'''


def patch_source(source):
    if 'PluginRegistry.Registrar' not in source:
        return source
    if source.count(LEGACY) != 1:
        raise ValueError('uni_links legacy registration changed; review the pinned plugin before patching')
    result = source.replace(LEGACY, '')
    if 'PluginRegistry.Registrar' in result:
        raise ValueError('Unexpected additional Android v1 API in uni_links')
    return result


def patch_plugins(manifest):
    plugins = json.loads(manifest.read_text())['plugins']['android']
    plugin = next(item for item in plugins if item['name'] == 'uni_links')
    path = Path(plugin['path']) / 'android/src/main/java/name/avioli/unilinks/UniLinksPlugin.java'
    source = path.read_text()
    patched = patch_source(source)
    if patched != source:
        path.write_text(patched)
    print('uni_links Android registration verified for Flutter embedding v2.')


if __name__ == '__main__':
    patch_plugins(Path(__file__).resolve().parents[1] / 'flutter/.flutter-plugins-dependencies')
