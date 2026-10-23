use super::*;
use hbb_common::{
    base64::engine::general_purpose::STANDARD,
    sodiumoxide::{self, crypto::sign},
    ResultType,
};
use serde_json::{json, Value};

const KEY_ID: &str = "test-ed25519-main";
const SHA256: &str = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef";

struct Fixture {
    metadata: Vec<u8>,
    signature: Vec<u8>,
    public_key: [u8; 32],
}

fn artifact() -> Value {
    json!({"platform":"windows","arch":"x86_64","format":"exe","url":"https://github.com/rustdesk/rustdesk/releases/download/v1.4.6/rustdesk-1.4.6-x86_64.exe","file_name":"rustdesk-1.4.6-x86_64.exe","size":123456,"sha256":SHA256})
}

fn metadata() -> Value {
    json!({"schema_version":1,"app":"rustdesk","package_id":PUBLIC_UPDATE_PACKAGE_ID,"version":"1.4.6","release_id":"v1.4.6","published_at":"2026-05-14T00:00:00Z","signature_key_id":KEY_ID,"artifacts":[artifact()]})
}

fn set_value(metadata: &mut Value, key: &str, value: Value, artifact_field: bool) {
    let target = if artifact_field {
        &mut metadata["artifacts"][0]
    } else {
        metadata
    };
    target
        .as_object_mut()
        .expect("JSON object")
        .insert(key.to_string(), value);
}

fn sign_fixture(metadata: Value, signature_key_id: &str) -> Fixture {
    sodiumoxide::init().expect("test sodiumoxide init");
    let metadata = serde_json::to_vec(&metadata).expect("metadata JSON");
    let (public_key, secret_key) = sign::gen_keypair();
    let mut signed = UPDATE_METADATA_SIGNATURE_CONTEXT.to_vec();
    signed.extend_from_slice(&metadata);
    let sig = sign::sign_detached(&signed, &secret_key);
    let sig_json = json!({"schema_version":1,"algorithm":"ed25519","key_id":signature_key_id,"signature":STANDARD.encode(sig.to_bytes())});
    Fixture {
        metadata,
        signature: serde_json::to_vec(&sig_json).expect("signature JSON"),
        public_key: public_key.0,
    }
}

fn valid_fixture() -> Fixture {
    sign_fixture(metadata(), KEY_ID)
}

#[test]
fn latest_canonical_json_verifies_the_python_publication_vector() {
    let fixture: Value = serde_json::from_str(include_str!("../res/update/fixtures/signed_latest.json")).unwrap();
    let public_key: [u8; 32] = STANDARD.decode(fixture["public_key"].as_str().unwrap()).unwrap().try_into().unwrap();
    let mut latest = fixture["latest"].clone();
    let signature = latest.as_object_mut().unwrap().remove("signature").unwrap();
    let signature: UpdateSignature = serde_json::from_value(signature).unwrap();
    let bytes = canonical_latest_json(&latest).unwrap();
    verify_metadata_signature(&bytes, &decode_signature(&signature.signature).unwrap(), &key(public_key)).unwrap();
    let mut tampered = latest;
    tampered["version"] = json!("1.5.1-4");
    assert!(verify_metadata_signature(&canonical_latest_json(&tampered).unwrap(),
        &decode_signature(&signature.signature).unwrap(), &key(public_key)).is_err());
}

