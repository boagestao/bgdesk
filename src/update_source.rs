use hbb_common::{bail, ResultType};

pub(crate) const UPDATE_ORIGIN: &str = match option_env!("BGDESK_UPDATE_ORIGIN") {
    Some(origin) => origin,
    None => "https://bgdesk.com",
};
#[cfg(feature = "incoming-only")]
pub(crate) const UPDATE_EDITION: &str = "cliente";
#[cfg(not(feature = "incoming-only"))]
pub(crate) const UPDATE_EDITION: &str = "suporte";

pub(crate) fn latest_url() -> String {
    format!("{UPDATE_ORIGIN}/updates/{UPDATE_EDITION}/latest.json")
}

pub(crate) fn release_url(release_id: &str) -> String {
    format!("{UPDATE_ORIGIN}/updates/{UPDATE_EDITION}/{release_id}")
}

pub(crate) fn display_version_from_release_id(release_id: &str) -> ResultType<String> {
    let version = release_id.strip_prefix('v').unwrap_or(release_id);
    let parts = version.split('.').collect::<Vec<_>>();
    if parts.len() != 3
        || parts.iter().any(|part| {
            part.is_empty()
                || !part.bytes().all(|byte| byte.is_ascii_digit())
                || part.parse::<u16>().is_err()
        })
        || parts.iter().all(|part| part.parse::<u16>() == Ok(0))
    {
        bail!("Release id is not a stable display version: {release_id}");
    }
    Ok(version.to_owned())
}

pub(crate) fn release_id_from_update_url(update_url: &str) -> ResultType<String> {
    let prefix = format!("{UPDATE_ORIGIN}/updates/{UPDATE_EDITION}/");
    let Some(release_id) = update_url.strip_prefix(&prefix) else {
        bail!("Update URL is not a BGDesk {UPDATE_EDITION} release URL");
    };
    let release_id = release_id.strip_suffix('/').unwrap_or(release_id);
    display_version_from_release_id(release_id)?;
    Ok(release_id.to_owned())
}

pub(crate) fn download_file_name(download_url: &str) -> Option<&str> {
    let (release, file_name) = download_url.rsplit_once('/')?;
    release_id_from_update_url(release).ok()?;
    if file_name.is_empty()
        || matches!(file_name, "." | "..")
        || !file_name
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b'-'))
    {
        return None;
    }
    // A release URL may have a trailing slash, but artifact paths must be canonical.
    let release_id = release_id_from_update_url(release).ok()?;
    (download_url == format!("{}/{file_name}", release_url(&release_id))).then_some(file_name)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn accepts_own_edition_and_stable_releases() {
        let release = release_url("v1.5.2");
        assert_eq!(release_id_from_update_url(&release).unwrap(), "v1.5.2");
        assert_eq!(
            release_id_from_update_url(&format!("{release}/")).unwrap(),
            "v1.5.2"
        );
        assert_eq!(display_version_from_release_id("v1.5.2").unwrap(), "1.5.2");
        assert_eq!(
            download_file_name(&format!("{release}/bgdesk.dmg")),
            Some("bgdesk.dmg")
        );
        assert_eq!(
            latest_url(),
            format!("{UPDATE_ORIGIN}/updates/{UPDATE_EDITION}/latest.json")
        );
    }

    #[test]
    fn rejects_other_origins_editions_and_malformed_paths() {
        let release = release_url("v1.5.2");
        let other = if UPDATE_EDITION == "cliente" {
            "suporte"
        } else {
            "cliente"
        };
        for url in [
            release.replace("https:", "http:"),
            release.replace("bgdesk.com", "bgdesk.com.evil.test"),
            release.replace("bgdesk.com", "user@bgdesk.com"),
            release.replace("bgdesk.com", "bgdesk.com:443"),
            release.replace(UPDATE_EDITION, other),
            format!("{release}?x=1"),
            format!("{release}#asset"),
            format!("{release}/extra"),
            format!("{release}/../v1.5.3"),
            release.replace("v1.5.2", "%76%31.5.2"),
            release.replace("v1.5.2", "nightly"),
            "https://github.com/boagestao/bgdesk/releases/tag/v1.5.2".to_owned(),
        ] {
            assert!(release_id_from_update_url(&url).is_err(), "{url}");
        }
        for name in [
            "",
            "..",
            "nested/app.exe",
            "app.exe?x=1",
            "app.exe#x",
            "%2e%2e",
            "C:app.exe",
            "app\\name.exe",
            "app name.exe",
        ] {
            assert!(
                download_file_name(&format!("{release}/{name}")).is_none(),
                "{name}"
            );
        }
        assert!(download_file_name(&format!("{release}//app.exe")).is_none());
        for version in ["v1.5.2-rc1", "0.0.0", "1.2", "65536.1.1"] {
            assert!(display_version_from_release_id(version).is_err());
        }
    }
}
