import 'package:flutter/material.dart';

import '../../common.dart';
import '../../models/platform_model.dart';

const _licenseDialogTag = 'bgdesk-license';

/// Returns true when a valid license is available (suporte edition only).
Future<bool> ensureLicenseBeforeConnect() async {
  if (bind.isIncomingOnly()) {
    return true;
  }
  if (bind.mainTryValidateStoredLicense()) {
    return true;
  }
  return showLicenseDialogAndWait();
}

Future<bool> showLicenseDialogAndWait() async {
  if (bind.isIncomingOnly()) {
    return true;
  }
  gFFI.dialogManager.dismissByTag(_licenseDialogTag);

  final keyController = TextEditingController();
  var errorText = '';
  var isInProgress = false;

  final result = await gFFI.dialogManager.show<bool>((setState, close, context) {
    cancel() {
      close(false);
    }

    submit() async {
      if (isInProgress) return;
      final key = keyController.text.trim();
      if (key.isEmpty) {
        setState(() {
          errorText = translate('Invalid license');
        });
        return;
      }
      setState(() {
        errorText = '';
        isInProgress = true;
      });
      String res;
      try {
        res = await bind.mainValidateLicense(key: key);
      } catch (e) {
        setState(() {
          errorText = translate(
              'Could not register the license. Check your internet connection and try again.');
          isInProgress = false;
        });
        return;
      }
      if (res.isEmpty) {
        if (context.mounted) {
          close(true);
        }
      } else {
        if (!context.mounted) return;
        setState(() {
          errorText = res;
          isInProgress = false;
        });
      }
    }

    return CustomAlertDialog(
      title: Text(translate('License required')),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(translate('Enter your registration key to connect.')),
          const SizedBox(height: 12),
          TextField(
            controller: keyController,
            decoration: InputDecoration(
              labelText: translate('Registration key'),
              errorText: errorText.isEmpty ? null : errorText,
            ),
            enabled: !isInProgress,
            autofocus: true,
            onSubmitted: (_) => submit(),
          ).workaroundFreezeLinuxMint(),
        ],
      ),
      actions: [
        dialogButton('Cancel',
            onPressed: isInProgress ? null : cancel, isOutline: true),
        dialogButton('OK', onPressed: isInProgress ? null : submit),
      ],
      onSubmit: submit,
      onCancel: cancel,
    );
  }, tag: _licenseDialogTag);

  return result == true;
}