#[test]
fn latest_feed_authenticates_version_and_all_artifacts_from_one_document() {
    let name = format!("bgdesk-{}-update-win64.exe", crate::update_source::UPDATE_EDITION);
    let mut data = metadata();
    data["artifacts"][0]["file_name"] = json!(name);
    data["artifacts"][0]["url"] = json!(format!("{}/{name}", crate::update_source::UPDATE_ORIGIN));
    let fixture = sign_fixture(data.clone(), KEY_ID);
    let keys = [key(fixture.public_key)];
    data["signature"] = serde_json::from_slice(&fixture.signature).unwrap();
    let feed = serde_json::to_vec_pretty(&data).unwrap();
    let verified = verify_latest_feed_with_keys(&feed, &keys).unwrap();
    assert_eq!(verified.signed_bytes(), feed.as_slice());
    assert_eq!(verified.version(), "1.4.6");
    let artifact = verified.artifact(&query()).unwrap();
    assert_eq!(artifact.sha256, SHA256);
    assert_eq!(artifact.size, 123456);
    assert!(verified.artifact(&UpdateArtifactQuery { arch: "x86", ..query() }).is_err());
    for field in ["version", "package_id"] {
        let mut tampered = data.clone();
        tampered[field] = json!("changed");
        assert!(verify_latest_feed_with_keys(&serde_json::to_vec(&tampered).unwrap(), &keys).is_err());
    }
    data["artifacts"][0]["sha256"] = json!("0".repeat(64));
    assert!(verify_latest_feed_with_keys(&serde_json::to_vec(&data).unwrap(), &keys).is_err());
}

#[test]
fn latest_feed_announces_only_newer_revisions_and_keeps_the_verified_snapshot() {
    for (version, available) in [("65535.0.0", true), (crate::VERSION, false), ("1.0.0", false)] {
        let mut data = metadata();
        let name = format!("bgdesk-{}-update-win64.exe", crate::update_source::UPDATE_EDITION);
        data["version"] = json!(version);
        data["release_id"] = json!(format!("v{version}"));
        data["artifacts"][0]["file_name"] = json!(name);
        data["artifacts"][0]["url"] = json!(format!("{}/{name}", crate::update_source::UPDATE_ORIGIN));
        let fixture = sign_fixture(data, KEY_ID);
        let mut document: Value = serde_json::from_slice(&fixture.metadata).unwrap();
        document["signature"] = serde_json::from_slice(&fixture.signature).unwrap();
        let feed = verify_latest_feed_with_keys(&serde_json::to_vec(&document).unwrap(), &[key(fixture.public_key)]).unwrap();
        crate::common::process_verified_software_update(feed).unwrap();
        assert_eq!(!crate::common::SOFTWARE_UPDATE_URL.lock().unwrap().is_empty(), available);
        assert_eq!(crate::ui_interface::get_new_version(), if available { version } else { "" });
        assert_eq!(crate::updater::latest_update_version(), if available { version } else { "" });
        let selected = crate::updater::verified_update_artifact_for_release_page_url(
            &crate::update_source::latest_url(), query());
        assert_eq!(selected.is_ok(), available);
        if let Ok(selected) = selected {
            assert_eq!(selected.version, version);
            assert_eq!(selected.sha256, SHA256);
        }
        assert!(crate::updater::verified_update_artifact_for_release_page_url(
            "https://untrusted.example/latest.json", query()).is_err());
    }
}

#[test]
fn latest_feed_rejects_signed_wrong_edition_origin_paths_duplicates_and_invalid_revisions() {
    let name = format!("bgdesk-{}-update-win64.exe", crate::update_source::UPDATE_EDITION);
    let origin = crate::update_source::UPDATE_ORIGIN;
    let mut original = metadata();
    original["artifacts"][0]["file_name"] = json!(name);
    original["artifacts"][0]["url"] = json!(format!("{origin}/{name}"));
    let mut cases = Vec::new();
    for url in [format!("https://untrusted.example/{name}"), format!("{origin}/nested/{name}"),
                format!("{origin}/updates/suporte/v1.4.6/{name}"), format!("{origin}/{name}?x=1")] {
        let mut data = original.clone();
        data["artifacts"][0]["url"] = json!(url);
        cases.push(data);
    }
    for (field, value) in [("package_id", json!("other-edition")), ("version", json!("1.5.1-rc1")),
                           ("release_id", json!("v1.5.2")), ("artifacts", json!([]))] {
        let mut data = original.clone();
        data[field] = value;
        cases.push(data);
    }
    let mut duplicate = original.clone();
    duplicate["artifacts"].as_array_mut().unwrap().push(original["artifacts"][0].clone());
    cases.push(duplicate);
    for data in cases {
        let fixture = sign_fixture(data, KEY_ID);
        let mut feed: Value = serde_json::from_slice(&fixture.metadata).unwrap();
        feed["signature"] = serde_json::from_slice(&fixture.signature).unwrap();
        assert!(verify_latest_feed_with_keys(&serde_json::to_vec(&feed).unwrap(), &[key(fixture.public_key)]).is_err());
    }
}

