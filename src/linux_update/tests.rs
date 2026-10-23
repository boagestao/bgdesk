use super::*;
use sha2::{Digest, Sha256};
use std::os::unix::fs::symlink;

fn artifact(bytes: &[u8]) -> VerifiedUpdateArtifact {
    VerifiedUpdateArtifact {
        version: "1.5.1-2".to_owned(),
        url: "https://bgdesk.com/bgdesk-suporte-x86_64.AppImage".to_owned(),
        #[cfg(target_os = "macos")]
        file_name: "bgdesk-suporte-x86_64.AppImage".to_owned(),
        size: bytes.len() as u64,
        sha256: hex::encode(Sha256::digest(bytes)),
    }
}

#[test]
fn downloads_do_not_overwrite_a_running_appimage_in_the_public_temp_directory() {
    let name = "bgdesk-suporte-aarch64.AppImage";
    let path = download_path(name).unwrap();
    assert_ne!(path, std::env::temp_dir().join(name));
    assert_eq!(path, download_path(name).unwrap());
    assert_eq!(
        fs::metadata(path.parent().unwrap()).unwrap().mode() & 0o777,
        0o700
    );
    for name in ["..", "", "../application.AppImage", "/tmp/app", "app;rm"] {
        assert!(download_path(name).is_err());
    }
}

#[test]
fn selects_the_owner_of_the_installed_binary_instead_of_guessing_the_distro() {
    assert_eq!(
        select_package_kind(Some("bgdesk: /usr/share/bgdesk/bgdesk"), None, None).unwrap(),
        PackageKind::Deb
    );
    assert_eq!(
        select_package_kind(Some("bgdesk:amd64: /usr/share/bgdesk/bgdesk"), None, None).unwrap(),
        PackageKind::Deb
    );
    assert_eq!(
        select_package_kind(None, Some("bgdesk"), None).unwrap(),
        PackageKind::Rpm
    );
    let arch_name = format!("bgdesk-{}", crate::update_source::UPDATE_EDITION);
    assert_eq!(
        select_package_kind(None, None, Some(&arch_name)).unwrap(),
        PackageKind::Arch
    );
    assert!(select_package_kind(None, None, None).is_err());
    assert!(select_package_kind(Some("other: /usr/share/bgdesk/bgdesk"), None, None).is_err());
    assert!(select_package_kind(Some("bgdesk: /tmp/bgdesk"), None, None).is_err());
    assert!(select_package_kind(None, Some("other"), None).is_err());
    let other = if crate::update_source::UPDATE_EDITION == "cliente" {
        "bgdesk-suporte"
    } else {
        "bgdesk-cliente"
    };
    assert!(select_package_kind(None, None, Some(other)).is_err());
    assert!(select_package_kind(
        Some("bgdesk: /usr/share/bgdesk/bgdesk"),
        Some("bgdesk"),
        None
    )
    .is_err());
}

#[test]
fn package_commands_use_literal_arguments_and_preserve_package_manager_checks() {
    let path = Path::new("/var/tmp/update & $(touch unexpected); 'quoted'/update.pkg.tar.zst");
    for (kind, executable, operation) in [
        (PackageKind::Deb, "/usr/bin/apt-get", "install"),
        (PackageKind::Rpm, "/usr/bin/rpm", "--upgrade"),
        (PackageKind::Arch, "/usr/bin/pacman", "--upgrade"),
    ] {
        let command = kind.installer(path);
        assert_eq!(command.get_program(), executable);
        let args: Vec<_> = command.get_args().collect();
        assert_eq!(args.last().copied(), Some(path.as_os_str()));
        assert!(args.iter().any(|arg| *arg == operation));
        assert!(!args.iter().any(|arg| [
            "--nodeps",
            "--nosignature",
            "--force",
            "--allow-downgrades",
            "-c"
        ]
        .iter()
        .any(|bad| arg == bad)));
        assert!(command
            .get_envs()
            .any(|(key, value)| key == "LC_ALL" && value == Some(std::ffi::OsStr::new("C"))));
    }
    assert!(!HELPER_COMMAND.starts_with("--"));
}

