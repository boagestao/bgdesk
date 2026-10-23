use crate::update_metadata::{UpdateArtifactQuery, VerifiedUpdateArtifact};
use hbb_common::{bail, ResultType};
use std::{path::PathBuf, sync::Mutex};

lazy_static::lazy_static! {
    static ref VERIFIED_UPDATE_FEED: Mutex<Option<crate::update_metadata::VerifiedUpdateFeed>> = Mutex::new(None);
    static ref VERIFIED_UPDATE_ARTIFACT: Mutex<Option<(VerifiedUpdateArtifact, Vec<u8>)>> = Mutex::new(None);
}

pub(crate) fn current_update_platform() -> &'static str {
    #[cfg(target_os = "windows")]
    {
        "windows"
    }
    #[cfg(target_os = "macos")]
    {
        "macos"
    }
    #[cfg(not(any(target_os = "windows", target_os = "macos")))]
    {
        std::env::consts::OS
    }
}

pub(crate) fn current_update_arch() -> &'static str {
    #[cfg(all(target_os = "windows", not(feature = "flutter")))]
    {
        "x86"
    }
    #[cfg(not(all(target_os = "windows", not(feature = "flutter"))))]
    {
        std::env::consts::ARCH
    }
}

pub(crate) fn current_update_format(update_msi: bool) -> &'static str {
    #[cfg(any(
        not(target_os = "windows"),
        all(target_os = "windows", not(feature = "flutter"))
    ))]
    let _ = update_msi;
    #[cfg(all(target_os = "windows", feature = "flutter"))]
    {
        if update_msi {
            return "msi";
        }
        "exe"
    }
    #[cfg(all(target_os = "windows", not(feature = "flutter")))]
    {
        "exe"
    }
    #[cfg(target_os = "macos")]
    {
        "dmg"
    }
    #[cfg(not(any(target_os = "windows", target_os = "macos")))]
    {
        "unknown"
    }
}

pub fn current_update_artifact_query(update_msi: bool) -> UpdateArtifactQuery<'static> {
    UpdateArtifactQuery {
        platform: current_update_platform(),
        arch: current_update_arch(),
        format: current_update_format(update_msi),
    }
}

pub fn verified_update_artifact_for_release_page_url(
    release_page_url: &str,
    query: UpdateArtifactQuery<'_>,
) -> ResultType<VerifiedUpdateArtifact> {
    let feed = verified_feed_for_url(release_page_url)?;
    let artifact = feed.artifact(&query)?;
    *VERIFIED_UPDATE_ARTIFACT.lock().unwrap() =
        Some((artifact.clone(), feed.signed_bytes().to_vec()));
    Ok(artifact)
}

pub fn verified_update_artifact_for_download_url(
    download_url: &str,
) -> ResultType<VerifiedUpdateArtifact> {
    VERIFIED_UPDATE_ARTIFACT
        .lock()
        .unwrap()
        .as_ref()
        .filter(|(artifact, _)| artifact.url == download_url)
        .map(|(artifact, _)| artifact.clone())
        .ok_or_else(|| hbb_common::anyhow::anyhow!("update artifact was not verified"))
}

#[cfg(target_os = "linux")]
pub(crate) fn verified_update_feed_for_download_url(download_url: &str) -> ResultType<Vec<u8>> {
    VERIFIED_UPDATE_ARTIFACT
        .lock()
        .unwrap()
        .as_ref()
        .filter(|(artifact, _)| artifact.url == download_url)
        .map(|(_, bytes)| bytes.clone())
        .ok_or_else(|| hbb_common::anyhow::anyhow!("update artifact was not verified"))
}

pub(crate) fn cache_update_feed(feed: crate::update_metadata::VerifiedUpdateFeed) {
    *VERIFIED_UPDATE_FEED.lock().unwrap() = Some(feed);
}

pub(crate) fn clear_update_feed() {
    *VERIFIED_UPDATE_FEED.lock().unwrap() = None;
}

pub(crate) fn latest_update_version() -> String {
    VERIFIED_UPDATE_FEED
        .lock()
        .unwrap()
        .as_ref()
        .map(|feed| feed.version().to_owned())
        .unwrap_or_default()
}

pub(super) fn verified_update_artifact_from_release_page_url(
    update_url: &str,
    query: &UpdateArtifactQuery<'_>,
) -> ResultType<VerifiedUpdateArtifact> {
    verified_feed_for_url(update_url)?.artifact(query)
}

fn verified_feed_for_url(
    update_url: &str,
) -> ResultType<crate::update_metadata::VerifiedUpdateFeed> {
    if !crate::common::uses_public_update_channel() {
        bail!("Public update channel is not enabled for this client");
    }
    if update_url != crate::update_source::latest_url() {
        bail!("Update URL is not the BGDesk signed latest feed");
    }
    VERIFIED_UPDATE_FEED
        .lock()
        .unwrap()
        .as_ref()
        .ok_or_else(|| {
            hbb_common::anyhow::anyhow!(
                "No verified update feed available; check for updates again"
            )
        })
        .cloned()
}

pub fn get_update_download_file_from_url(url: &str) -> Option<PathBuf> {
    #[cfg(target_os = "linux")]
    return crate::update_source::download_file_name(url)
        .and_then(|name| crate::linux_update::download_path(name).ok());
    #[cfg(not(target_os = "linux"))]
    crate::update_source::download_file_name(url).map(|name| std::env::temp_dir().join(name))
}
