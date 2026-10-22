import re
from datetime import datetime
from string import ascii_letters, digits
from urllib.parse import urlsplit

PACKAGE_ID_CHARACTERS = frozenset(ascii_letters + digits + ".-")
RFC3339_TIMESTAMP = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}[Tt][0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?(?:[Zz]|[+-][0-9]{2}:[0-9]{2})"
)
ARTIFACT_FILE_NAME_PATTERN = re.compile(r"[A-Za-z0-9._-]+")


def validate_release(release_id, version):
    if (
        not release_id
        or not release_id.isascii()
        or release_id in {".", ".."}
        or any(
            char.isspace() or not char.isprintable() or char in "/\\?%#"
            for char in release_id
        )
    ):
        raise ValueError(f"invalid release id: {release_id}")
    from application_version import parse_version
    # Arbitrary signed offline IDs remain supported; public numeric IDs must
    # match the complete revision, not just the upstream base.
    display_version = release_id.removeprefix('v')
    if re.match(r"[0-9]+\.", display_version):
        parse_version(display_version)
        if display_version != version:
            raise ValueError(f"release id {release_id} maps to {display_version}, not {version}")


def validate_published_at(value):
    if not RFC3339_TIMESTAMP.fullmatch(value):
        raise ValueError("published_at must be an RFC 3339 timestamp")
    normalized = value[:-1] + "+00:00" if value[-1] in "Zz" else value
    try:
        datetime.fromisoformat(normalized)
    except ValueError as error:
        raise ValueError(
            "published_at must be an RFC 3339 timestamp"
        ) from error


def validate_artifact_file_name(file_name):
    if (
        not isinstance(file_name, str)
        or file_name in {".", ".."}
        or not ARTIFACT_FILE_NAME_PATTERN.fullmatch(file_name)
    ):
        raise ValueError(f"invalid artifact file name: {file_name}")


def validate_package_id(value):
    if (
        not isinstance(value, str)
        or not value
        or not value.isascii()
        or any(char not in PACKAGE_ID_CHARACTERS for char in value)
        or not any(char.isalnum() for char in value)
    ):
        raise ValueError(f"invalid package id: {value}")
    return value


def validate_release_base_url(value):
    if (
        not isinstance(value, str)
        or not value
        or not value.isascii()
        or any(char.isspace() or not char.isprintable() for char in value)
        or value.endswith("/")
        or "\\" in value
        or "?" in value
        or "#" in value
    ):
        raise ValueError(f"invalid release base URL: {value}")
    try:
        parsed = urlsplit(value)
        parsed.port
    except ValueError as error:
        raise ValueError(f"invalid release base URL: {value}") from error
    if (
        parsed.scheme != "https"
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError(
            "release base URL must be HTTPS and must not contain credentials"
        )
    return value


def release_artifact_url(release_base_url, release_id, file_name, artifact_base_url=None):
    if artifact_base_url is not None:
        validate_release_base_url(artifact_base_url)
        if urlsplit(artifact_base_url).netloc != urlsplit(release_base_url).netloc:
            raise ValueError("artifact origin must match the release origin")
        if urlsplit(artifact_base_url).path:
            raise ValueError("root artifact URL must be an HTTPS origin without a path")
        return f"{artifact_base_url}/{file_name}"
    return f"{release_base_url}/{release_id}/{file_name}"


def root_artifact_name(edition, platform, arch, file_format):
    if edition not in ("cliente", "suporte"):
        raise ValueError("Invalid artifact edition")
    prefix = f"bgdesk-{edition}"
    if platform == "android" and arch == "universal" and file_format == "apk":
        return f"{prefix}-universal.apk"
    if platform == "linux" and arch in ("x86_64", "aarch64"):
        if file_format in ("deb", "rpm", "AppImage") or (arch == "x86_64" and file_format == "pkg.tar.zst"):
            return f"{prefix}-{arch}.{file_format}"
    if platform == "macos" and arch in ("x86_64", "aarch64") and file_format == "dmg":
        return f"{prefix}-{arch}.dmg"
    if platform == "windows" and arch in ("x86_64", "x86") and file_format in ("exe", "inno-exe"):
        suffix = "win32" if arch == "x86" else "win64"
        return f"{prefix}{'-update' if file_format == 'exe' else ''}-{suffix}.exe"
    raise ValueError("Unsupported root artifact selector")