#[test]
fn cancel_and_missing_graphical_authorization_are_distinct_from_success() {
    assert_eq!(pkexec_outcome(Some(0)).unwrap(), UpdateOutcome::Installed);
    assert_eq!(pkexec_outcome(Some(126)).unwrap(), UpdateOutcome::Cancelled);
    assert!(pkexec_outcome(Some(127)).is_err());
    assert!(pkexec_outcome(Some(1)).is_err());
    assert!(pkexec_outcome(None).is_err());
}

#[test]
fn verified_copy_rejects_replaced_bytes_size_and_symlinks_and_cleans_failed_copies() {
    let directory = PrivateDirectory::new(&std::env::temp_dir()).unwrap();
    let source = directory.0.join("source");
    let destination = directory.0.join("verified");
    let bytes = b"signed package";
    fs::write(&source, bytes).unwrap();
    let expected = artifact(bytes);
    let file = copy_verified(
        &source,
        &destination,
        &expected,
        Some(unsafe { libc::geteuid() }),
    )
    .unwrap();
    assert_eq!(file.metadata().unwrap().mode() & 0o777, 0o600);
    assert_eq!(fs::read(&destination).unwrap(), bytes);
    drop(file);
    fs::remove_file(&destination).unwrap();
    fs::write(&source, b"altered bytes!").unwrap();
    assert!(copy_verified(&source, &destination, &expected, None).is_err());
    assert!(!destination.exists());
    fs::write(&source, b"short").unwrap();
    assert!(copy_verified(&source, &destination, &expected, None).is_err());
    assert!(!destination.exists());
    let link = directory.0.join("source-link");
    symlink(&source, &link).unwrap();
    assert!(copy_verified(&link, &destination, &expected, None).is_err());
    assert!(!destination.exists());
}

#[test]
fn appimage_is_replaced_atomically_and_keeps_executable_permissions_without_root() {
    let directory = PrivateDirectory::new(&std::env::temp_dir()).unwrap();
    let target = directory.0.join("BGDesk.AppImage");
    let downloaded = directory.0.join("download");
    fs::write(&target, b"old application").unwrap();
    fs::set_permissions(&target, fs::Permissions::from_mode(0o750)).unwrap();
    let inode = fs::metadata(&target).unwrap().ino();
    let bytes = b"new application";
    fs::write(&downloaded, bytes).unwrap();
    replace_appimage(&downloaded, &target, &artifact(bytes)).unwrap();
    assert_eq!(fs::read(&target).unwrap(), bytes);
    assert_ne!(fs::metadata(&target).unwrap().ino(), inode);
    assert_eq!(fs::metadata(&target).unwrap().mode() & 0o777, 0o750);
    assert_eq!(fs::read_dir(&directory.0).unwrap().count(), 2);
}

#[test]
fn invalid_appimage_updates_preserve_the_old_file_and_do_not_follow_target_links() {
    let directory = PrivateDirectory::new(&std::env::temp_dir()).unwrap();
    let target = directory.0.join("BGDesk.AppImage");
    let download = directory.0.join("download");
    fs::write(&target, b"old application").unwrap();
    fs::write(&download, b"corrupt").unwrap();
    assert!(replace_appimage(&download, &target, &artifact(b"new application")).is_err());
    assert_eq!(fs::read(&target).unwrap(), b"old application");
    let link = directory.0.join("alias.AppImage");
    symlink(&target, &link).unwrap();
    assert!(replace_appimage(&download, &link, &artifact(b"corrupt")).is_err());
    assert_eq!(fs::read(&target).unwrap(), b"old application");
    assert!(replace_appimage(
        &download,
        &directory.0.join("missing"),
        &artifact(b"corrupt")
    )
    .is_err());
}

#[test]
fn unprivileged_helper_invocations_and_incomplete_arguments_are_rejected() {
    assert!(run_privileged(&[]).is_err());
    assert!(run_privileged(&["package".to_owned()]).is_err());
}
