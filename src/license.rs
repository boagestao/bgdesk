use hbb_common::{
    anyhow::{anyhow, bail, Context},
    config::{self, Config},
    log,
    password_security::{decrypt_str_or_original, encrypt_str_or_original},
    ResultType,
};
use jsonwebtoken::{decode, Algorithm, DecodingKey, Validation};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::time::{SystemTime, UNIX_EPOCH};

use crate::ui_interface::{get_fingerprint, set_local_option};

pub const LOCAL_OPTION_LICENSE_KEY: &str = "bgdesk-license-key";
const LOCAL_OPTION_LICENSE_SESSION: &str = "bgdesk-license-session";
const PASSWORD_ENC_VERSION: &str = "00";
/// JWT + metadata may exceed the default password encrypt limit (128 chars).
const LICENSE_SESSION_ENCRYPT_MAX_LEN: usize = 8192;

#[derive(Debug, Clone, Serialize, Deserialize)]
struct LicenseSession {
    license_key: String,
    token: String,
    iat: i64,
    expires_at: i64,
}

#[derive(Debug, Deserialize)]
struct LicenseResponse {
    iat: Value,
    token: String,
    #[serde(rename = "expiresIn")]
    expires_in: u64,
}

#[derive(Debug, Deserialize)]
struct LicenseJwtClaims {
    #[serde(default)]
    exp: Option<i64>,
    #[serde(default)]
    iat: Option<i64>,
}

fn validate_jwt_token(token: &str) -> ResultType<()> {
    let secret = config::license_jwt_secret();
    if secret.is_empty() {
        bail!("license jwt secret is not configured");
    }
    let key = DecodingKey::from_secret(secret.as_bytes());
    let mut validation = Validation::new(Algorithm::HS256);
    validation.validate_exp = true;
    decode::<LicenseJwtClaims>(token, &key, &validation)
        .map_err(|e| anyhow!("invalid license token: {e}"))?;
    Ok(())
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum LicenseValidationError {
    EmptyKey,
    InvalidLicense,
    ConnectionError,
    RemoteServerError,
}

impl LicenseValidationError {
    pub fn message_key(&self) -> &'static str {
        match self {
            Self::EmptyKey | Self::InvalidLicense => "Invalid license",
            Self::ConnectionError => {
                "Could not register the license. Check your internet connection and try again."
            }
            Self::RemoteServerError => {
                "Remote server error. Contact support for more information."
            }
        }
    }
}

impl std::fmt::Display for LicenseValidationError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(self.message_key())
    }
}

impl std::error::Error for LicenseValidationError {}

pub fn get_license_server_url() -> String {
    config::LICENSE_SERVER_URL.to_owned()
}

pub fn get_stored_license_key() -> String {
    crate::get_local_option(LOCAL_OPTION_LICENSE_KEY)
}

pub fn set_license_key(key: &str) {
    let key = key.trim();
    let prev = get_stored_license_key();
    if prev != key {
        clear_license_session();
    }
    set_local_option(LOCAL_OPTION_LICENSE_KEY.to_owned(), key.to_owned());
}

pub fn clear_license_key() {
    set_local_option(LOCAL_OPTION_LICENSE_KEY.to_owned(), String::new());
    clear_license_session();
}

fn now_unix() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0)
}

fn parse_iat(value: &Value) -> ResultType<i64> {
    match value {
        Value::Number(n) => n
            .as_i64()
            .or_else(|| n.as_u64().map(|v| v as i64))
            .ok_or_else(|| anyhow!("invalid iat number")),
        Value::String(s) => {
            if let Ok(v) = s.parse::<i64>() {
                return Ok(v);
            }
            chrono::DateTime::parse_from_rfc3339(s)
                .map(|dt| dt.timestamp())
                .with_context(|| format!("invalid iat datetime: {s}"))
        }
        _ => bail!("invalid iat type"),
    }
}

fn load_license_session() -> Option<LicenseSession> {
    let stored = crate::get_local_option(LOCAL_OPTION_LICENSE_SESSION);
    if stored.is_empty() {
        return None;
    }
    let (plain, _, _) = decrypt_str_or_original(&stored, PASSWORD_ENC_VERSION);
    if plain.is_empty() {
        return None;
    }
    serde_json::from_str(&plain).ok()
}

fn save_license_session(session: &LicenseSession) {
    let plain = serde_json::to_string(session).unwrap_or_default();
    if plain.is_empty() {
        return;
    }
    let encrypted =
        encrypt_str_or_original(&plain, PASSWORD_ENC_VERSION, LICENSE_SESSION_ENCRYPT_MAX_LEN);
    if encrypted.is_empty() {
        log::error!("failed to encrypt license session");
        return;
    }
    set_local_option(LOCAL_OPTION_LICENSE_SESSION.to_owned(), encrypted);
}

fn clear_license_session() {
    if crate::get_local_option(LOCAL_OPTION_LICENSE_SESSION).is_empty() {
        return;
    }
    set_local_option(LOCAL_OPTION_LICENSE_SESSION.to_owned(), String::new());
}

