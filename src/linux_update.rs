//! Interactive Linux updates. Only an installed, root-owned BGDesk executable
//! is elevated; it independently authenticates the feed and copies the package
//! into a private root directory before invoking a package manager.
use crate::update_metadata::{UpdateArtifactQuery, VerifiedUpdateArtifact};
use hbb_common::{
    anyhow::{anyhow, Context},
    bail, libc, ResultType,
};
use std::{
    fs::{self, File, OpenOptions},
    io::{Read, Seek, SeekFrom, Write},
    os::unix::fs::{DirBuilderExt, MetadataExt, OpenOptionsExt, PermissionsExt},
    path::{Path, PathBuf},
    process::{Command, Stdio},
    sync::Mutex,
};

// Without `--`: package service hooks use pkill -f 'bgdesk --'. The updater
// must survive that stop so it can report the installer's result and clean up.
pub(crate) const HELPER_COMMAND: &str = "linux-update";
const INSTALLED_EXE: &str = "/usr/share/bgdesk/bgdesk";
const PKEXEC: &str = "/usr/bin/pkexec";
const MAX_FEED_BYTES: u64 = 1024 * 1024;
static APPLY_LOCK: Mutex<()> = Mutex::new(());
static DOWNLOAD_DIRECTORY: Mutex<Option<PrivateDirectory>> = Mutex::new(None);

#[derive(Clone, Copy, Debug, PartialEq)]
enum PackageKind {
    Deb,
    Rpm,
    Arch,
}

impl PackageKind {
    fn format(self) -> &'static str {
        match self {
            Self::Deb => "deb",
            Self::Rpm => "rpm",
            Self::Arch => "pkg.tar.zst",
        }
    }

    fn installer(self, package: &Path) -> Command {
        let (program, args): (&str, &[&str]) = match self {
            Self::Deb => (
                "/usr/bin/apt-get",
                &[
                    "-y",
                    "--no-remove",
                    "-o",
                    "Dpkg::Options::=--force-confold",
                    "install",
                    "--",
                ],
            ),
            Self::Rpm => ("/usr/bin/rpm", &["--upgrade", "--"]),
            Self::Arch => ("/usr/bin/pacman", &["--upgrade", "--noconfirm", "--"]),
        };
        let mut command = clean_command(program);
        command
            .args(args)
            .arg(package)
            .env("DEBIAN_FRONTEND", "noninteractive");
        command
    }
}

enum Target {
    Package(PackageKind),
    AppImage(PathBuf),
}

#[derive(Debug, PartialEq)]
pub(crate) enum UpdateOutcome {
    Installed,
    Cancelled,
}

fn clean_command(program: &str) -> Command {
    let mut command = Command::new(program);
    command
        .env_clear()
        .env("PATH", "/usr/sbin:/usr/bin:/sbin:/bin")
        .env("LC_ALL", "C")
        .stdin(Stdio::null());
    command
}

fn query(program: &str, args: &[&str]) -> Option<String> {
    let output = clean_command(program).args(args).output().ok()?;
    output
        .status
        .success()
        .then(|| String::from_utf8_lossy(&output.stdout).trim().to_owned())
}

fn select_package_kind(
    deb_owner: Option<&str>,
    rpm_owner: Option<&str>,
    arch_owner: Option<&str>,
) -> ResultType<PackageKind> {
    let edition = format!("bgdesk-{}", crate::update_source::UPDATE_EDITION);
    let mut matches = Vec::new();
    if deb_owner.map_or(false, |owner| {
        owner.lines().any(|line| {
            line.split_once(": ").map_or(false, |(package, path)| {
                package.split(':').next() == Some("bgdesk") && path == INSTALLED_EXE
            })
        })
    }) {
        matches.push(PackageKind::Deb);
    }
    if rpm_owner == Some("bgdesk") {
        matches.push(PackageKind::Rpm);
    }
    if arch_owner == Some(edition.as_str()) || arch_owner == Some("bgdesk") {
        matches.push(PackageKind::Arch);
    }
    match matches.as_slice() {
        [kind] => Ok(*kind),
        [] => bail!("The installed BGDesk package was not found"),
        _ => bail!("More than one package manager owns the BGDesk installation"),
    }
}

