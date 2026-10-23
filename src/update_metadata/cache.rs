//! Verified feed state is shared by desktop and mobile update notifications.
//! Keep it independent of the desktop-only installer (`crate::updater`).
use super::VerifiedUpdateFeed;
use hbb_common::{anyhow::anyhow, ResultType};
use std::sync::Mutex;

static VERIFIED_UPDATE_FEED: Mutex<Option<VerifiedUpdateFeed>> = Mutex::new(None);

pub(crate) fn cache_update_feed(feed: VerifiedUpdateFeed) {
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

pub(crate) fn cached_update_feed() -> ResultType<VerifiedUpdateFeed> {
    VERIFIED_UPDATE_FEED
        .lock()
        .unwrap()
        .clone()
        .ok_or_else(|| anyhow!("No verified update feed available; check for updates again"))
}