fn session_is_valid(session: &LicenseSession, license_key: &str) -> bool {
    session.license_key == license_key
        && now_unix() < session.expires_at
        && validate_jwt_token(&session.token).is_ok()
}

fn license_session_from_response(license_key: &str, resp: LicenseResponse) -> ResultType<LicenseSession> {
    validate_jwt_token(&resp.token)?;
    let iat = parse_iat(&resp.iat)?;
    let expires_at = iat.saturating_add(resp.expires_in as i64);
    Ok(LicenseSession {
        license_key: license_key.to_owned(),
        token: resp.token,
        iat,
        expires_at,
    })
}

#[cfg(not(any(target_os = "android", target_os = "ios")))]
async fn fingerprint_for_license_async() -> String {
    crate::ipc::get_fingerprint_async().await
}

#[cfg(any(target_os = "android", target_os = "ios"))]
async fn fingerprint_for_license_async() -> String {
    get_fingerprint()
}

#[cfg(not(any(target_os = "android", target_os = "ios")))]
fn fingerprint_for_license_sync() -> String {
    std::thread::spawn(|| {
        let rt = match hbb_common::tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
        {
            Ok(rt) => rt,
            Err(e) => {
                log::error!("Failed to build runtime for license fingerprint: {}", e);
                return String::new();
            }
        };
        rt.block_on(fingerprint_for_license_async())
    })
    .join()
    .unwrap_or_default()
}

#[cfg(any(target_os = "android", target_os = "ios"))]
fn fingerprint_for_license_sync() -> String {
    get_fingerprint()
}

fn request_license_token_sync(key: &str) -> Result<LicenseSession, LicenseValidationError> {
    let url = format!("{}/bgdesk", get_license_server_url().trim_end_matches('/'));
    let body = json!({
        "Chave": key,
        "Fingerprint": fingerprint_for_license_sync(),
        "BGDeskId": Config::get_id(),
    })
    .to_string();

    let client = crate::hbbs_http::create_http_client_with_url(&url);
    let response = client
        .post(&url)
        .header("Content-Type", "application/json")
        .body(body)
        .send()
        .map_err(|e| {
            log::debug!("License request failed: {}", e);
            LicenseValidationError::ConnectionError
        })?;

    let status = response.status().as_u16();
    if status != 200 {
        log::debug!("License request returned status {}", status);
        return Err(match status {
            403 => LicenseValidationError::InvalidLicense,
            500 => LicenseValidationError::RemoteServerError,
            _ => LicenseValidationError::ConnectionError,
        });
    }

    let text = response.text().map_err(|e| {
        log::debug!("Failed to read license response body: {}", e);
        LicenseValidationError::ConnectionError
    })?;
    let resp: LicenseResponse = serde_json::from_str(&text).map_err(|e| {
        log::debug!("Invalid license response json: {} ({})", text, e);
        LicenseValidationError::RemoteServerError
    })?;
    license_session_from_response(key, resp).map_err(|e| {
        log::debug!("Invalid license token in response: {}", e);
        LicenseValidationError::RemoteServerError
    })
}

fn ensure_license_session_sync(key: &str) -> Result<(), LicenseValidationError> {
    if let Some(session) = load_license_session() {
        if session_is_valid(&session, key) {
            return Ok(());
        }
        if session.license_key == key {
            log::info!("Cached license token is invalid or expired, requesting a new one");
            clear_license_session();
        }
    }
    let session = request_license_token_sync(key)?;
    save_license_session(&session);
    Ok(())
}

pub fn validate_license_sync(key: &str) -> Result<(), LicenseValidationError> {
    let key = key.trim();
    if key.is_empty() {
        return Err(LicenseValidationError::EmptyKey);
    }
    ensure_license_session_sync(key)
}

pub async fn validate_license(key: &str) -> ResultType<()> {
    let key = key.trim().to_owned();
    if key.is_empty() {
        bail!("{}", LicenseValidationError::EmptyKey);
    }
    hbb_common::tokio::task::spawn_blocking(move || ensure_license_session_sync(&key))
        .await
        .map_err(|e| anyhow!("license validation task failed: {e}"))?
        .map_err(|e| anyhow!(crate::lang::translate(e.message_key().to_owned())))?;
    Ok(())
}

/// Ensures a license key is present before outbound connections (suporte edition only).
pub async fn ensure_license_valid() -> ResultType<()> {
    if config::is_incoming_only() {
        return Ok(());
    }
    let key = get_stored_license_key();
    if key.is_empty() {
        bail!("License required");
    }
    if let Some(session) = load_license_session() {
        if session_is_valid(&session, &key) {
            return Ok(());
        }
    }
    ensure_license_session_sync(&key)
        .map_err(|e| anyhow!(crate::lang::translate(e.message_key().to_owned())))?;
    Ok(())
}

pub fn try_validate_stored_license() -> bool {
    if config::is_incoming_only() {
        return true;
    }
    let stored = get_stored_license_key();
    if stored.is_empty() {
        return false;
    }
    match ensure_license_session_sync(&stored) {
        Ok(()) => true,
        Err(e) => {
            log::info!("License validation failed: {}", e);
            if e == LicenseValidationError::InvalidLicense {
                clear_license_key();
            }
            false
        }
    }
}
