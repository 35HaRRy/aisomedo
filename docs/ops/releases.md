# Android releases

Android distribution is independent of VPS deployment. The `android-release`
workflow builds tags named `android-v<versionName>` from commits on main and
publishes `aisomedo.apk` plus its SHA-256 checksum through GitHub Releases.
No Play Store account or SSH connection is involved.

## One-time signing setup

Create a dedicated release keystore and store an encrypted offline backup with
its alias and passwords. Keep using the same key: Android cannot install an
update signed by a different key over an existing installation. Never commit
the keystore, passwords, or their base64 representation.

Create the `android-release` GitHub environment; restrict eligible tags to
`android-v*` and restrict who can create release tags. Configure secrets:

- `ANDROID_KEYSTORE_BASE64`: base64 encoding of the binary keystore.
- `ANDROID_KEYSTORE_PASSWORD`: keystore password.
- `ANDROID_KEY_ALIAS`: release-key alias, not the debug alias.
- `ANDROID_KEY_PASSWORD`: private-key password.

Optional environment reviewers can protect release signing. Missing secrets
fail before building; temporary keystores are removed even on failure.

## Release procedure

1. Increase `versionCode` in `android/app/build.gradle.kts` for every release;
   choose `versionName` and merge the version update to main after CI passes.
2. Create/push matching `android-v<versionName>` tag on that main commit.
3. Verify workflow success and the APK/checksum attached to the Release.
4. Set production `ANDROID_CURRENT_VERSION_CODE` to the distributed code and
   `ANDROID_UPDATE_URL` to the release APK. Empty `ANDROID_MIN_VERSION_CODE`
   preserves the backend's N/N-1 policy. Backend deploys do not bump these values.

The workflow runs release unit tests/lint, validates the APK signature with
`apksigner`, rejects a debug certificate, and uploads into a draft Release
before publishing it. It never overwrites a published release. If publication
fails midway, inspect and remove only the incomplete draft before rerunning.

The stable URL is `https://github.com/OWNER/REPO/releases/latest/download/aisomedo.apk`.
Private repositories require download authentication; use a public repository
or another operator-managed HTTPS distribution endpoint if administrators must
download without GitHub credentials. Never make repository/package visibility
public automatically.