fn system_package_kind() -> ResultType<PackageKind> {
    let installed = fs::canonicalize(INSTALLED_EXE).context("BGDesk is not installed")?;
    if fs::canonicalize(std::env::current_exe()?)? != installed {
        bail!("This executable is not the installed BGDesk application");
    }
    ensure_root_owned(&installed)?;
    let deb = query("/usr/bin/dpkg-query", &["-S", INSTALLED_EXE]);
    let rpm = query("/usr/bin/rpm", &["-qf", "--qf", "%{NAME}", INSTALLED_EXE]);
    let arch = query("/usr/bin/pacman", &["-Qoq", INSTALLED_EXE]);
    select_package_kind(deb.as_deref(), rpm.as_deref(), arch.as_deref())
}

fn ensure_root_owned(path: &Path) -> ResultType<()> {
    for component in path.ancestors() {
        let metadata = fs::symlink_metadata(component)?;
        if metadata.uid() != 0 || metadata.mode() & 0o022 != 0 || metadata.file_type().is_symlink()
        {
            bail!(
                "The installed application path is not protected: {}",
                component.display()
            );
        }
    }
    Ok(())
}

fn target() -> ResultType<Target> {
    if let Some(path) = std::env::var_os("APPIMAGE") {
        let path = PathBuf::from(path);
        let metadata = fs::symlink_metadata(&path).context("The AppImage was not found")?;
        if !path.is_absolute()
            || !metadata.is_file()
            || metadata.file_type().is_symlink()
            || metadata.uid() != unsafe { libc::geteuid() }
        {
            bail!("The AppImage is not a regular file owned by this user");
        }
        return Ok(Target::AppImage(path));
    }
    let kind = system_package_kind()?;
    if !Path::new(PKEXEC).is_file() {
        bail!("Graphical administrator authorization is unavailable (pkexec missing)");
    }
    Ok(Target::Package(kind))
}

pub(crate) fn artifact_query() -> ResultType<UpdateArtifactQuery<'static>> {
    let format = match target()? {
        Target::Package(kind) => kind.format(),
        Target::AppImage(_) => "AppImage",
    };
    Ok(UpdateArtifactQuery {
        platform: "linux",
        arch: std::env::consts::ARCH,
        format,
    })
}

struct PrivateDirectory(PathBuf);
impl PrivateDirectory {
    fn new(parent: &Path) -> ResultType<Self> {
        let path = parent.join(format!("bgdesk-update-{}", uuid::Uuid::new_v4()));
        fs::DirBuilder::new().mode(0o700).create(&path)?;
        Ok(Self(path))
    }
}
impl Drop for PrivateDirectory {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

pub(crate) fn download_path(file_name: &str) -> ResultType<PathBuf> {
    if file_name.is_empty()
        || matches!(file_name, "." | "..")
        || !file_name
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b'-'))
    {
        bail!("Invalid Linux update file name");
    }
    let mut directory = DOWNLOAD_DIRECTORY.lock().unwrap();
    if directory.is_none() {
        *directory = Some(PrivateDirectory::new(&std::env::temp_dir())?);
    }
    let path = &directory.as_ref().unwrap().0;
    let metadata = fs::symlink_metadata(path)?;
    if !metadata.is_dir()
        || metadata.file_type().is_symlink()
        || metadata.uid() != unsafe { libc::geteuid() }
        || metadata.mode() & 0o077 != 0
    {
        bail!("Untrusted Linux download directory");
    }
    // A running AppImage can itself be named /tmp/<artifact>. Never download
    // onto that public path before the verified, atomic replacement step.
    Ok(path.join(file_name))
}

fn open_regular(path: &Path, owner: Option<u32>) -> ResultType<File> {
    let file = OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC | libc::O_NONBLOCK | libc::O_NOCTTY)
        .open(path)?;
    let metadata = file.metadata()?;
    if !metadata.is_file() || owner.map_or(false, |uid| metadata.uid() != uid) {
        bail!("Invalid update input: {}", path.display());
    }
    Ok(file)
}

