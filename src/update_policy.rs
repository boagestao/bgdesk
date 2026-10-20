//! Public distribution identity is separate from legacy custom-client branding.
use std::sync::atomic::{AtomicBool, Ordering};

pub(crate) static CHANNEL: UpdateChannelPolicy = UpdateChannelPolicy::new();

pub(crate) struct UpdateChannelPolicy {
    custom_config_loaded: AtomicBool,
}

impl UpdateChannelPolicy {
    const fn new() -> Self {
        Self {
            custom_config_loaded: AtomicBool::new(false),
        }
    }

    /// Call only after a custom configuration's signature and JSON are validated.
    /// Even a custom configuration retaining the BGDesk name must stay isolated.
    pub(crate) fn mark_custom_config_loaded(&self) {
        self.custom_config_loaded.store(true, Ordering::SeqCst);
    }

    pub(crate) fn uses_public_channel(&self, app_name: &str) -> bool {
        app_name == "BGDesk" && !self.custom_config_loaded.load(Ordering::SeqCst)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn public_bgdesk_is_eligible_without_changing_legacy_branding() {
        let policy = UpdateChannelPolicy::new();
        assert!(policy.uses_public_channel("BGDesk"));
        for name in [
            "RustDesk",
            "Other Client",
            "BGDesk Pro",
            "bgdesk",
            "BGDesk ",
            "",
        ] {
            assert!(!policy.uses_public_channel(name), "{name}");
        }
    }

    #[test]
    fn custom_configuration_never_joins_public_channel_even_with_the_same_name() {
        let policy = UpdateChannelPolicy::new();
        assert!(policy.uses_public_channel("BGDesk"));
        policy.mark_custom_config_loaded();
        assert!(!policy.uses_public_channel("BGDesk"));
        assert!(!policy.uses_public_channel("Other Client"));
        policy.mark_custom_config_loaded();
        assert!(!policy.uses_public_channel("BGDesk"));
    }
}
