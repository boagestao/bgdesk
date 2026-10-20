"""Restore and validate the existing Android signing identity without logging secrets."""
import base64
import os
from pathlib import Path
import subprocess
import tempfile

NAMES = ('ANDROID_SIGNING_KEY', 'ANDROID_ALIAS', 'ANDROID_KEY_STORE_PASSWORD', 'ANDROID_KEY_PASSWORD')


def local_secrets(root):
    properties = {}
    for line in (root / 'config/android-key.properties').read_text().splitlines():
        if line.strip() and not line.lstrip().startswith(('#', '!')):
            key, value = line.split('=', 1)
            properties[key.strip()] = value
    path = Path(properties.get('storeFile', 'android-key.jks'))
    if not path.is_absolute():
        path = root / 'config' / path
    return dict(zip(NAMES, (base64.b64encode(path.read_bytes()).decode('ascii'),
                           properties['keyAlias'], properties['storePassword'], properties['keyPassword'])))


def escape_property(value):
    # java.util.Properties.load(InputStream) reads ISO-8859-1 and escape sequences.
    result = ''
    for char in value:
        if char in '\\:=#! ':
            result += '\\' + char
        elif char in '\n\r\t':
            result += {'\n': '\\n', '\r': '\\r', '\t': '\\t'}[char]
        elif ord(char) > 126 or ord(char) < 32:
            encoded = char.encode('utf-16-be')
            result += ''.join(f'\\u{int.from_bytes(encoded[i:i+2], "big"):04x}'
                              for i in range(0, len(encoded), 2))
        else:
            result += char
    return result


def write_private(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError('Signing files must not be symbolic links')
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, 'wb') as handle:
        handle.write(data)


def validate(values, directory):
    if any(not values.get(name) for name in NAMES):
        raise ValueError('All four Android signing secrets are required')
    key = directory / 'android-key.jks'
    write_private(key, base64.b64decode(values['ANDROID_SIGNING_KEY'], validate=True))
    environment = dict(os.environ, BGDESK_STORE_PASS=values['ANDROID_KEY_STORE_PASSWORD'],
                       BGDESK_KEY_PASS=values['ANDROID_KEY_PASSWORD'])
    # Importing one private key verifies the store password, key password, and alias.
    with tempfile.TemporaryDirectory(prefix='bgdesk-key-check-') as temporary:
        result = subprocess.run(['keytool', '-importkeystore', '-noprompt', '-srckeystore', str(key),
                                 '-srcstorepass:env', 'BGDESK_STORE_PASS', '-srckeypass:env', 'BGDESK_KEY_PASS',
                                 '-srcalias', values['ANDROID_ALIAS'], '-destkeystore', str(Path(temporary) / 'check.p12'),
                                 '-deststoretype', 'PKCS12', '-deststorepass:env', 'BGDESK_STORE_PASS'],
                                env=environment, capture_output=True, timeout=30)
        if result.returncode:
            raise ValueError('Android keystore, alias or signing passwords failed validation')
    return key


def restore(values, root):
    key = validate(values, Path(os.environ.get('RUNNER_TEMP', tempfile.gettempdir())) / 'bgdesk-android-signing')
    properties = dict(storeFile=str(key.resolve()), keyAlias=values['ANDROID_ALIAS'],
                      storePassword=values['ANDROID_KEY_STORE_PASSWORD'], keyPassword=values['ANDROID_KEY_PASSWORD'])
    write_private(root / 'flutter/android/key.properties',
                  ''.join(f'{k}={escape_property(v)}\n' for k, v in properties.items()).encode('ascii'))


if __name__ == '__main__':
    restore(os.environ, Path(__file__).resolve().parents[2])
    print('Android signing identity and both passwords validated; temporary files have mode 0600.')