#[test]
fn signed_root_downloads_keep_hash_identity_and_reject_other_origins_and_nested_paths() {
    let name = format!("bgdesk-{}-update-win64.exe", crate::update_source::UPDATE_EDITION);
    let origin = crate::update_source::UPDATE_ORIGIN;
    let root = format!("{origin}/");
    let release = format!("{origin}/updates/{}/v1.4.6/", crate::update_source::UPDATE_EDITION);
    for url in [format!("{root}{name}"), format!("{release}{name}")] {
        let mut document = metadata();
        document["artifacts"][0]["file_name"] = json!(name);
        document["artifacts"][0]["url"] = json!(url);
        let fixture = sign_fixture(document, KEY_ID);
        let keys = [key(fixture.public_key)];
        let verify = |data: &Fixture| verify_update_metadata_with_options(&data.metadata, &data.signature,
            VerificationOptions {
                requirements: requirements(query()), expected_package_id: PUBLIC_UPDATE_PACKAGE_ID,
                artifact_url_policy: ArtifactUrlPolicy::ReleaseOrRoot { release_prefix: &release, root_prefix: &root },
                trusted_keys: &keys,
            });
        let verified = verify(&fixture).unwrap();
        assert_eq!(verified.sha256, SHA256);
        assert_eq!(verified.size, 123456);
        let mut corrupt = fixture;
        corrupt.metadata.push(b' ');
        assert!(verify(&corrupt).is_err());
    }
    for url in [format!("https://untrusted.example/{name}"), format!("{origin}/nested/{name}"),
                format!("{origin}:443/{name}"), format!("{root}{name}?x=1"),
                format!("{root}{name}#fragment"), format!("{origin}//{name}")] {
        let mut document = metadata();
        document["artifacts"][0]["file_name"] = json!(name);
        document["artifacts"][0]["url"] = json!(url);
        let fixture = sign_fixture(document, KEY_ID);
        let keys = [key(fixture.public_key)];
        assert!(verify_update_metadata_with_options(&fixture.metadata, &fixture.signature,
            VerificationOptions {
                requirements: requirements(query()), expected_package_id: PUBLIC_UPDATE_PACKAGE_ID,
                artifact_url_policy: ArtifactUrlPolicy::ReleaseOrRoot { release_prefix: &release, root_prefix: &root },
                trusted_keys: &keys,
            }).is_err(), "{url}");
    }
}
fn key(public_key: [u8; 32]) -> TrustedUpdateKey {
    TrustedUpdateKey {
        key_id: KEY_ID,
        algorithm: "ed25519",
        public_key,
    }
}
fn query<'a>() -> UpdateArtifactQuery<'a> {
    UpdateArtifactQuery {
        platform: "windows",
        arch: "x86_64",
        format: "exe",
    }
}
fn requirements<'a>(artifact: UpdateArtifactQuery<'a>) -> MetadataRequirements<'a> {
    MetadataRequirements {
        expected_version: "1.4.6",
        expected_release_id: "v1.4.6",
        artifact,
    }
}
fn verify_with_query(
    fixture: &Fixture,
    query: &UpdateArtifactQuery<'_>,
) -> ResultType<VerifiedUpdateArtifact> {
    let trusted_keys = [key(fixture.public_key)];
    verify_update_metadata_with_options(
        &fixture.metadata,
        &fixture.signature,
        VerificationOptions {
            requirements: requirements(*query),
            expected_package_id: PUBLIC_UPDATE_PACKAGE_ID,
            artifact_url_policy: ArtifactUrlPolicy::ExactPrefix(
                "https://github.com/rustdesk/rustdesk/releases/download/v1.4.6/",
            ),
            trusted_keys: &trusted_keys,
        },
    )
}

fn verify(fixture: &Fixture) -> ResultType<VerifiedUpdateArtifact> {
    verify_with_query(fixture, &query())
}

