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
    parse_update_version(version)?;
    Ok(version.to_owned())
}

// BGDesk revisions are stable local revisions, not SemVer prereleases.
// Do not use this ordering for peer/protocol capability negotiation.
pub(crate) fn parse_update_version(version: &str) -> ResultType<[u16; 4]> {
    let (base, revision) = version.split_once('-').unwrap_or((version, "0"));
    let mut result = [0; 4];
    let parts: Vec<_> = base.split('.').collect();
    if parts.len() != 3 {
        bail!("Invalid BGDesk version: {version}");
    }
    for (index, value) in parts.into_iter().chain(std::iter::once(revision)).enumerate() {
        if value.is_empty() || !value.bytes().all(|b| b.is_ascii_digit())
            || (value.len() > 1 && value.starts_with('0')) {
            bail!("Invalid BGDesk version: {version}");
        }
        result[index] = value.parse()?;
    }
    if result[..3] == [0, 0, 0] || (version.contains('-') && result[3] == 0) {
        bail!("Invalid BGDesk version: {version}");
    }
    Ok(result)
}

pub(crate) fn is_newer_update(candidate: &str, installed: &str) -> ResultType<bool> {
    Ok(parse_update_version(candidate)? > parse_update_version(installed)?)
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
    if file_name.is_empty()
        || matches!(file_name, "." | "..")
        || !file_name
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b'-'))
    {
        return None;
    }
    if release == UPDATE_ORIGIN && file_name.starts_with(&format!("bgdesk-{UPDATE_EDITION}-")) {
        return Some(file_name);
    }
    release_id_from_update_url(release).ok()?;
    // A release URL may have a trailing slash, but artifact paths must be canonical.
    let release_id = release_id_from_update_url(release).ok()?;
    (download_url == format!("{}/{file_name}", release_url(&release_id))).then_some(file_name)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn revisions_are_ordered_numerically_without_overlapping_the_next_base() {
        let versions = ["1.5.1", "1.5.1-1", "1.5.1-2", "1.5.1-10", "1.5.1-65535", "1.5.2"];
        for (i, installed) in versions.iter().enumerate() {
            for (j, candidate) in versions.iter().enumerate() {
                assert_eq!(is_newer_update(candidate, installed).unwrap(), j > i);
            }
        }
        assert_eq!(display_version_from_release_id("v1.5.1-10").unwrap(), "1.5.1-10");
        for version in ["1.5.1-b", "1.5.1-0", "1.5.1-01", "1.5.1-65536", "1.5.1.1", "1.5.1-1+69", "01.5.1"] {
            assert!(parse_update_version(version).is_err(), "{version}");
        }
    }

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

    #[test]
    fn accepts_same_edition_downloads_at_root_without_relaxing_origin_or_path_checks() {
        let name = format!("bgdesk-{UPDATE_EDITION}-update-win64.exe");
        assert_eq!(
            download_file_name(&format!("{UPDATE_ORIGIN}/{name}")),
            Some(name.as_str())
        );
        for url in [
            format!("{UPDATE_ORIGIN}/nested/{name}"),
            format!("{UPDATE_ORIGIN}//{name}"),
            format!("{UPDATE_ORIGIN}/{name}?x=1"),
            format!("{UPDATE_ORIGIN}/{name}#fragment"),
            format!("{UPDATE_ORIGIN}/{name}/../app.exe"),
            format!("{UPDATE_ORIGIN}/app.exe"),
            format!("https://untrusted.example/{name}"),
            format!("{UPDATE_ORIGIN}:443/{name}"),
        ] {
            assert!(download_file_name(&url).is_none(), "{url}");
        }
        let other = if UPDATE_EDITION == "cliente" {
            "suporte"
        } else {
            "cliente"
        };
        assert!(
            download_file_name(&format!("{UPDATE_ORIGIN}/bgdesk-{other}-update-win64.exe"))
                .is_none()
        );
    }
}
