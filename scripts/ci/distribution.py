"""Editions actually distributed for each target."""


def editions_for_target(platform, arch):
    return ('cliente',) if (platform, arch) == ('windows', 'x86') else ('cliente', 'suporte')