#[test]
fn accepts_valid_metadata_and_signature() {
    let artifact = verify(&valid_fixture()).expect("verified artifact");
    assert_eq!("rustdesk-1.4.6-x86_64.exe", artifact.file_name);
    assert_eq!(123456, artifact.size);
    assert_eq!(SHA256, artifact.sha256);
    assert_eq!("1.4.6", artifact.version);
}

#[test]
fn signed_revision_requires_exact_version_signature_and_architecture() {
    let prefix = "https://updates.example.com/releases/v1.5.1-2/";
    let mut data = metadata();
    data["version"] = json!("1.5.1-2");
    data["release_id"] = json!("v1.5.1-2");
    data["artifacts"][0]["url"] = json!(format!("{prefix}rustdesk-1.4.6-x86_64.exe"));
    let mut fixture = sign_fixture(data, KEY_ID);
    let keys = [key(fixture.public_key)];
    let verify_revision = |fixture: &Fixture, version: &str, arch: &str| {
        verify_update_metadata_with_options(&fixture.metadata, &fixture.signature, VerificationOptions {
            requirements: MetadataRequirements {
                expected_version: version, expected_release_id: "v1.5.1-2",
                artifact: UpdateArtifactQuery { platform: "windows", arch, format: "exe" },
            },
            expected_package_id: PUBLIC_UPDATE_PACKAGE_ID,
            artifact_url_policy: ArtifactUrlPolicy::ExactPrefix(prefix), trusted_keys: &keys,
        })
    };
    let verified = verify_revision(&fixture, "1.5.1-2", "x86_64").unwrap();
    assert_eq!(verified.version, "1.5.1-2");
    assert_eq!(verified.sha256, SHA256);
    assert_eq!(verified.size, 123456);
    assert!(verify_revision(&fixture, "1.5.1-1", "x86_64").is_err());
    assert!(verify_revision(&fixture, "1.5.1-2", "x86").is_err());
    fixture.metadata.push(b' ');
    assert!(verify_revision(&fixture, "1.5.1-2", "x86_64").is_err());
}

#[test]
fn website_update_metadata_requires_own_edition_even_with_valid_signature() {
    let prefix = format!("{}/", crate::update_source::release_url("v1.4.6"));
    let mut data = metadata();
    data["artifacts"][0]["url"] = json!(format!("{prefix}rustdesk-1.4.6-x86_64.exe"));
    let verify_website = |fixture: &Fixture| {
        let trusted_keys = [key(fixture.public_key)];
        verify_update_metadata_with_options(
            &fixture.metadata,
            &fixture.signature,
            VerificationOptions {
                requirements: requirements(query()),
                expected_package_id: PUBLIC_UPDATE_PACKAGE_ID,
                artifact_url_policy: ArtifactUrlPolicy::ExactPrefix(&prefix),
                trusted_keys: &trusted_keys,
            },
        )
    };
    assert!(verify_website(&sign_fixture(data.clone(), KEY_ID)).is_ok());
    let other = if PUBLIC_UPDATE_PACKAGE_ID == "bgdesk-cliente" {
        "bgdesk-suporte"
    } else {
        "bgdesk-cliente"
    };
    data["package_id"] = json!(other);
    assert!(verify_website(&sign_fixture(data, KEY_ID)).is_err());
}

#[test]
fn rejects_bad_signature_or_tampered_metadata() {
    let mut fixture = valid_fixture();
    fixture.metadata.push(b' ');
    assert!(verify(&fixture).is_err());
    for (key, value) in [
        ("schema_version", json!(2)),
        ("algorithm", json!("rsa")),
        ("signature", json!("not base64")),
        ("signature", json!(STANDARD.encode([1u8; 63]))),
    ] {
        let mut fixture = valid_fixture();
        let mut sig: Value = serde_json::from_slice(&fixture.signature).expect("signature");
        sig.as_object_mut()
            .expect("signature object")
            .insert(key.to_string(), value);
        fixture.signature = serde_json::to_vec(&sig).expect("signature bytes");
        assert!(verify(&fixture).is_err(), "{}", key);
    }
}