fn copy_verified(
    source: &Path,
    destination: &Path,
    artifact: &VerifiedUpdateArtifact,
    owner: Option<u32>,
) -> ResultType<File> {
    let mut source = open_regular(source, owner)?;
    let mut output = OpenOptions::new()
        .read(true)
        .write(true)
        .create_new(true)
        .mode(0o600)
        .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
        .open(destination)?;
    let result = (|| -> ResultType<()> {
        let count = std::io::copy(
            &mut Read::by_ref(&mut source).take(artifact.size.saturating_add(1)),
            &mut output,
        )?;
        if count != artifact.size {
            bail!("Update artifact size mismatch");
        }
        output.seek(SeekFrom::Start(0))?;
        crate::update_hash::verify_sha256_reader(&mut output, &artifact.sha256)
            .map_err(|_| anyhow!("Update artifact SHA-256 mismatch"))?;
        output.sync_all()?;
        Ok(())
    })();
    if let Err(error) = result {
        drop(output);
        let _ = fs::remove_file(destination);
        return Err(error);
    }
    Ok(output)
}

fn replace_appimage(
    source: &Path,
    target: &Path,
    artifact: &VerifiedUpdateArtifact,
) -> ResultType<()> {
    let original = fs::symlink_metadata(target)?;
    if !original.is_file()
        || original.file_type().is_symlink()
        || original.uid() != unsafe { libc::geteuid() }
    {
        bail!("The AppImage cannot be replaced by this user");
    }
    let directory = PrivateDirectory::new(
        target
            .parent()
            .ok_or_else(|| anyhow!("Invalid AppImage path"))?,
    )?;
    let replacement = directory.0.join("update.AppImage");
    let file = copy_verified(source, &replacement, artifact, None)?;
    file.set_permissions(fs::Permissions::from_mode(
        (original.mode() & 0o777) | 0o100,
    ))?;
    file.sync_all()?;
    let current = fs::symlink_metadata(target)?;
    if current.dev() != original.dev()
        || current.ino() != original.ino()
        || current.file_type().is_symlink()
    {
        bail!("The AppImage changed while preparing its update");
    }
    fs::rename(&replacement, target)?;
    // The running process retains its old inode; the next launch uses the new file.
    Ok(())
}

fn pkexec_outcome(code: Option<i32>) -> ResultType<UpdateOutcome> {
    match code {
        Some(0) => Ok(UpdateOutcome::Installed),
        Some(126) => Ok(UpdateOutcome::Cancelled),
        Some(127) => bail!("Administrator authorization was denied or no graphical authentication agent is available"),
        _ => bail!("The Linux update installer failed ({code:?})"),
    }
}

pub(crate) fn apply(
    download: &Path,
    artifact: &VerifiedUpdateArtifact,
    signed_feed: &[u8],
) -> ResultType<UpdateOutcome> {
    let _lock = APPLY_LOCK
        .try_lock()
        .map_err(|_| anyhow!("An update is already in progress"))?;
    ensure_no_active_sessions()?;
    // Re-authenticate even the cached snapshot, selecting the installed format.
    let target = target()?;
    let format = match &target {
        Target::Package(kind) => kind.format(),
        Target::AppImage(_) => "AppImage",
    };
    let feed = crate::update_metadata::verify_latest_feed(signed_feed)?;
    let selected = feed.artifact(&UpdateArtifactQuery {
        platform: "linux",
        arch: std::env::consts::ARCH,
        format,
    })?;
    if selected.url != artifact.url
        || selected.sha256 != artifact.sha256
        || selected.size != artifact.size
        || !crate::update_source::is_newer_update(feed.version(), crate::VERSION)?
    {
        bail!("The verified update no longer matches this installation");
    }
    match target {
        Target::AppImage(path) => {
            replace_appimage(download, &path, &selected)?;
            Ok(UpdateOutcome::Installed)
        }
        Target::Package(_) => {
            let directory = PrivateDirectory::new(&std::env::temp_dir())?;
            let feed_path = directory.0.join("latest.json");
            OpenOptions::new()
                .write(true)
                .create_new(true)
                .mode(0o600)
                .open(&feed_path)?
                .write_all(signed_feed)?;
            // Polkit owns the authentication dialog and credentials. Never fall
            // back to a textual agent or pass passwords through application code.
            let output = Command::new(PKEXEC)
                .arg("--disable-internal-agent")
                .arg(INSTALLED_EXE)
                .arg(HELPER_COMMAND)
                .arg(download)
                .arg(&feed_path)
                .stdin(Stdio::null())
                .stdout(Stdio::null())
                .stderr(Stdio::piped())
                .output()?;
            if !output.status.success() && output.status.code() != Some(126) {
                let detail: String = String::from_utf8_lossy(&output.stderr)
                    .chars()
                    .take(4096)
                    .collect();
                hbb_common::log::warn!("Linux update helper failed: {}: {}", output.status, detail);
            }
            pkexec_outcome(output.status.code())
        }
    }
}