#[test]
fn rejects_schema_policy_artifact_and_url_mismatches() {
    let cases = [
        ("schema_version", json!(2), false), ("app", json!("other"), false),
        ("version", json!("1.4.7"), false), ("release_id", json!("v1.4.7"), false),
        ("package_id", json!("custom"), false), ("signature_key_id", json!("different-key"), false),
        ("arch", json!("x86"), true),
        ("sha256", json!("not-a-sha256"), true),
        ("url", json!("https://github.com/rustdesk/rustdesk/releases/download/v1.4.7/rustdesk-1.4.6-x86_64.exe"), true),
        ("url", json!("https://github.com/rustdesk/rustdesk/releases/download/v1.4.6/other.exe"), true),
    ];
    for (key, value, artifact_field) in cases {
        let mut metadata = metadata();
        set_value(&mut metadata, key, value, artifact_field);
        assert!(verify(&sign_fixture(metadata, KEY_ID)).is_err(), "{}", key);
    }
}

#[test]
fn rejects_artifact_file_name_path_components() {
    for file_name in [
        "",
        "nested/rustdesk.exe",
        r"nested\rustdesk.exe",
        "..",
        "rust desk.exe",
        "rustdesk*.exe",
        "rustdesk\n.exe",
        "rüstdesk.exe",
    ] {
        let mut invalid_metadata = metadata();
        invalid_metadata["artifacts"][0]["file_name"] = json!(file_name);
        invalid_metadata["artifacts"][0]["url"] = json!(format!(
            "https://github.com/rustdesk/rustdesk/releases/download/v1.4.6/{file_name}"
        ));
        let fixture = sign_fixture(invalid_metadata, KEY_ID);

        let error = verify_with_query(&fixture, &query())
            .err()
            .expect("invalid file name");

        assert_eq!("invalid update artifact file name", error.to_string());
    }
}

#[test]
fn verifies_metadata_generated_by_python_release_script_fixture() {
    const PYTHON_KEY_ID: &str = "python-test-ed25519-main";
    let metadata = br#"{"schema_version":1,"app":"rustdesk","package_id":"rustdesk","version":"1.4.6","release_id":"v1.4.6","published_at":"2026-05-14T00:00:00Z","signature_key_id":"python-test-ed25519-main","artifacts":[{"platform":"windows","arch":"x86_64","format":"exe","url":"https://github.com/rustdesk/rustdesk/releases/download/v1.4.6/rustdesk-1.4.6-x86_64.exe","file_name":"rustdesk-1.4.6-x86_64.exe","size":8,"sha256":"304ca1638c5effa6832e0e15b958a8f74847efe4df9c3f3187216e921c168fed"}]}"#;
    let signature = br#"{"schema_version":1,"algorithm":"ed25519","key_id":"python-test-ed25519-main","signature":"ZMcod9VNaEGTYK0gIfGmMQ44HAvrYAkYDyIL9JTKjzUH+hVFYs8KpvnGSlteAHwqiJuJDdiKBVCPEdtcRRAJCA=="}"#;
    let trusted_key = TrustedUpdateKey {
        key_id: PYTHON_KEY_ID,
        algorithm: "ed25519",
        public_key: [
            3, 161, 7, 191, 243, 206, 16, 190, 29, 112, 221, 24, 231, 75, 192, 153, 103, 228, 214,
            48, 155, 165, 13, 95, 29, 220, 134, 100, 18, 85, 49, 184,
        ],
    };

    let trusted_keys = [trusted_key];
    let artifact = verify_update_metadata_with_options(
        metadata,
        signature,
        VerificationOptions {
            requirements: requirements(query()),
            expected_package_id: "rustdesk",
            artifact_url_policy: ArtifactUrlPolicy::ExactPrefix(
                "https://github.com/rustdesk/rustdesk/releases/download/v1.4.6/",
            ),
            trusted_keys: &trusted_keys,
        },
    )
    .expect("Python-generated update metadata verifies");

    assert_eq!("rustdesk-1.4.6-x86_64.exe", artifact.file_name);
}

#[path = "update_metadata/offline_tests.rs"]
mod offline_tests;