fn ensure_no_active_sessions() -> ResultType<()> {
    if !crate::updater::has_no_active_conns() {
        bail!("Close active sessions before updating");
    }
    hbb_common::tokio::runtime::Runtime::new()?.block_on(async {
        let mut uids = crate::ipc::running_server_uids_for_current_exe()?;
        uids.sort_unstable();
        uids.dedup();
        for uid in uids {
            let mut connection = crate::ipc::connect_for_uid(1_000, uid, "").await?;
            connection
                .send(&crate::ipc::Data::HasNoActiveConns(None))
                .await?;
            match connection.next_timeout(1_000).await? {
                Some(crate::ipc::Data::HasNoActiveConns(Some(true))) => {}
                _ => bail!("Active sessions or unknown connection state; update deferred"),
            }
        }
        Ok(())
    })
}

pub(crate) fn run_privileged(args: &[String]) -> ResultType<()> {
    if unsafe { libc::geteuid() } != 0 {
        bail!("Linux package updates require administrator authorization");
    }
    let [download, feed_path] = args else {
        bail!("Invalid Linux update arguments");
    };
    let caller_uid: u32 = std::env::var("PKEXEC_UID")
        .unwrap_or_else(|_| "0".to_owned())
        .parse()?;
    let kind = system_package_kind()?;
    let lock = OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .mode(0o600)
        .custom_flags(libc::O_NOFOLLOW | libc::O_CLOEXEC)
        .open("/run/bgdesk-update.lock")?;
    use std::os::fd::AsRawFd;
    if unsafe { libc::flock(lock.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) } != 0 {
        bail!("Another Linux update is in progress");
    }
    let mut bytes = Vec::new();
    open_regular(Path::new(feed_path), Some(caller_uid))?
        .take(MAX_FEED_BYTES + 1)
        .read_to_end(&mut bytes)?;
    if bytes.len() as u64 > MAX_FEED_BYTES {
        bail!("Update feed is too large");
    }
    let feed = crate::update_metadata::verify_latest_feed(&bytes)?;
    if !crate::update_source::is_newer_update(feed.version(), crate::VERSION)? {
        bail!("Refusing to reinstall or downgrade BGDesk");
    }
    let artifact = feed.artifact(&UpdateArtifactQuery {
        platform: "linux",
        arch: std::env::consts::ARCH,
        format: kind.format(),
    })?;
    let directory = PrivateDirectory::new(Path::new("/var/tmp"))?;
    let package = directory.0.join(format!("update.{}", kind.format()));
    let _file = copy_verified(Path::new(download), &package, &artifact, Some(caller_uid))?;
    ensure_no_active_sessions()?;
    let status = kind
        .installer(&package)
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()?;
    if !status.success() {
        bail!("The package manager failed ({status})");
    }
    let version = query(INSTALLED_EXE, &["--version"])
        .ok_or_else(|| anyhow!("The updated application could not be started"))?;
    if version != artifact.version {
        bail!("The installed BGDesk version does not match the signed update");
    }
    Ok(())
}

#[cfg(test)]
mod tests;
